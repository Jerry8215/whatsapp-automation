# Plantillas de mensaje para aprobación de Meta

Estas son las únicas formas de escribirle a un paciente **fuera de la
ventana de 24 horas**. Dentro de esa ventana —es decir, cuando el paciente
escribió recientemente— se responde con texto libre y sin costo.

**Enviar a aprobación el mismo día que se tenga acceso a WhatsApp Manager.**
Meta suele tardar entre unos minutos y 48 horas, pero un rechazo obliga a
corregir y reenviar, así que conviene no dejarlo para el final.

Categoría: **UTILITY** en todos los casos. Son mensajes transaccionales
sobre una cita que el propio paciente solicitó, no promociones. Marcarlas
como MARKETING encarecería el envío y aumentaría el riesgo de que el
paciente las reporte.

Idioma: **es_MX**.

---

## 1. `recordatorio_cita`

Se envía 24 horas antes. Es el mensaje que más ausencias evita.

**Cuerpo**

```
Hola {{1}}, le recordamos su cita con el Dr. José Guadalupe Padilla.

📅 {{2}}
📍 {{3}}
{{4}}

Le pedimos llegar 10 minutos antes.
```

| Variable | Contenido | Ejemplo |
|---|---|---|
| `{{1}}` | Nombre del paciente | Ana López |
| `{{2}}` | Fecha y hora legibles | jueves 7 de agosto, 10:30 |
| `{{3}}` | Nombre de la sede | Torre Médica Providencia |
| `{{4}}` | Dirección completa | Av. Pablo Neruda 3265, Providencia |

**Botones de respuesta rápida**

| Texto | Identificador |
|---|---|
| Confirmo mi cita | `confirmar_cita` |
| Necesito reprogramar | `reprogramar_cita` |

> La dirección va como variable y no fija en la plantilla, porque el
> consultorio tiene tres sedes. Un recordatorio con la dirección equivocada
> es la causa más frecuente de ausencia en consultorios con varias
> ubicaciones.

---

## 2. `confirmacion_cita`

Se envía al agendar, cuando el paciente ya salió de la ventana de 24 horas
(por ejemplo, si la cita la cargó la asistente desde el panel).

**Cuerpo**

```
Hola {{1}}, su cita quedó agendada.

📅 {{2}}
📍 {{3}}
{{4}}

Un día antes le enviamos un recordatorio. Si necesita cambiarla, responda a este mensaje.
```

Mismas variables que la anterior. Sin botones.

---

## 3. `cita_reprogramada`

**Cuerpo**

```
Hola {{1}}, su cita fue reprogramada.

Nueva fecha: {{2}}
📍 {{3}}

Si esta fecha no le acomoda, responda a este mensaje y buscamos otra.
```

| Variable | Contenido |
|---|---|
| `{{1}}` | Nombre del paciente |
| `{{2}}` | Nueva fecha y hora |
| `{{3}}` | Sede |

---

## 4. `seguimiento_postoperatorio`

Se envía a los días de una cirugía. **Solo pregunta si necesita algo; no
pregunta por síntomas ni pide fotografías.** Si el paciente responde con
algo clínico, la barrera de `app/brain/safety.py` lo deriva al equipo.

**Cuerpo**

```
Hola {{1}}, le escribimos del consultorio del Dr. Padilla para saber cómo ha seguido.

Si necesita algo o quiere adelantar su cita de control, responda a este mensaje y lo atendemos.

Ante cualquier molestia importante, acuda a urgencias sin esperar.
```

| Variable | Contenido |
|---|---|
| `{{1}}` | Nombre del paciente |

---

## Antes de enviarlas a aprobación

- **Nada de contenido clínico.** Ninguna plantilla pregunta por síntomas ni
  ofrece orientación médica. Meta rechaza contenido sensible de salud, y
  además va en contra de cómo está diseñado el sistema.
- **Sin lenguaje promocional.** Ni descuentos, ni «aproveche», ni
  «promoción». Eso reclasificaría la plantilla como MARKETING.
- **Que el nombre del negocio esté verificado** antes de enviar. Con la
  verificación pendiente los rechazos son más probables.
- **Revisar la redacción con el Dr. Padilla.** Es su voz la que va a leer el
  paciente.

## Si Meta rechaza alguna

Los motivos habituales son: variable al inicio o al final del cuerpo sin
texto alrededor, dos variables seguidas, o categoría mal elegida. Se corrige
y se reenvía; no hay penalización por reintentar.

## Estado

| Plantilla | Enviada | Aprobada |
|---|---|---|
| `recordatorio_cita` | ⏳ | |
| `confirmacion_cita` | ⏳ | |
| `cita_reprogramada` | ⏳ | |
| `seguimiento_postoperatorio` | ⏳ | |
