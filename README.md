# Asistente de WhatsApp — Consultorio Dr. José Guadalupe Padilla

Cirugía General y Laparoscópica · Guadalajara

Asistente que atiende WhatsApp 24/7: conversa con naturalidad, agenda en la
agenda real del consultorio, envía recordatorios y pasa la conversación a
una persona cuando hace falta criterio humano.

---

## Estado

**Fase 1 — software completo.** Circuito entero, de mensaje entrante a cita
agendada, funcionando contra el número de prueba de Meta. Lo único que falta
para entregar es el acceso a Meta y el contenido del consultorio: no queda
nada por programar.

| Componente | Estado |
|---|---|
| Barrera clínica | ✅ funcionando, 69 pruebas |
| Clasificación de intención | ✅ funcionando |
| Reglas de escalado | ✅ funcionando |
| Flujos determinísticos (modo básico) | ✅ funcionando |
| Capa de IA con tope de gasto | ✅ funcionando |
| Webhook de WhatsApp con validación de firma | ✅ funcionando |
| Agenda — Plan B (calendario) | ✅ funcionando |
| **Panel de control** | ✅ funcionando, con acceso por usuario |
| **Recordatorios y ciclo de la cita** | ✅ funcionando |
| **Modo fuera de horario** | ✅ funcionando |
| **Edición de contenido desde el panel** | ✅ funcionando |
| **Agenda y citas por cargar** | ✅ funcionando |
| **Registro de actividad** | ✅ funcionando |
| **Zona horaria del consultorio** | ✅ funcionando |
| **App instalable y avisos push** | ✅ funcionando |
| **Derivación a otro profesional** | ✅ funcionando |
| **Agenda — Plan C (Google Calendar)** | ✅ construido y en pausa |
| Agenda — Plan A (API Doctoralia) | ❌ descartado · Doctoralia confirmó que no hay API |
| Plantillas de Meta | ⏳ redactadas, a la espera de acceso para enviarlas |

El número real del consultorio **sigue funcionando normalmente en el
celular**. Se migra a la API el día 14, en horario de cierre, con el panel
ya terminado y el personal capacitado.

---

## Puesta en marcha

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows
pip install -r requirements.txt

cp .env.example .env            # completar credenciales
python -m app.seed              # datos iniciales
python -m app.demo              # conversaciones de ejemplo, para ver el panel con contenido

uvicorn app.main:aplicacion --reload
```

- **Simulador: <http://localhost:8000/simulador>** — conversar con el
  asistente sin tener nada configurado en Meta
- Panel: <http://localhost:8000/panel>
- Diagnóstico de Meta: <http://localhost:8000/diagnostico> — estado de la
  configuración consultado directamente a Meta, sin entrar a su consola
- Estado del servicio: <http://localhost:8000/salud>
- Maqueta aprobada: <http://localhost:8000/maqueta>
- Documentación de la API: <http://localhost:8000/docs>

Usuarios que crea el `seed`, **con contraseña a cambiar en el primer acceso**:
`doctor@consultorio.local` y `asistente@consultorio.local`.

Pruebas:

```bash
pytest -q
```

---

## Cómo circula un mensaje

```
WhatsApp
   │
   ▼
webhook.py ──── valida firma X-Hub-Signature-256 ──── responde 200 de inmediato
   │
   ▼
router.py
   │
   ├─ 1.  Guardar el mensaje                    nunca se pierde nada
   ├─ 2.  ¿La lleva una persona?                → el bot calla
   ├─ 3.  BARRERA CLÍNICA  (safety.py)          → antes que todo lo demás
   ├─ 4.  Clasificar intención  (intents.py)    reglas, costo cero
   ├─ 5.  ¿Escalar?  (escalation.py)            → derivar y avisar
   ├─ 5b. ¿Busca a otro profesional?            → pasarle el número correcto
   ├─ 6.  LA IA CONVERSA  (ai.py)               con la agenda real en la mano
   ├─ 7.  Flujos  (flows.py)                    modo básico, o si la IA no está
   └─ 8.  Si nada resolvió                      → derivar a una persona
