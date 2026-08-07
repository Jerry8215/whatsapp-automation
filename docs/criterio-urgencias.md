# Criterio de urgencias — para revisión y firma del Dr. Padilla

**Por qué esto lo define usted y no yo.**

El asistente está programado para detectar signos de alarma y, cuando los
encuentra, deja de responder por su cuenta: le indica al paciente que acuda
a urgencias y les avisa a ustedes de inmediato. Nunca da un diagnóstico ni
tranquiliza a nadie.

La lista de qué cuenta como signo de alarma es una decisión clínica, no
técnica. Yo armé una propuesta con criterio de cirugía general —abdomen
agudo y postoperatorio complicado— pero **necesito que usted la revise y la
apruebe** antes de que el sistema atienda a un paciente real.

Es la única parte del proyecto donde un error no es un problema comercial.

**Cómo responder:** marque cada punto y agregue lo que falte. Si prefiere,
grábeme un audio recorriendo la lista; con eso me alcanza.

---

## Parte A · Signos de alarma → «acuda a urgencias»

Cuando el paciente escribe algo de esta lista, el asistente responde:

> «Por lo que me describe es importante que la valoren hoy mismo de forma
> presencial. Le pido que acuda al servicio de urgencias más cercano sin
> esperar. Ya avisé al equipo del Dr. Padilla para que la contacten. Si el
> malestar aumenta, no espere la llamada y acuda de inmediato.»

Y les llega el aviso marcado como urgente.

### A1 · Abdominal

| | Signo | ¿Correcto? |
|---|---|---|
| 1 | Dolor «muy fuerte», «intenso» o «insoportable» | ☐ Sí ☐ No |
| 2 | «No aguanto el dolor» / «me duele muchísimo» | ☐ Sí ☐ No |
| 3 | Dolor que no cede ni se calma | ☐ Sí ☐ No |
| 4 | Abdomen duro, rígido o muy distendido | ☐ Sí ☐ No |
| 5 | No puede pasar gases ni evacuar | ☐ Sí ☐ No |

### A2 · Sistémicos

| | Signo | ¿Correcto? |
|---|---|---|
| 6 | Fiebre alta (39 °C o más) | ☐ Sí ☐ No |
| 7 | Escalofríos | ☐ Sí ☐ No |
| 8 | Desmayo o sensación de desmayo | ☐ Sí ☐ No |
| 9 | Dificultad para respirar o falta de aire | ☐ Sí ☐ No |
| 10 | Dolor en el pecho | ☐ Sí ☐ No |

> **A definir:** ¿a partir de qué temperatura quiere que se considere alarma?
> Hoy está en **39 °C**. ☐ 38 ☐ 38.5 ☐ 39 ☐ Otra: ______

### A3 · Sangrado

| | Signo | ¿Correcto? |
|---|---|---|
| 11 | Sangrado abundante o que no se detiene | ☐ Sí ☐ No |
| 12 | Sangre en vómito, heces u orina | ☐ Sí ☐ No |
| 13 | Vómito persistente («llevo días vomitando», «vomito todo») | ☐ Sí ☐ No |

### A4 · Ictericia

| | Signo | ¿Correcto? |
|---|---|---|
| 14 | Piel u ojos amarillos | ☐ Sí ☐ No |

### A5 · Herida quirúrgica

| | Signo | ¿Correcto? |
|---|---|---|
| 15 | La herida se abrió | ☐ Sí ☐ No |
| 16 | Sale pus o líquido por la herida | ☐ Sí ☐ No |
| 17 | Herida muy roja, caliente o con mal olor | ☐ Sí ☐ No |
| 18 | Se zafó un punto o una grapa | ☐ Sí ☐ No |

### A6 · ¿Falta algo?

Signos que usted agregaría, sobre todo los propios de sus procedimientos más
frecuentes:

```
19. ______________________________________________

20. ______________________________________________

21. ______________________________________________
```

---

## Parte B · Cuándo quiere que lo contacten a usted

Distinto de «acuda a urgencias»: son los casos donde su asistente debe
buscarlo a usted directamente.

