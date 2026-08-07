# Asistente de WhatsApp — Consultorio Dr. José Guadalupe Padilla

Cirugía General y Laparoscópica · Guadalajara

Asistente que atiende WhatsApp 24/7: conversa con naturalidad, agenda en la
agenda real del consultorio, envía recordatorios y pasa la conversación a
una persona cuando hace falta criterio humano.

---

## Estado

**Fase 1 · Hito 1 — en curso.** Circuito completo de mensaje entrante a
respuesta enviada, funcionando contra el número de prueba de Meta.

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
| **Zona horaria del consultorio** | ✅ funcionando |
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
   ├─ 6.  Flujos  (flows.py)                    resuelto sin costo
   ├─ 7.  IA  (ai.py)                           solo si el modo lo permite
   └─ 8.  Si nada resolvió                      → derivar a una persona
```

**El invariante del sistema:** la IA nunca ve un mensaje que la barrera
clínica bloqueó.

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

**Configuración** — modo del asistente, medidor de consumo de IA,
interruptor de sedes, estado de la agenda y quién tiene acceso.

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

## Los tres modos

Se cambian desde el panel, sin reprogramar nada.

| Modo | Qué hace | Costo |
|---|---|---|
| `basico` | Solo flujos. Lo que no reconoce, lo deriva. | cero |
| `hibrido` | Flujos para lo común; la IA solo entra en lo no previsto. | ~80% menos |
| `ia` | IA en todas las respuestas. | mayor |

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
    flows.py           respuestas determinísticas
    ai.py              OpenAI con tope de gasto
    router.py          el circuito completo

  agenda/
    base.py            interfaz común
    franjas.py         ← el que se usa: franjas reservadas
    doctoralia_api.py  descartado (no hay API)
    calendar_sync.py   sin uso (no hay exportación de calendario)
    service.py         lo que usa el resto del sistema

  panel/
    auth.py            sesión por usuario, cookie firmada
    api.py             API del panel
    static/panel.html  la interfaz

  tiempo.py            zona horaria: se guarda UTC, se muestra local
  recordatorios.py     recordatorios y ciclo de vida de la cita
  tareas.py            programador
  seed.py              datos iniciales
  demo.py              conversaciones de ejemplo (solo desarrollo)
  simulador.py         chat de prueba sin Meta (solo desarrollo)
  diagnostico.py       estado de la configuración de Meta vía Graph API
  arranque.py          preparación previa al despliegue

tests/                 178 pruebas
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

## Pendientes por hito

**Hito 1 · días 1–4**
- [x] Estructura, modelo de datos, webhook con validación de firma
- [x] Barrera clínica, intenciones, escalado, flujos
- [x] Capa de IA con tope de gasto
- [x] Agenda Plan B
- [ ] Solicitud de acceso a la API ante Docplanner — **enviar el día 1**
- [ ] App de Meta y número de prueba
- [ ] Servidor desplegado en cuenta del consultorio
- [ ] Plantillas de recordatorio enviadas a aprobación de Meta

**Hito 2 · días 5–9**
- [x] Recordatorio 24 h con botones de confirmar y reprogramar
- [x] Cancelación y reprogramación desde WhatsApp
- [x] Plantillas de Meta redactadas
- [x] Zona horaria del consultorio
- [ ] Contenido real del consultorio (precios, horarios, 3 direcciones, convenios)
- [ ] Criterio de urgencias revisado y firmado por el Dr. Padilla
- [ ] Plantillas enviadas a aprobación de Meta

**Hito 3 · días 10–14**
- [x] Panel web, según la maqueta aprobada
- [x] Toma de control y bandeja de pendientes
- [x] Métricas y ficha de contacto del paciente
- [x] Acceso por usuario, permisos por rol y auditoría
- [ ] Auditoría visible en pantalla
- [ ] Capacitación del personal
- [ ] **Migración del número real** — último paso, en horario de cierre

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