```

**Dos invariantes:**

La IA **nunca** ve un mensaje que la barrera clínica bloqueó. Por eso el
paso 3 va antes que el 6.

Si la IA no está —sin clave, sin presupuesto, con OpenAI caído— el paso 7
atiende igual. El paciente no se entera; el consultorio lo ve en el panel.

---

## La barrera clínica

`app/brain/safety.py` es el módulo más importante del proyecto y el único
que no admite atajos.

- Es **determinístico**. No depende de un modelo de lenguaje, porque un
  modelo puede fallar y aquí el costo de fallar lo paga un paciente.
- Corre **antes** de clasificar y antes de cualquier llamada a la IA.
- **Ante la duda, deriva.** Nunca tranquiliza, nunca minimiza, nunca
  interpreta.
- Cualquier adjunto (foto, estudio, audio) se deriva **sin descargarse**.

Qué detecta y qué hace:

| Situación | Acción |
|---|---|
| Signos de alarma (fiebre alta, sangrado, herida abierta, no puede respirar…) | Indica acudir a urgencias + avisa al consultorio |
| Descripción de síntomas, pedido de opinión | Deriva sin opinar |
| Pregunta por medicamentos o dosis | Deriva sin sugerir ninguno |
| Envío o interpretación de estudios | Deriva, pide llevarlos a consulta |
| Pronóstico o promesa de resultados | Deriva al doctor |
| Cualquier adjunto | Deriva sin abrirlo |

> **Pendiente antes de producción:** el Dr. Padilla debe revisar y firmar el
> criterio de `docs/criterio-urgencias.md`. El criterio clínico es suyo, no
> del desarrollador; sus respuestas se traducen directamente a `safety.py` y
> a `escalation.py`, y el documento firmado queda como constancia de quién
> lo definió.

Las pruebas de este módulo son bloqueantes: si una falla, el sistema no sale
a producción.

```bash
pytest tests/test_safety.py -v
```

---

## El panel

Cuatro secciones. Funciona igual en computadora y en celular: es una página
web, se agrega a la pantalla de inicio y no hay nada que instalar.

**Resumen del día** — pendientes, conversaciones, citas, conversión, tiempo
de respuesta, urgencias, serie de 7 días, origen de los pacientes, próximas
citas y motivos de pérdida.

**Conversaciones** — bandeja con filtros, hilo completo, y **toma de
control**: al escribir desde el panel el asistente se pausa solo en esa
conversación. Al costado, la ficha de contacto del paciente con teléfono,
ciudad, cómo llegó, sede y sus citas, más accesos directos para llamar,
abrir el chat en WhatsApp o copiar el número.

**Pacientes** — el directorio de contactos del consultorio, con buscador
por nombre o teléfono.

**Agenda** — todas las citas, la lista de **por cargar en Doctoralia** —la
tarea diaria de la asistente— y el **registro de citas que entraron por
Doctoralia**.

Ese último punto es el que hace que el asistente deje de ser ciego. Hasta
que existió, el sistema solo conocía las citas que él mismo había agendado:
una cita tomada por Doctoralia no existía para él, así que no podía
confirmarla, no le mandaba el recordatorio de 24 horas, y el paciente que
escribía por ella terminaba derivado a una persona. Como la mayoría de las
citas de un consultorio entran por ahí, el recordatorio —lo que más
ausencias evita— cubría a una minoría.

Ahora la asistente la carga en segundos y el asistente la trata como
cualquier otra. Con Google activo, además se escribe en la agenda de
Google: una sola agenda, completa.

No verifica disponibilidad a propósito. No se está pidiendo un lugar: se
está registrando algo que ya ocurrió. Si hay superposición avisa, pero la
decisión es del consultorio.

**Probar el asistente** — el simulador, dentro del panel. Estaba disponible
en `/simulador` pero no había forma de llegar desde la interfaz, así que el
consultorio no lo encontraba.

**Contenido** — precios, direcciones, horarios, franjas reservadas y
respuestas frecuentes. Lo edita el consultorio sin depender del
desarrollador. Los horarios se escriben en lenguaje natural
(«Martes 10:00-12:00») y se validan antes de guardar: un bloque mal cargado
dejaría al asistente sin poder ofrecer turnos, y sería un fallo silencioso.

**Configuración** — modo del asistente, medidor de consumo de IA,
interruptor de sedes, cambio de contraseña y quién tiene acceso.

**Registro de actividad** — quién hizo qué y cuándo. Solo el doctor.

### En el celular

El panel se agrega a la pantalla de inicio y queda con su propio ícono, a
pantalla completa y sin barra de navegador. No hay nada que descargar de
una tienda.

Los avisos de intervención humana salen por **tres canales a la vez**, y es
a propósito:

| Canal | Para qué | Se configura |
|---|---|---|
| Push al celular | El más cómodo: suena en el momento | Desde el panel, en Configuración |
| Telegram | El que no falla | `TELEGRAM_BOT_TOKEN` |
| Correo | Constancia | `SMTP_*` |

El push depende de que el sistema operativo no haya matado la suscripción,
así que **no reemplaza a Telegram**: un aviso perdido es una conversación
que nadie atiende. Si un canal falla, los otros salen igual —
`tests/test_push.py` lo verifica.

Se activa por aparato: el celular de la asistente y el del doctor se
registran por separado, y el panel muestra cuántos hay. Una urgencia queda
en pantalla hasta que alguien la abra; el resto se descarta solo.

> **En iPhone hay un paso previo.** Apple solo permite avisos si la app está
> agregada a la pantalla de inicio (iOS 16.4+). El panel lo detecta y
> explica el paso en lugar de mostrar un botón que no haría nada.

Las claves de envío se generan una sola vez:

```bash
python -m scripts.generar_claves_vapid   # → VAPID_* en el .env
python -m scripts.generar_iconos         # solo si cambian los colores
```

Sin claves configuradas el panel no ofrece la opción y los avisos siguen
saliendo por Telegram y correo. Nada se rompe.

Nada clínico viaja en el aviso: nombre del paciente, motivo administrativo y
el enlace. El aviso pasa por un servicio de terceros; el contenido no.

Sobre los permisos: la asistente ve y responde conversaciones; solo el
doctor cambia el modo, activa sedes y consulta la auditoría. Cada persona
entra con su propio usuario y toda acción que modifica algo queda
registrada con su nombre.

---

## Cuándo se deriva a una persona

Un asistente que deriva de más satura la bandeja, y una bandeja saturada se
deja de mirar — con lo cual se pierden las derivaciones que sí importaban.
Por eso el criterio es explícito:

**Llega a una persona:** posible urgencia, contenido clínico o adjuntos,
pedido de hablar con el doctor, molestia o reclamo, solicitud de
facturación, y la consulta que no se entendió **tras dos intentos**.

**No molesta a nadie:** saludos, precios, horarios, ubicación,
agendamiento, indicaciones. Y el primer mensaje que no se entiende: ahí se
pide una aclaración, no se deriva.

Está cubierto con pruebas en las dos direcciones — `tests/test_escalado.py`
verifica tanto lo que debe escalar como lo que no.

---

## Zona horaria

**Se guarda en UTC. Se muestra en la hora del consultorio.** Guadalajara es
UTC−6 todo el año, sin horario de verano desde 2022.

No es un detalle cosmético: si se mezcla, a un paciente con turno a las
10:30 le llega un recordatorio que dice 16:30, y la rejilla ofrece espacios
de madrugada. Es un error que no se ve en desarrollo, porque el servidor de
pruebas suele estar en UTC, y aparece recién con pacientes reales.

Todo pasa por `app/tiempo.py`. Los horarios de atención («9:00 a 14:00») son
hora local, así que la rejilla de turnos se arma en local y recién ahí se
convierte. Cubierto en `tests/test_tiempo.py`.

---

## Recordatorios

Es lo que más ausencias evita, y lo único donde el sistema le escribe
primero al paciente. Eso implica plantilla aprobada por Meta y costo por
envío, así que las reglas son estrictas:

- 24 horas antes, con la dirección de **su** sede. En un consultorio con
  tres ubicaciones, un recordatorio genérico manda al paciente a la
  dirección equivocada.
- **Nunca dos veces la misma cita.** Ni para citas canceladas, ni para algo
  que ya pasó, ni para algo que ocurre en menos de dos horas.
- Si el envío falla no se marca como enviado: se reintenta en la ronda
  siguiente.

El paciente responde con botones. **Confirmo** deja la cita confirmada.
**Necesito reprogramar** ofrece alternativas — y no libera el cupo hasta que
elija otro, porque cancelar antes es la forma más rápida de dejarlo sin
ninguno.

Las plantillas están redactadas en `docs/plantillas-whatsapp.md`, listas
para enviar a aprobación.

### Tareas programadas

| Tarea | Cada | Qué hace |
|---|---|---|
| Recordatorios | 15 min | Envía los que corresponden |
| Mantenimiento | 1 hora | Cierra citas pasadas y conversaciones abandonadas |
| Retención | 04:30 | Borra historiales vencidos (LFPDPPP) |

Todas se pueden ejecutar dos veces sin causar daño: si el servicio se
reinicia a mitad de una ronda, la siguiente retoma sin duplicar nada.

---

## Fuera del horario de atención

El asistente sigue atendiendo y agendando: un paciente que escribe a las
once de la noche debe poder agendar, o se pierde.

Lo que cambia es lo que **no** se promete. Dentro del horario, ante una
urgencia el asistente dice «ya avisé al equipo para que la contacten».
Fuera de horario **no puede decirlo**, porque a las tres de la madrugada no
hay nadie — y un paciente con signos de alarma que se queda esperando una
llamada que no va a llegar es el peor resultado posible de este sistema.
Ahí el mensaje insiste en acudir de inmediato y sin esperar respuesta.

Cubierto en `tests/test_fuera_horario.py`.

---

## Cómo conversa

El asistente entiende cómo escribe la gente de verdad: sin acentos, con
faltas, en audio transcrito, a medias. «oiga y si me urge hay chance hoy?»
no está en ningún catálogo de respuestas, y es exactamente el mensaje que
llega un martes a las once de la noche.

Además de hablar, **hace**: consulta la disponibilidad real, reserva,
cancela y deriva, con las herramientas de `app/brain/herramientas.py`. El
modelo decide *cuándo*; el código decide *qué pasa*.

Tres garantías, cubiertas en `tests/test_ia.py`:

- **Una alucinación no se convierte en cita.** Si el modelo pide agendar un
  horario que no existe, el proveedor de agenda lo rechaza igual que
  rechazaría a un paciente. No hay camino entre inventar y la agenda del
  doctor.
- **El modelo no escribe en la base.** Pide una acción; el router la aplica.
  Derivar y marcar una conversión los decide el código.
- **Si OpenAI se cae, el paciente recibe respuesta igual.** Contestan los
  flujos y no se entera nadie más que el consultorio.

### Los tres modos

Se cambian desde el panel, sin reprogramar nada.

| Modo | Qué hace | Costo |
|---|---|---|
| `basico` | Solo flujos. Lo que no reconoce, lo deriva. | cero |
| `hibrido` | Los flujos contestan lo previsto; la IA, todo lo demás. | ~80% menos |
| `ia` | IA en todas las respuestas. | mayor |

**Qué define el modo híbrido**, que es de donde sale el ahorro: el saludo,
el precio, la dirección y el horario los contestan los flujos, gratis. La
IA entra cuando (a) no se entendió la intención, o (b) **el paciente ya
había preguntado eso mismo en esta conversación**.

Ese segundo caso importa más de lo que parece. Que alguien vuelva a
preguntar significa que la respuesta fija no le sirvió; repetírsela palabra
por palabra es lo que hace que sienta que habla con una grabación. Ahí
cuesta unas milésimas de dólar y vale cada una.

> **Sin `OPENAI_API_KEY` el sistema queda en modo básico aunque el panel
> diga «híbrido».** Funciona, contesta y agenda — pero repite la misma
> respuesta ante cualquier pregunta que no estuviera prevista. Es lo primero
> que hay que revisar si el consultorio reporta que «siempre contesta lo
> mismo».

**Tope de gasto mensual con caída automática.** Al alcanzar
`IA_LIMITE_MENSUAL_USD`, el sistema pasa solo a modo básico y avisa. Nunca
hay cargos sorpresa. Conviene además fijar el tope del lado de OpenAI: doble
red.

---

## La agenda: franjas reservadas

El 7 de agosto de 2026 Doctoralia confirmó por escrito (caso MX-03213156)
que **no ofrece API, no admite integración externa y no permite exportar ni
sincronizar la agenda**. El asistente no puede ver la disponibilidad real de
ninguna manera.

Eso deja un problema sin solución técnica: agendar a ciegas sobre una agenda
compartida choca tarde o temprano con una cita tomada desde el sitio web,
desde Doctoralia o por la propia asistente.

**La solución es de diseño, no de código.** El consultorio bloquea ciertas
franjas en Doctoralia y las destina solo a WhatsApp:

```
Doctoralia          →  todo el horario MENOS las franjas
Sitio web (widget)  →  todo el horario MENOS las franjas
Asistente WhatsApp  →  únicamente las franjas
```

Dentro de esas franjas este sistema es la única fuente de verdad, así que
**el choque no se detecta: no puede ocurrir**. La cita queda en firme y se le
confirma al paciente en el momento.

Si una sede no tiene franjas configuradas, el asistente no promete ningún
horario: toma el pedido y lo confirma una persona. Prometer a ciegas sería
peor que no prometer nada.

Después, la asistente carga la cita en Doctoralia desde el panel. Mientras
no lo haga, la cita sigue en su lista de pendientes (`/panel/api/por-cargar`)
— es lo que impide que esto se convierta en doble gestión de agendas.

---

## Plan C — Google Calendar: construido y en pausa

Las franjas son la mejor respuesta posible a una plataforma cerrada, pero
siguen dejando un paso manual y limitan al asistente a un pedazo del
horario. Google Calendar sí tiene API, así que el camino de salida está
construido y esperando.

| | Doctoralia (franjas) | Google Calendar |
|---|---|---|
| Ve la disponibilidad real | No | **Sí** |
| Escribe la cita | La copia una persona | **El asistente** |
| Horarios que puede ofrecer | Solo las franjas | **Todo el horario** |
| Lista de «por cargar» | Todos los días | **Vacía** |

Se activa con un interruptor en **Configuración → De dónde sale la agenda**.
No hay que tocar código, no se rehace nada y las citas ya tomadas se
conservan. La marcha atrás está siempre disponible y no depende de que
Google responda.

Antes de dejar activarlo, el panel prueba la conexión sede por sede:
activarla a ciegas dejaría al asistente sin poder agendar en el acto.

Se conecta con una **cuenta de servicio** —un usuario técnico del
consultorio, no una cuenta personal— y lee la disponibilidad con `freeBusy`,
que devuelve solo los rangos ocupados, sin títulos ni invitados. En el
evento se escribe nombre, teléfono, sede y motivo administrativo: nada
clínico, igual que en el resto del sistema.

Configuración paso a paso en **`docs/google-calendar.md`**.

---

## Cuando el paciente busca a otro profesional

Hoy una sola asistente lleva la agenda del Dr. Padilla y la de su esposa
desde el mismo número. Al separarlas, los pacientes que ya tienen este
número guardado van a seguir escribiendo acá para pedirle cita a ella.

Sin nada que lo contemple, esos pacientes quedarían agendados con el médico
equivocado —y se enterarían el día de la consulta.

`app/brain/derivacion.py` lo reconoce y le pasa el número correcto:

> Este número atiende la agenda del Dr. José Guadalupe Padilla.
> Para la Dra. Ana Ramírez la agenda se lleva por otro número: 📱 …

Se administra desde **Contenido → Otros profesionales**: nombre, número y
cómo lo nombran los pacientes («doctora», «su esposa»). El apellido se
reconoce siempre, aunque no se cargue como palabra clave.

Tres decisiones que vale la pena explicar:

- **Es una regla, no una interpretación.** Funciona igual en modo básico,
  sin IA, y mandar mal un número es un error que el paciente paga con un
  viaje perdido.
- **No basta con nombrarla.** «La doctora me recomendó operarme» es un
  mensaje para el Dr. Padilla. Se exige además un contexto de consulta, o
  que la intención ya venga clasificada como cita. Un paciente desviado por
  error es un paciente perdido.
- **No se reenvía nada.** Se le dice a dónde escribir. Pasar mensajes de un
  número a otro sin que el paciente lo sepa es peor que decirle a dónde ir.

Si alguien queda cargado sin número, el asistente no inventa: deriva a una
persona y el panel marca esa ficha como incompleta.

Cubierto en `tests/test_derivacion.py`, en las dos direcciones.

La misma tabla `Profesional` es la que deja el sistema **preparado para
varios médicos**, tal como se acordó: sumar al Dr. B más adelante es agregar
una fila con su agenda de Google, no rehacer el modelo de datos.

---

## Los otros dos proveedores

Se conservan por si la plataforma cambia de política. No se usan hoy.

**Plan A — `AGENDA_PROVEEDOR=api`.** Descartado. El 7 de agosto de 2026
Doctoralia confirmó por escrito (caso MX-03213156) que no cuenta con API
pública ni permite integrar una API externa. El módulo
`app/agenda/doctoralia_api.py` se conserva por si cambian de política, pero
no se usa en esta entrega.

> **Condicionante del plan contratado.** El consultorio está en plan
> **Starter** y pasa a **VIP el 11 de agosto de 2026**. El acceso a la API
> —y en Starter posiblemente también la exportación iCal— depende del plan
> y de una autorización de Docplanner. Hasta el 11 de agosto se trabaja
> contra un calendario local de prueba; ese día se reevalúa qué habilita
> realmente el VIP. Solicitud formal enviada a Docplanner el día 1.

**Plan B — `AGENDA_PROVEEDOR=calendar`.** Activo hoy. Lee el feed iCal de
Doctoralia y mantiene un módulo propio de citas.

> **La limitación del Plan B: los feeds iCal son de solo lectura.** No se
> puede escribir en Doctoralia. Por eso las citas nacen como `SOLICITADA` y
> la asistente las confirma desde el panel. Los turnos del mismo día exigen
> siempre esa confirmación humana, porque el widget del sitio web reserva
> sobre la misma agenda y el feed puede tardar en reflejarlo.

Ambos caminos respetan:

- **Re-verificación al confirmar**, no al ofrecer. Si el hueco se ocupó
  mientras el paciente elegía, se le ofrecen alternativas — nunca un error.
- **Primero la sede, después la fecha.** Ofrecer horarios sin saber a qué
  consultorio va significa ofrecer huecos que en esa dirección no existen.
- **Margen de traslado entre sedes** (`MINUTOS_TRASLADO_ENTRE_SEDES`). El
  doctor no puede estar en dos consultorios a la vez.
- **Sedes con interruptor.** Una sede inactiva no se ofrece. Las citas ya
  agendadas en ella se conservan.

---

## Estructura

```
app/
  config.py            configuración desde el entorno
  models.py            modelo de datos
  db.py                motor y sesiones
  security.py          firma de Meta, claves
  notify.py            avisos por Telegram y correo
  main.py              aplicación FastAPI

  whatsapp/
    webhook.py         endpoints de Meta
    parser.py          normaliza la carga entrante
    client.py          envío: texto, botones, listas, plantillas

  brain/
    safety.py          ← barrera clínica
    intents.py         clasificación por reglas
    escalation.py      cuándo pasa a una persona
    derivacion.py      cuando buscan a otro profesional
    flows.py           respuestas determinísticas
    ai.py              ← la que conversa: OpenAI con tope de gasto
    herramientas.py    lo que la IA puede hacer: agenda, reserva, deriva
    router.py          el circuito completo

  agenda/
    base.py            interfaz común
    franjas.py         ← el que se usa: franjas reservadas
    google_calendar.py Plan C: construido y en pausa
    doctoralia_api.py  descartado (no hay API)
    calendar_sync.py   sin uso (no hay exportación de calendario)
    service.py         lo que usa el resto del sistema

  panel/
    auth.py            sesión por usuario, cookie firmada
    api.py             API del panel
    contenido.py       edición de contenido, agenda y contraseña
    static/panel.html  la interfaz
    static/sw.js       service worker: avisos push y apertura sin señal
    static/manifest.webmanifest   la app instalable
    static/iconos/     el ícono de la pantalla de inicio

  push.py              avisos push al celular (VAPID)
  migraciones.py       columnas nuevas sobre una base que ya tiene datos
  tiempo.py            zona horaria: se guarda UTC, se muestra local
  recordatorios.py     recordatorios y ciclo de vida de la cita
  tareas.py            programador
  seed.py              datos iniciales
  demo.py              conversaciones de ejemplo (solo desarrollo)
  simulador.py         chat de prueba sin Meta (solo desarrollo)
  diagnostico.py       estado de la configuración de Meta vía Graph API
  arranque.py          preparación previa al despliegue

