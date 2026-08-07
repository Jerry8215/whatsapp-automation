# Solicitud de integración a Docplanner / Doctoralia

Lo envía **el Dr. Padilla desde la cuenta con la que administra Doctoralia**,
con copia al desarrollador. Va desde su cuenta a propósito: una solicitud de
integración hecha por un tercero rara vez avanza.

**Enviar a:** soporte de Doctoralia México — desde el panel de la cuenta, o
al correo de soporte que aparezca en ella. Si existe la opción de contactar
al *account manager* asignado, es la vía preferible.

---

## Asunto

Solicitud de acceso a API / integración de agenda — cuenta profesional

## Cuerpo

> Buen día,
>
> Soy el Dr. José Guadalupe Padilla, Cirujano General y Laparoscópico, y
> administro una cuenta profesional en Doctoralia. Actualmente estoy en plan
> **Starter** y a partir del **11 de agosto** tengo contratado el cambio a
> **VIP**.
>
> Estoy implementando un asistente de WhatsApp para mi consultorio y
> necesito que trabaje siempre contra la disponibilidad real de mi agenda de
> Doctoralia, para evitar duplicar turnos o manejar dos agendas en paralelo.
>
> Les agradecería que me confirmen los siguientes puntos:
>
> 1. **Acceso a API.** ¿Ofrecen acceso a la API de agenda para cuentas
>    profesionales? De ser así, ¿qué requisitos, plan y proceso de
>    autorización implica, y cuál es el tiempo estimado?
>
> 2. **Alcance del plan VIP.** ¿El plan VIP que tengo contratado a partir
>    del 11 de agosto incluye alguna capacidad de integración o acceso a API?
>    Si no está incluido, ¿existe un complemento contratable?
>
> 3. **Operaciones disponibles.** En caso de haber acceso: ¿permite
>    consultar disponibilidad, crear, reprogramar y cancelar citas, y
>    bloquear espacios en la agenda?
>
> 4. **Exportación de calendario.** ¿Mi cuenta permite exportar la agenda en
>    formato iCal, o sincronizarla con Google Calendar? ¿Esa función está
>    disponible en el plan Starter, o solo a partir de VIP? En caso
>    afirmativo, ¿con qué frecuencia se actualiza el feed?
>
> 5. **Documentación.** Si corresponde, les agradecería la documentación
>    técnica y el procedimiento para generar credenciales.
>
> Autorizo a mi desarrollador, en copia en este correo, a coordinar los
> aspectos técnicos de la integración.
>
> Quedo atento y agradezco su apoyo.
>
> Dr. José Guadalupe Padilla
> Cirugía General y Laparoscópica

---

## Por qué se pregunta cada cosa

**1 y 2 — acceso a API.** Es el Plan A. Docplanner sí tiene API, pero el
acceso se otorga por convenio y suele reservarse a niveles superiores o a
partners. La pregunta 2 existe porque el cambio a VIP puede habilitarlo, y
conviene saberlo antes del 11 de agosto y no después.

**3 — operaciones.** Un acceso de solo lectura no alcanza para el flujo
completo: sin escritura no se puede reservar ni cancelar desde WhatsApp.
Además, la capacidad de **bloquear espacios** es lo que haría posible, más
adelante, sumar la agenda de un segundo médico.

**4 — iCal.** Es el Plan B, y es la pregunta más urgente de todas: si el
plan Starter no exporta calendario, hasta el 11 de agosto no hay ninguna
forma de leer la agenda real, y el desarrollo tiene que apoyarse en un
calendario de prueba.

**5 — documentación.** Los nombres de endpoints en
`app/agenda/doctoralia_api.py` están puestos según el patrón habitual de la
plataforma y deben confirmarse contra la documentación oficial antes de
activar el Plan A.

---

## Seguimiento

| Fecha | Estado |
|---|---|
| 5 de agosto de 2026 | Solicitud enviada por el Dr. Padilla |
| 7 de agosto de 2026 | **Respuesta: no hay API.** Caso MX-03213156 |
| | Repregunta pendiente sobre exportación de calendario |

## Respuesta de Doctoralia — 7 de agosto de 2026

Caso **MX-03213156**, respondido por Ángeles Lugo (soporte México):

> «Actualmente, Doctoralia no cuenta con una API pública ni es posible
> anclar o integrar una API externa para sincronizar la disponibilidad de la
> agenda con asistentes de WhatsApp u otras herramientas de terceros. Por
> este motivo, no es posible establecer una conexión que consulte la
> disponibilidad de su agenda en tiempo real.»

**El Plan A queda descartado.** `app/agenda/doctoralia_api.py` se conserva
por si la plataforma cambia de política, pero no se va a usar en esta
entrega.

**Lo que NO respondieron:** la pregunta 4, sobre exportación en iCal o
sincronización con Google Calendar. Toda su respuesta habla de API, y la
exportación de calendario no es una API sino una función del producto. Se
repreguntó por separado, evitando la palabra «API» para no recibir la misma
respuesta automática.

De esa repregunta dependen dos escenarios muy distintos:

| Si hay exportación de calendario | Si no la hay |
|---|---|
| El asistente **lee** la disponibilidad real | El asistente no ve la agenda de Doctoralia |
| Nunca ofrece un horario ya ocupado | Hace falta reservar franjas para evitar choques |
| La asistente solo **carga** la cita en Doctoralia | La asistente carga y además vigila colisiones |
