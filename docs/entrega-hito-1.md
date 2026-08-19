# Entrega del Hito 1

Asistente de WhatsApp · Consultorio del Dr. José Guadalupe Padilla

---

## Un cambio en el orden, para confirmar

En el acuerdo original el Hito 1 decía *«número migrado y respondiendo por
la API oficial»*.

Al empezar detecté un problema con ese orden y le propuse cambiarlo: si
migrábamos su número el día 4, quedaba **sin la aplicación de WhatsApp
Business y sin el panel todavía terminado** durante unos diez días. Sus
asistentes no habrían podido responderle a nadie en ese lapso.

Por eso el nuevo orden es:

| Días | Qué pasa | Su número |
|---|---|---|
| 1–9 | Se construye y prueba todo con el **número de prueba** que ofrece Meta | Sigue funcionando normal en el celular |
| 10–13 | Panel terminado y capacitación del personal | Sigue funcionando normal |
| **14** | **Migración del número real**, en horario de cierre | Cambia, con todo listo y el equipo capacitado |

**Los montos y el plazo total no cambian.** Siguen siendo tres hitos de USD
60, 80 y 60 en 14 días. Solo cambia en qué momento se toca su número.

**Le pido que me confirme este orden por escrito**, así quedamos los dos con
la misma expectativa.

---

## Qué se entrega en este hito

Lo que sigue está construido, probado y funcionando.

### Cómo comprobarlo usted mismo

**1. Escríbale al asistente desde su celular.** Le paso el número de prueba
y registro el suyo como autorizado. Pruebe:

- «Hola, buenos días» → le responde y se presenta
- «¿Cuánto cuesta la consulta?» → le da el precio
- «¿Dónde están ubicados?» → le da las sedes activas
- «Quiero agendar una cita» → le pregunta la sede y después le ofrece horarios
- **«Tengo un dolor muy fuerte y fiebre»** → lo manda a urgencias y marca la
  conversación como urgente
- **«¿Es normal que la herida se vea rosada?»** → se niega a opinar y deriva

**2. Entre al panel** con el usuario que le paso, desde la computadora o
desde el celular. Va a ver sus propias conversaciones de prueba en tiempo
real, con la ficha de contacto y el motivo por el que se derivó cada una.

### Lo construido

**Conversación**
- Responde 24/7, en menos de 5 segundos. Ningún mensaje queda sin respuesta.
- Conversación natural, sin menús numerados.
- Clasifica automáticamente: cita, costos, postoperatorio, urgencia,
  ubicación, información general, facturación, referencia médica, cancelación.
- Reconoce al paciente que ya escribió antes.

**Barrera clínica** — la parte más delicada
- Detecta signos de alarma y manda a urgencias, sin dar diagnóstico.
- Nunca recomienda medicamentos, interpreta estudios ni promete resultados.
- **Nunca tranquiliza sobre un síntoma.** Ante la duda, deriva.
- Las fotografías y estudios no se abren ni se guardan: se derivan.
- Verificado con 69 pruebas automáticas.

**Escalado a una persona**
- Deriva por: urgencia, contenido clínico, pedido de hablar con usted,
  molestia, facturación, o consulta no entendida tras dos intentos.
- Lo rutinario lo resuelve solo, sin molestar a nadie.
- Aviso inmediato por Telegram, correo o notificación.

**Panel de control**
- Resumen del día con métricas reales.
- Bandeja de conversaciones, con toma de control desde el mismo panel.
- Ficha de contacto de cada paciente y directorio con buscador.
- Configuración: modo del asistente, medidor de gasto de IA, sedes.
- Usuario individual por persona y registro de quién hizo qué.
- **Se instala en el celular**: se agrega a la pantalla de inicio y queda
  con su propio ícono, a pantalla completa. Nada que bajar de una tienda.
- **Avisos con sonido** cuando una conversación requiere atención, por
  push al celular, por Telegram y por correo. Se activan por aparato desde
  el mismo panel, y hay un botón para probarlos: nadie debería descubrir
  que no llegaban el día que llega una urgencia real.

**Agenda**
- Sistema de franjas reservadas (ver más abajo).
- Respeta el tiempo de traslado entre sus sedes.
- Recordatorio 24 h antes con la dirección de la sede correcta, y botones
  para confirmar o reprogramar.
- **Google Calendar, construido y en pausa**, como acordamos. El día que
  decida dejar Doctoralia, lo activa con un interruptor del panel: ahí el
  asistente pasa a ver su disponibilidad real y a escribir la cita él mismo,
  sin lista de pendientes. Se puede volver atrás cuando quiera.

**Si alguien más atiende por otro número**
- Cuando un paciente escriba a este número pidiendo cita con otra
  profesional, el asistente lo reconoce y le pasa el número correcto, en
  lugar de agendarle con usted por error.
- Lo carga usted desde el panel: nombre, número y cómo la nombran los
  pacientes. Sin depender de mí.
- La estructura queda además preparada para sumar un segundo médico con su
  propia agenda más adelante, tal como habíamos hablado.

**Seguridad**
- Validación criptográfica de cada mensaje entrante.
- Cifrado en tránsito y en reposo, respaldos diarios.
- Aviso de consentimiento al primer contacto (LFPDPPP).
- Ningún dato clínico se almacena.

**392 pruebas automáticas**, todas en verde.

---

## Lo que cambió respecto de lo previsto: la agenda

Doctoralia confirmó por escrito (caso **MX-03213156**, 7 de agosto de 2026)
que **no ofrece API, no admite integración externa y no permite exportar ni
sincronizar la agenda**. Es una limitación de su plataforma, no del plan
contratado.

Era uno de los dos escenarios que le planteé antes de empezar, y por eso el
sistema estaba construido para ambos.

**La solución implementada: franjas reservadas.** Usted bloquea ciertos
horarios en Doctoralia y los destina solo a WhatsApp.

```
Doctoralia y su sitio web  →  todo su horario MENOS las franjas
Asistente de WhatsApp      →  únicamente las franjas
```

Cada canal trabaja sobre horarios distintos, así que **el choque de citas no
es que se detecte: no puede ocurrir**. Es imposible por diseño.

Al paciente se le confirma la cita en el momento. Su asistente después la
carga en Doctoralia desde una lista de pendientes del panel, que muestra
todo lo necesario. Son segundos por cita, y solo por las de WhatsApp.

**Lo que necesito de usted:** qué franjas destinar en cada sede. Mi
recomendación es empezar con poco —dos franjas de dos horas por semana— y
ampliarlas cuando vea el volumen real.

---

## Lo que sigue, y qué necesito

| Necesito | Para qué | Estado |
|---|---|---|
| Invitación en Meta Business | Migrar su número y enviar las plantillas a aprobación | Pendiente |
| Constancia de Situación Fiscal | Verificación del negocio ante Meta | Pendiente |
| Contenido del consultorio | Precios, horarios, 3 direcciones, convenios, indicaciones | Pendiente |
| Criterio de urgencias firmado | Que la barrera clínica sea suya y no mía | Enviado, pendiente |
| Franjas por sede | Que el asistente pueda agendar en firme | Pendiente |

Las plantillas de recordatorio ya están redactadas y se envían a aprobación
de Meta el mismo día que tenga acceso. Meta puede tardar hasta 48 horas, así
que es lo primero que hago.

---

## Solicitud de liberación

Con lo anterior comprobado, le pido la liberación del **Hito 1 · USD 60**.

Sigo con el Hito 2 mientras llegan los pendientes de arriba.
