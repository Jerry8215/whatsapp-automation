# Manual del panel

Asistente de WhatsApp · Consultorio del Dr. José Guadalupe Padilla

Está escrito para el uso diario. Lo importante está en las dos primeras
páginas; el resto se consulta cuando haga falta.

---

## Lo mínimo que hay que saber

**Entrar:** [dirección del panel] · con su correo y contraseña.
Funciona igual en computadora y en celular.

**En el celular**, ábralo en el navegador y use «Agregar a pantalla de
inicio». Queda como cualquier otra aplicación.

**Cada persona entra con su propio usuario.** No se comparten contraseñas:
el panel registra quién respondió cada conversación.

### Lo único que hay que revisar todos los días

La sección **Conversaciones**, pestaña **Requieren atención**. Ahí está lo
que el asistente no resolvió y necesita a una persona. Si esa bandeja está
vacía, no hay nada pendiente.

---

## Resumen del día

Lo primero que aparece al entrar.

| Indicador | Qué significa |
|---|---|
| **Requieren atención** | Pacientes esperando a una persona. Si no es cero, empiece por ahí. |
| Conversaciones | Cuántos pacientes escribieron hoy |
| Citas agendadas | Cuántas se agendaron hoy |
| Conversión | De cada 100 que escriben, cuántos terminan agendando |
| Respuesta promedio | Cuánto tarda el asistente en contestar |
| Urgencias detectadas | Cuántos casos se derivaron a urgencias hoy |

Más abajo: cómo llegaron los pacientes (Google, Doctoralia, recomendación),
las próximas citas y los motivos por los que se perdieron pacientes.

---

## Conversaciones

### Las pestañas

- **Requieren atención** — esperan a una persona. Es la que importa.
- **En atención** — alguien del consultorio ya las tomó.
- **Asistente** — las está llevando el asistente, no hay que hacer nada.
- **Todas**

### Por qué el asistente deriva una conversación

| Etiqueta | Qué pasó |
|---|---|
| 🔴 **Posible urgencia** | El paciente describió signos de alarma. **Atender primero.** |
| 🔴 **Contenido clínico** | Describió síntomas, mandó una foto o pidió una opinión médica |
| 🟡 Pidió al doctor | Quiere hablar directamente con el Dr. Padilla |
| 🟡 Paciente molesto | Se detectó un reclamo |
| 🟡 No comprendido | El asistente no entendió después de dos intentos |
| Facturación | Pidió una factura |

### Responder a un paciente

1. Abra la conversación. Arriba está todo lo que el asistente ya conversó,
   así no hay que preguntar dos veces.
2. Escriba en el cuadro de abajo y envíe.
3. **Al escribir, usted toma el control automáticamente** y el asistente se
   detiene en esa conversación. No va a contradecirla.
4. Cuando termine, pulse **Devolver al asistente** para que siga
   atendiendo, o **Marcar resuelta** para cerrarla.

> Si el paciente lleva más de 24 horas sin escribir, WhatsApp no permite
> mandarle texto libre. El panel avisa cuando pasa. En ese caso hay que
> llamarlo por teléfono.

### La ficha del paciente

A la derecha: teléfono, ciudad, cómo llegó al consultorio y sus citas
previas. Con botones para llamar, abrir el chat en WhatsApp o copiar el
número.

---

## Agenda

### Por cargar en Doctoralia

**Es la tarea diaria de la asistente.**

Doctoralia no permite conectarse con otros sistemas, así que las citas que
entran por WhatsApp se pasan a mano. La lista muestra paciente, teléfono,
fecha y sede.

Al cargar una en Doctoralia, pulse **Ya la cargué** y desaparece de la
lista. Mientras algo siga ahí, sigue a la vista — así ninguna se pierde.

> Conviene revisarla dos veces al día: al abrir y antes de cerrar.

### Todas las citas

El listado completo, con su estado:

| Estado | Significa |
|---|---|
| **Agendada** | El asistente la reservó. Falta cargarla en Doctoralia. |
| **Confirmada** | El paciente confirmó al recibir el recordatorio |
| **Solicitada** | El paciente la pidió, falta que ustedes la confirmen |
| **Cancelada** | Se canceló. **Retirarla también de Doctoralia.** |

---

## Pacientes

El directorio de contactos, con buscador por nombre o teléfono. De cada uno:
teléfono, ciudad, cómo llegó, sede habitual, cuántas citas tuvo y cuándo fue
la última vez.

