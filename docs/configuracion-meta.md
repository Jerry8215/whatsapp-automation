# Configuración de Meta — guía para el consultorio

Esta guía la ejecuta **el Dr. Padilla o su asistente**, con el desarrollador
guiando por videollamada. El acceso a la cuenta nunca sale de sus manos.

Se hace desde una computadora, no desde el celular. Toma unos 40 minutos.

**Lo que hay que tener a mano antes de empezar:**

- La cuenta de Facebook con la que administra el negocio
- La Constancia de Situación Fiscal del consultorio
- El celular del doctor y el de la asistente
- Los tres valores que le pasa el desarrollador: dirección del servidor,
  una palabra clave de verificación, y el nombre a mostrar

---

## Paso 1 · Crear la aplicación

1. Entrar a **developers.facebook.com** y elegir **Mis aplicaciones**.
2. **Crear aplicación**.
3. Caso de uso: **Otro** → tipo **Negocio (Business)**.
4. Nombre: `Asistente Consultorio Padilla`. Correo de contacto: el suyo.
5. Seleccionar el negocio del consultorio, si aparece en la lista.

> Anotar el **ID de la aplicación**, que aparece arriba de todo.

---

## Paso 2 · Agregar WhatsApp

1. En el panel de la aplicación, buscar **WhatsApp** y pulsar **Configurar**.
2. Meta crea automáticamente una cuenta de WhatsApp Business y asigna un
   **número de prueba**.

En esa pantalla hay que copiar y pasarle al desarrollador tres valores:

| Dónde dice | Qué es |
|---|---|
| **Identificador del número de teléfono** | `WA_PHONE_NUMBER_ID` |
| **Identificador de la cuenta de WhatsApp Business** | `WA_BUSINESS_ACCOUNT_ID` |
| El número de prueba que muestra | Para las pruebas |

> El número de prueba sirve para probarlo todo sin tocar el número real del
> consultorio. Ese se migra al final.

---

## Paso 3 · Autorizar los teléfonos de prueba

En la misma pantalla, en **Para**, pulsar **Administrar lista de teléfonos**
y agregar:

- El celular del Dr. Padilla
- El celular de la asistente
- El del desarrollador

A cada uno le llega un código de verificación por WhatsApp.

> Son hasta cinco números. El número de prueba **solo** puede escribirle a
> estos, por eso hay que registrarlos.

---

## Paso 4 · El token permanente

El token que Meta muestra por defecto **vence a las 24 horas**. Para que el
sistema no se caiga al día siguiente hay que crear uno que no caduque.

1. Ir a **business.facebook.com** → **Configuración del negocio**.
2. **Usuarios → Usuarios del sistema** → **Agregar**.
3. Nombre: `Asistente WhatsApp`. Rol: **Empleado**.
4. Seleccionarlo y pulsar **Asignar recursos**:
   - **Aplicaciones** → la que se creó → **Administrar aplicación**
   - **Cuentas de WhatsApp** → la del consultorio → **Control total**
5. **Generar nuevo token**:
   - Aplicación: la que se creó
   - Caducidad: **Nunca**
   - Permisos: `whatsapp_business_messaging` y `whatsapp_business_management`
6. **Copiar el token completo y pasárselo al desarrollador.**

> ⚠️ Ese token se muestra **una sola vez**. Si se cierra la ventana sin
> copiarlo, hay que generar otro.
>
> Es una cadena muy larga. Hay que copiarla entera, sin espacios ni saltos
> de línea.

---

## Paso 5 · El secreto de la aplicación

1. En developers.facebook.com → la aplicación → **Configuración → Básica**.
2. En **Clave secreta de la aplicación**, pulsar **Mostrar**.
3. Copiarla y pasársela al desarrollador. Es `WA_APP_SECRET`.

> Sirve para que el sistema pueda comprobar que cada mensaje viene
> realmente de Meta. Sin esto, alguien que conociera la dirección del
> servidor podría enviar mensajes falsos.

---

## Paso 6 · Conectar el webhook

Es el paso que le permite al sistema recibir los mensajes de los pacientes.
El desarrollador entrega los dos valores.

1. En la aplicación → **WhatsApp → Configuración**.
2. En **Webhook**, pulsar **Editar**.
3. Completar:

| Campo | Valor |
|---|---|
| URL de devolución de llamada | `https://<servidor>/webhook` |
| Token de verificación | la palabra clave que entrega el desarrollador |

4. **Verificar y guardar.** Si da error, avisar antes de seguir.
5. En **Campos del webhook**, pulsar **Administrar** y suscribirse a:
   - **`messages`** — imprescindible
   - **`message_template_status_update`** — para saber si Meta aprueba las
     plantillas

---

## Paso 7 · Verificación del negocio

Necesaria para usar el número real y para levantar el límite de mensajes.

1. **business.facebook.com** → **Configuración del negocio** →
   **Centro de seguridad**.
2. **Iniciar verificación**.
3. Cargar la **Constancia de Situación Fiscal** y los datos del consultorio.

> Meta suele tardar de 1 a 3 días hábiles. Conviene iniciarla cuanto antes:
> mientras esté pendiente, el número tiene un límite bajo de mensajes.

---

## Paso 8 · Las plantillas

Son los textos aprobados para escribirle primero a un paciente — los
recordatorios de cita. Sin ellas no hay recordatorios.

1. **business.facebook.com** → **WhatsApp Manager** → **Plantillas de
   mensaje** → **Crear plantilla**.
2. Cargar las cuatro que están en `docs/plantillas-whatsapp.md`, tal cual:
   nombre, categoría **Utilidad**, idioma **Español (México)**, cuerpo y
   botones.

> Meta tarda entre unos minutos y 48 horas en aprobarlas. Un rechazo se
> corrige y se reenvía, sin penalización.

---

## Comprobar que todo quedó bien

Con los valores cargados en el servidor, el desarrollador abre la página de
**Diagnóstico** del panel. Esa página consulta a Meta directamente y dice
qué falta:

- Si el token es válido y no está por vencer
- Si el webhook quedó suscrito a los mensajes
- El estado de cada plantilla
- La calificación de calidad del número
- Si la verificación del negocio sigue pendiente

Así se verifica sin tener que revisar la consola de Meta pantalla por
pantalla.

---

## Los valores a entregar al desarrollador

Conviene mandarlos juntos, en un solo mensaje:

```
WA_PHONE_NUMBER_ID      = ..........
WA_BUSINESS_ACCOUNT_ID  = ..........
WA_TOKEN                = .......... (el permanente del paso 4)
WA_APP_SECRET           = .......... (paso 5)
Número de prueba        = ..........
```

**El token y la clave secreta son credenciales.** Conviene enviarlas por un
canal distinto al del resto, y cambiarlas si alguna vez se sospecha que se
filtraron. Se pueden revocar en cualquier momento desde la misma pantalla
donde se generaron.
