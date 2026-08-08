# Despliegue

Meta exige una URL pública con HTTPS para el webhook, así que hay que
desplegar antes de poder probar nada en WhatsApp real.

**Regla del proyecto:** el servidor va en una cuenta **a nombre del
consultorio**, no del desarrollador. Si mañana se corta la relación, la
infraestructura sigue siendo del Dr. Padilla. Al principio puede quedar en
una cuenta propia para la etapa de pruebas, pero antes de la migración del
número (día 14) se transfiere.

---

## 1. Servidor

Railway o Render sirven igual. Ambos dan HTTPS automático, que es lo que
Meta necesita.

Desde el tablero de Railway, sin instalar nada:

1. **railway.app** → entrar con GitHub
2. **New Project → Deploy from GitHub repo** → elegir el repositorio
3. **New → Database → PostgreSQL** dentro del mismo proyecto
4. Cargar las variables (abajo) en *Variables*
5. **Settings → Networking → Generate Domain**

Railway detecta el `Dockerfile` y lo usa. Cada `git push` vuelve a
desplegar solo.

> **Por qué Dockerfile y no la detección automática.** Con Nixpacks la
> versión de Python la resuelve el catálogo del proveedor, y un despliegue
> que funciona hoy puede romperse mañana sin que nadie haya tocado el
> código. En el Dockerfile la versión está fijada.

> `DATABASE_URL` la inyecta Railway con la forma `postgresql://...`, que
> haría a SQLAlchemy buscar psycopg2 — no instalado, porque el proyecto usa
> psycopg 3. `app/config.py` la reescribe sola. No hay que tocarla.

> **La base hay que referenciarla.** Agregar PostgreSQL al proyecto no
> alcanza: en las variables del servicio hay que poner
> `DATABASE_URL=${{Postgres.DATABASE_URL}}`. Sin eso el servicio arranca con
> SQLite y pierde todo en cada despliegue. El arranque lo advierte en el
> registro.

> **Si la plataforma insiste en construir sin el Dockerfile** y falla con
> `mise ERROR ... No GitHub artifact attestations found for python`, revisar
> en *Settings → Build* que el constructor sea Dockerfile. Como alternativa,
> agregar la variable `MISE_PYTHON_GITHUB_ATTESTATIONS=false`.

Variables de entorno mínimas para arrancar:

```
ENTORNO=produccion
DATABASE_URL=postgresql+psycopg://...    # el que provea la plataforma
PANEL_SECRETO=<64 caracteres aleatorios>
WA_VERIFY_TOKEN=<cadena aleatoria propia>
WA_APP_SECRET=<de la app de Meta>
WA_TOKEN=<token del usuario del sistema>
WA_PHONE_NUMBER_ID=<del número>
ZONA_HORARIA=America/Mexico_City
AGENDA_PROVEEDOR=franjas
```

> En producción, sin `WA_APP_SECRET` el webhook **rechaza todo**. Es
> deliberado: sin firma, cualquiera que conozca la URL podría inyectar
> mensajes falsos y hacer que el asistente agende citas.

Comprobar que arrancó:

```
GET https://<su-dominio>/salud
```

---

## 2. Número de prueba de Meta

**No hace falta el Business Manager del consultorio para esto.** Sirve para
demostrar el sistema mientras llega la invitación.

1. Crear una app en `developers.facebook.com` → tipo **Business**.
2. Agregar el producto **WhatsApp**.
3. Meta asigna un número de prueba y un token temporal (dura 24 h; para algo
   estable, crear un usuario del sistema).
4. En **API Setup**, agregar los números destinatarios autorizados — hasta
   cinco. Ahí va el celular del Dr. Padilla y el de la asistente.
5. Copiar `Phone number ID` y el token a las variables de entorno.

Limitaciones del número de prueba, para tenerlas presentes:

- Solo escribe a los números registrados como destinatarios.
- No sirve para migrar el número real.
- Las plantillas se aprueban sobre la cuenta definitiva, no sobre esta.

Alcanza de sobra para que el doctor converse con el asistente desde su
propio WhatsApp.

---

## 3. Webhook

En la app de Meta → **WhatsApp → Configuration → Webhook**:

| Campo | Valor |
|---|---|
| Callback URL | `https://<su-dominio>/webhook` |
| Verify token | el mismo de `WA_VERIFY_TOKEN` |

Suscribirse a los campos **`messages`** y **`message_template_status_update`**.

Si la verificación falla, revisar en este orden: que el token coincida
exactamente, que la URL responda por HTTPS, y que `/webhook` conteste al GET
de verificación (se puede probar a mano con el navegador).

---

## 4. Datos iniciales

```bash
python -m app.seed
```

Después, **cambiar las contraseñas** de `doctor@consultorio.local` y
`asistente@consultorio.local`. Las que crea el seed son provisionales y
están en el repositorio.

Cargar el contenido real del consultorio en cuanto llegue: precios,
horarios, direcciones de las tres sedes, convenios e indicaciones previas.

---

## 5. Antes de la migración del número real

Lista de verificación para el día 14:

- [ ] Verificación del negocio aprobada por Meta
- [ ] Plantillas aprobadas
- [ ] Panel funcionando y personal capacitado
- [ ] Franjas configuradas en cada sede activa
- [ ] Criterio de urgencias firmado por el Dr. Padilla
- [ ] Contraseñas cambiadas
- [ ] Respaldo del historial de WhatsApp hecho en el celular
- [ ] Día y hora de menor movimiento confirmados con el consultorio
- [ ] Verificación en dos pasos activada en el número
- [ ] Servidor y cuenta de Meta a nombre del consultorio

---

## 6. Entrega final

- Transferir el servidor y la base de datos a una cuenta del consultorio.
- Rotar todas las credenciales.
- Quitar el acceso del desarrollador y dejar constancia por escrito.
- El sistema se conecta con un **usuario del sistema** de Meta, no con una
  cuenta personal: nada queda atado al desarrollador.