tests/                 392 pruebas
```

---

## Qué se guarda y qué no

**Se guarda:** nombre, teléfono, ciudad, motivo administrativo de consulta,
fuente de referencia, historial de conversaciones, citas y fecha de última
interacción.

**No se guarda:** nada clínico. Ni síntomas, ni diagnósticos, ni estudios,
ni fotografías. Lo que el paciente escriba de esa índole se deriva a una
persona y no se procesa.

Menos datos guardados es menos superficie de riesgo. Es una decisión de
diseño, no un descuido.

Otras medidas: validación de firma en cada mensaje entrante, cifrado en
tránsito y en reposo, registro de auditoría de quién respondió qué, usuario
individual por persona, aviso de consentimiento en el primer contacto
(LFPDPPP) y retención configurable de los historiales.

---

## Qué falta

**El software está completo.** Todo lo que sigue depende de un tercero —
Meta, o el contenido que tiene que dar el consultorio. No hay nada más que
programar para entregar la Fase 1.

**Construido y probado** — 392 pruebas en verde

- [x] Estructura, modelo de datos, webhook con validación de firma
- [x] Barrera clínica, intenciones, escalado, flujos
- [x] Capa de IA con tope de gasto y caída automática a modo básico
- [x] Agenda por franjas reservadas, con margen de traslado entre sedes
- [x] Recordatorio 24 h con botones de confirmar y reprogramar
- [x] Cancelación y reprogramación desde WhatsApp
- [x] Zona horaria del consultorio
- [x] Panel web según la maqueta aprobada, con toma de control y métricas
- [x] Acceso por usuario, permisos por rol y auditoría visible
- [x] App instalable en el celular y avisos push
- [x] Derivación al número de otro profesional
- [x] Google Calendar como agenda propia, construido y en pausa
- [x] Plantillas de recordatorio redactadas

**Depende de Meta** — es el camino crítico

- [ ] Invitación en Meta Business con acceso limitado sobre la cuenta de WhatsApp
- [ ] Constancia de Situación Fiscal, para la verificación del negocio
- [ ] Plantillas enviadas a aprobación (Meta puede tardar 48 h)
- [ ] **Migración del número real** — último paso, en horario de cierre

**Depende del consultorio**

- [ ] Contenido real: precios, horarios, 3 direcciones, convenios
- [ ] Franjas reservadas de cada sede
- [ ] Criterio de urgencias revisado y firmado por el Dr. Padilla
- [ ] Capacitación del personal

**Del lado del servidor, al desplegar en la cuenta del consultorio**

- [ ] `PANEL_SECRETO` y `WA_APP_SECRET` definidos
- [ ] Claves VAPID generadas (`python -m scripts.generar_claves_vapid`)
- [ ] PostgreSQL en lugar de SQLite
- [ ] Google Calendar: opcional, solo si se decide mudar la agenda

---

## Notas de operación

- La ventana de 24 horas: el texto libre solo funciona si el paciente
  escribió en las últimas 24 h. Fuera de eso hay que usar plantilla
  aprobada, y eso sí tiene costo.
- Meta reintenta si el webhook tarda o falla, y el paciente recibe
  respuestas duplicadas. Por eso se responde 200 de inmediato y se procesa
  en segundo plano.
- El sistema se conecta con un **usuario del sistema** de Meta, no con una
  cuenta personal. Al terminar el proyecto nada queda atado al
  desarrollador.
