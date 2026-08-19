# Conectar Google Calendar

Guía de configuración del **Plan C**: la agenda propia del consultorio, con
lectura y escritura reales.

Queda construido y en pausa. El asistente sigue trabajando con las franjas
de Doctoralia hasta que el consultorio decida mudarse; ese día se cambia un
interruptor en el panel y nada más.

---

## Por qué existe

Doctoralia confirmó por escrito (caso MX-03213156, 7 de agosto de 2026) que
no ofrece API, no admite integración externa y no permite exportar ni
sincronizar la agenda. Con esa limitación, lo máximo que puede hacer el
asistente es agendar dentro de franjas reservadas y dejarle a la asistente
la tarea de copiar cada cita.

Con Google Calendar eso desaparece:

| | Doctoralia (franjas) | Google Calendar |
|---|---|---|
| Ve la disponibilidad real | No | **Sí** |
| Escribe la cita | La copia una persona | **El asistente** |
| Horarios que puede ofrecer | Solo las franjas reservadas | **Todo el horario de atención** |
| Lista de «por cargar» | Sí, todos los días | **Vacía** |

---

## Qué hace falta

Una cuenta de Google del consultorio y unos quince minutos, una sola vez.

### 1. Crear la cuenta de servicio

Es un «usuario técnico» que pertenece al consultorio, no a una persona. Si
mañana cambia el desarrollador, esto sigue funcionando igual.

1. Entrar a <https://console.cloud.google.com/> con la cuenta del consultorio.
2. Crear un proyecto — por ejemplo `asistente-consultorio`.
3. En **APIs y servicios → Biblioteca**, buscar *Google Calendar API* y
   habilitarla.
4. En **APIs y servicios → Credenciales → Crear credenciales → Cuenta de
   servicio**. Nombre: `asistente-whatsapp`. Sin roles: no los necesita.
5. Abrir la cuenta recién creada → pestaña **Claves** → **Agregar clave →
   Crear clave nueva → JSON**. Se descarga un archivo.

Ese archivo es una credencial. No se sube al repositorio ni se manda por
WhatsApp.

### 2. Compartir la agenda

En Google Calendar, en la agenda del consultorio: **Configuración → Compartir
con determinadas personas → Agregar**.

- Correo: el `client_email` que aparece dentro del JSON. Termina en
  `@…iam.gserviceaccount.com`.
- Permiso: **Hacer cambios en los eventos**.

Sin este paso Google responde 404 y parece que la agenda no existe. Es el
error más común.

### 3. Cargar las credenciales en el servidor

```bash
GOOGLE_CUENTA_SERVICIO_JSON={"type":"service_account", ...}   # el JSON completo
GOOGLE_CALENDARIO_ID=consultorio@gmail.com
```

`GOOGLE_CALENDARIO_ID` es el identificador de la agenda: está en
**Configuración de la agenda → Integrar agenda → ID de agenda**. Para la
agenda principal de una cuenta es el propio correo.

En una máquina local se puede poner la ruta al archivo en vez del JSON.

### 4. Comprobarlo antes de mudarse

En el panel: **Configuración → De dónde sale la agenda → Probar la conexión
con Google**.

Revisa cada sede activa e informa cuál está lista y cuál no. Hay que hacerlo
**antes** de cambiar el interruptor: activar la agenda a ciegas dejaría al
asistente sin poder agendar en el acto, y el consultorio se enteraría con un
paciente esperando. El panel tampoco deja activarlo si la prueba falla.

---

## Varias sedes

Lo normal es una sola agenda para las tres: es un solo doctor y no puede
estar en dos consultorios a la vez. En ese caso alcanza con
`GOOGLE_CALENDARIO_ID` y no hay que tocar nada más.

Si alguna sede lleva agenda aparte, se le carga la suya en **Contenido →
(la sede) → Agenda de Google**. El margen de traslado entre sedes
(`MINUTOS_TRASLADO_ENTRE_SEDES`) se respeta igual en los dos casos.

---

## Mudarse, y volver

**Mudarse:** Configuración → De dónde sale la agenda → *Google Calendar*.
Las citas ya tomadas se conservan; las que estaban pendientes de cargar en
Doctoralia siguen en la lista hasta que alguien las marque. De ahí en
adelante no se agrega ninguna.

**Volver:** el mismo interruptor, en sentido contrario, y siempre disponible
—no depende de que Google responda—. Si algo sale mal, el consultorio puede
volver al camino conocido sin llamar a nadie.

---

## Qué se guarda en el evento

Nombre del paciente, teléfono, sede y el motivo administrativo. **Nada
clínico**: ni síntomas, ni diagnósticos, ni estudios. Es la misma regla que
rige el resto del sistema, y acá pesa más porque la agenda de Google puede
estar compartida con otras personas del consultorio.

Para leer la disponibilidad se usa `freeBusy`, que devuelve solo los rangos
ocupados —sin títulos ni invitados—. El asistente no necesita saber de qué
es cada cita del doctor, así que no lo pregunta.