**Ver chat** abre su conversación.

---

## Contenido *(solo el doctor)*

Aquí se cambia lo que el asistente le dice a los pacientes. **No hace falta
pedirle nada al desarrollador.**

De cada sede: dirección, referencias para llegar, precio de la valoración,
convenios, horario de atención y franjas reservadas.

### Cómo se escriben los horarios

Una línea por bloque:

```
Lunes 09:00-14:00
Miércoles 09:00-14:00
Viernes 09:00-14:00
```

Si algo está mal escrito, el panel avisa y **no lo guarda**. Es a propósito:
un horario mal cargado dejaría al asistente sin poder ofrecer turnos.

### Las franjas reservadas

Son los horarios que usted bloquea en Doctoralia y destina solo a WhatsApp.

```
Martes 10:00-12:00
Jueves 10:00-12:00
```

**El asistente solo puede agendar dentro de esas franjas.** Como ningún otro
canal las toca, es imposible que se duplique una cita.

> Si una sede no tiene franjas, el asistente no promete horarios: toma el
> pedido y ustedes lo confirman.

### Respuestas frecuentes

Las preguntas que más les hacen, con la respuesta que debe dar el asistente.
Se agregan, editan y borran desde aquí.

---

## Configuración

### Modo del asistente

| Modo | Qué hace | Costo |
|---|---|---|
| **Básico** | Solo respuestas programadas | Sin costo |
| **Híbrido** | Las comunes sin costo; la inteligencia artificial solo para lo no previsto | Bajo |
| **IA completa** | Conversación natural siempre | Mayor |

**Recomendado: Híbrido.**

Debajo, el consumo del mes y su límite. Al alcanzarlo, el asistente pasa
solo a modo básico y les avisa. **Nunca hay cargos sorpresa.**

### Sedes

El interruptor de cada una. Una sede desactivada no se le ofrece a nadie.
Las citas ya agendadas ahí se conservan, y sus recordatorios siguen saliendo
con la dirección correcta.

### Cambiar la contraseña

**Háganlo la primera vez que entren.** Las contraseñas iniciales son
provisionales.

---

## Preguntas frecuentes del personal

**¿Tengo que estar mirando el panel todo el día?**
No. Cuando algo necesita a una persona llega un aviso al celular, por
Telegram o por correo, según lo configurado.

**Le respondí a un paciente y el asistente le escribió después. ¿Por qué?**
No debería pasar: al escribir desde el panel el asistente se detiene. Si
ocurrió, avísele al desarrollador — es un error.

**El paciente mandó una foto de su herida. ¿La abro?**
El asistente no la abre ni la guarda, y deriva la conversación. La foto está
en el WhatsApp del consultorio. Quien la valora es el doctor.

**¿Puede el asistente decirle a un paciente qué tomar, o si algo es grave?**
No, nunca. Está programado para negarse y derivar. Si un paciente insiste,
la conversación llega a ustedes.

**Un paciente dice que le llegó el recordatorio con la dirección
equivocada.** Revise en **Contenido** que la dirección de esa sede sea
correcta. El recordatorio usa lo que esté cargado ahí.

**Me equivoqué y cancelé una cita.** El horario vuelve a quedar libre.
Vuelva a agendarla desde Doctoralia y avísele al paciente.

**Se cerró la sesión sola.** Pasa por seguridad tras un rato de
inactividad. Vuelva a entrar.

---

## Qué hacer ante una urgencia

Cuando aparece **🔴 Posible urgencia**:

1. **Ábrala de inmediato.** Está siempre arriba de todo.
2. El asistente ya le indicó al paciente acudir a urgencias. No hay que
   repetírselo, pero conviene confirmarlo.
3. Avise al Dr. Padilla según lo que él haya definido.
4. Anote en la conversación lo que se hizo, para que quede registro.

> El asistente **nunca** le dice a un paciente que su síntoma no es grave.
> Ante la duda, deriva. Es preferible que derive de más.

---

## Si algo no funciona

**El panel no abre.** Pruebe otro navegador o el celular. Si tampoco,
avísele al desarrollador: puede ser el servidor.

**El asistente no responde a los pacientes.** Escríbale usted desde su
propio WhatsApp. Si tampoco le responde, avise de inmediato.

**No llegan los avisos.** Revise las notificaciones del navegador y de
Telegram en el celular.

Ante cualquier duda, escriba. Vale más preguntar que suponer.