| | Caso | ¿Lo contactamos? |
|---|---|---|
| 1 | Cualquier signo de alarma de la Parte A | ☐ Siempre ☐ Solo en horario ☐ Solo la asistente |
| 2 | Paciente postoperado suyo con cualquier molestia | ☐ Sí ☐ No |
| 3 | Paciente que pide hablar con usted por nombre | ☐ Sí ☐ No |
| 4 | Consulta de un colega o referencia médica | ☐ Sí ☐ No |
| 5 | Paciente molesto o con un reclamo | ☐ Sí ☐ No |
| 6 | Alguien preguntando por una cirugía ya programada | ☐ Sí ☐ No |

**¿Por qué vía prefiere el aviso urgente?**
☐ WhatsApp a su número personal ☐ Telegram ☐ Llamada ☐ Solo el panel

**¿En qué horario acepta que lo contacten?**
```
Días y horas: ___________________________________

Fuera de eso: ☐ igual avísenme si es urgencia ☐ que espere a la mañana
```

---

## Parte C · Fuera del horario de atención

Cuando el consultorio está cerrado y el mensaje **no** parece urgencia, hoy
el asistente responde y agenda normalmente para el siguiente día hábil.

¿Le parece bien? ☐ Sí ☐ No, prefiero que: ______________________

Cuando **sí** parece urgencia fuera de horario, hoy responde:

> «En este momento el consultorio está cerrado, pero ya dejé su mensaje
> marcado como prioritario y la contactan en cuanto abran. Si se trata de
> algo que no puede esperar, acuda al servicio de urgencias más cercano.»

¿Le parece bien? ☐ Sí ☐ No, prefiero que diga: ______________________

**¿Quiere dar un número de urgencias del consultorio?**
☐ No ☐ Sí: ______________________
Si es que sí: ☐ a todos los pacientes ☐ solo a sus postoperados

**¿Hay algún hospital al que prefiera derivar?**
```
______________________________________________
```

---

## Parte D · Lo que el asistente nunca hace

Esto ya está programado. Confírmeme que está de acuerdo, o agregue lo que
falte.

| | Nunca | ¿De acuerdo? |
|---|---|---|
| 1 | Emitir diagnósticos ni sugerir qué puede tener | ☐ Sí ☐ No |
| 2 | Recomendar medicamentos, dosis o tratamientos | ☐ Sí ☐ No |
| 3 | Interpretar estudios, análisis o imágenes | ☐ Sí ☐ No |
| 4 | Prometer resultados o dar pronósticos de recuperación | ☐ Sí ☐ No |
| 5 | Negociar honorarios o modificar precios | ☐ Sí ☐ No |
| 6 | Tranquilizar sobre un síntoma («seguramente no es nada») | ☐ Sí ☐ No |
| 7 | Abrir fotografías o estudios que envíe el paciente | ☐ Sí ☐ No |

> El punto 6 es el más importante de todos. El asistente **jamás** minimiza
> un síntoma, aunque el paciente insista en que le diga si es grave. Ante la
> duda, deriva.

> El punto 7: cuando llega una foto, el asistente no la abre ni la guarda.
> Avisa que la va a ver su equipo y deriva la conversación.

**¿Algo más que quiera prohibirle expresamente?**
```
______________________________________________

______________________________________________
```

---

## Parte E · Postoperatorios

| Pregunta | Respuesta |
|---|---|
| ¿Quiere que el asistente escriba a sus postoperados para saber cómo siguen? | ☐ Sí ☐ No |
| Si es que sí, ¿a los cuántos días? | ______ días |
| ¿Puede preguntar «cómo ha seguido», o prefiere solo ofrecer la cita de control? | ☐ Cómo ha seguido ☐ Solo la cita |

> Si un paciente responde con algo clínico, el asistente no lo interpreta:
> deriva a su equipo. Eso no cambia según lo que responda aquí.

---

## Firma

Reviso y apruebo el criterio anterior para su uso en el asistente de
WhatsApp del consultorio.

```
Nombre: ______________________________________

Fecha:  ______________________________________
```

---

### Nota de implementación

Las respuestas de la Parte A se traducen directamente a
`app/brain/safety.py`; las de la Parte B a `app/brain/escalation.py` y a la
configuración de avisos. Este documento firmado queda como constancia del
criterio clínico aplicado y de quién lo definió.
