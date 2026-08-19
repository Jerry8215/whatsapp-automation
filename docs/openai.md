# Configurar OpenAI

Sin `OPENAI_API_KEY` el asistente **sigue funcionando**, pero solo con los
flujos: contesta bien lo previsto y repite la misma respuesta ante cualquier
otra forma de preguntar. Es un fallo silencioso —desde afuera parece que
todo está bien— y es exactamente lo que reportó el consultorio.

Desde ahora se avisa en tres lugares: en el registro del despliegue, en
`/salud` (`ia.configurada`) y en el panel, en Configuración.

---

## 0. De quién es la cuenta

Decisión antes que trámite. Al consultorio se le dijo, por escrito, que
**OpenAI se le paga directo al proveedor, no al desarrollador**. Eso implica
que la cuenta debe terminar a nombre del consultorio, igual que el servidor.

Lo práctico:

| Momento | Qué conviene |
|---|---|
| Ahora, para probar | La clave del desarrollador. Son centavos y no frena nada. |
| Antes de migrar el número | La cuenta del consultorio, con su tarjeta y su tope. |

Cuando se cambie, se reemplaza la variable y se revoca la clave vieja. No
hay que tocar código ni migrar nada.

---

## 1. Crear la cuenta y cargar saldo

**Es <https://platform.openai.com>, no ChatGPT.** Son dos productos
distintos y es la confusión más común:

- **ChatGPT Plus** — USD 20 al mes, para usar el chat desde el navegador.
  **No sirve para esto** y no habilita nada del sistema.
- **La API** — se paga por uso, sin cuota fija ni mínimo mensual. Si un mes
  no escribe nadie, no se paga nada.

Pasos:

1. Entrar a <https://platform.openai.com> y crear la cuenta.
2. **Settings → Billing → Payment methods**: agregar una tarjeta.
3. **Add credit balance**: la API funciona con saldo prepagado. Con USD 5 o
   10 sobra para meses de un consultorio.

> Sin saldo cargado, las llamadas fallan con `429 insufficient_quota` y el
> asistente cae a los flujos. Se ve igual que si no hubiera clave: hay que
> mirar el registro para distinguirlo.

---

## 2. Poner un tope del lado de OpenAI

Es la **doble red** que se le prometió al consultorio: un tope en el sistema
y otro en la plataforma.

**Settings → Limits**:

- *Budget limit* — al alcanzarlo, OpenAI deja de responder.
- *Email notification threshold* — un aviso antes de llegar.

Recomendado: budget en USD 10 al mes y aviso en USD 5. Para el volumen de un
consultorio no se acerca ni de lejos, y garantiza que no haya sorpresas
aunque algo se comporte mal.

---

## 3. Crear la clave

1. **Dashboard → API keys → Create new secret key**.
2. Nombrarla de forma reconocible: `asistente-consultorio-padilla`.
3. Si la cuenta tiene proyectos, asignarla a un proyecto propio. Así el
   límite y el consumo de este sistema quedan separados de cualquier otra
   cosa de la misma cuenta.
4. **Copiarla en ese momento.** Empieza con `sk-` y no se vuelve a mostrar.
   Si se pierde, se revoca y se crea otra; no se puede recuperar.

La clave es una credencial de pago: quien la tenga puede gastar de esa
cuenta. No va al repositorio, ni por WhatsApp, ni en una captura de
pantalla.

---

## 4. Cargarla en el servidor

En Railway: proyecto → el servicio `whatsapp-automation` → pestaña
**Variables** → **New Variable**.

| Variable | Valor | Obligatoria |
|---|---|---|
| `OPENAI_API_KEY` | `sk-...` | **Sí** |
| `OPENAI_MODEL` | `gpt-4o-mini` | No, es el valor por defecto |
| `IA_LIMITE_MENSUAL_USD` | `15.00` | No, es el valor por defecto |
| `MODO_ASISTENTE` | `hibrido` | No, y además manda el panel |

Railway vuelve a desplegar solo al guardar una variable. No hace falta
hacer nada más.

En local, en el `.env` (que está fuera del repositorio por `.gitignore`):

```bash
OPENAI_API_KEY=sk-...
```

> **Si cambia `OPENAI_MODEL`, hay que actualizar `PRECIOS_USD_POR_MILLON`
> en `app/brain/ai.py`.** Con un modelo que no esté en esa tabla, el medidor
> cobra a precio de `gpt-4o-mini` y el tope mensual deja de proteger de
> verdad. Es un error caro y silencioso.

---

## 5. Comprobar que quedó bien

**En el registro del despliegue** ya no debe aparecer:

```
MODO «hibrido» PERO SIN OPENAI_API_KEY: el asistente va a funcionar en
modo básico y repetirá respuestas fijas ante lo que no tenga previsto.
```

**En `/salud`**:

```json
"modo": "hibrido",
"ia": { "configurada": true, "modelo": "gpt-4o-mini", "gasto_usd": 0.0 }
```

Si `configurada` es `false`, la variable no llegó al servicio.

**En el panel**, en Configuración, no debe verse el aviso de que falta la
clave.

**Conversando**, en el simulador:

1. Escriba algo que ningún catálogo tenga:
   `oiga y el doctor hace lo de la vesicula por laparoscopia o abierto?`
2. Vuelva a Configuración: el medidor de consumo **se movió**.
3. Pregunte dos veces lo mismo con distintas palabras. La segunda respuesta
   debe estar redactada distinto.

---

## 6. Cuánto va a costar de verdad

Con el modo híbrido, el saludo, el precio, la dirección y los horarios los
resuelven los flujos sin llamar al modelo. Solo se paga por lo no previsto y
por las repreguntas.

Con `gpt-4o-mini`, una conversación que sí llega al modelo cuesta del orden
de **una milésima de dólar**. Para 200 o 300 conversaciones al mes —volumen
alto para un consultorio— el gasto real ronda **USD 1 a 3 mensuales**.

El tope de `IA_LIMITE_MENSUAL_USD` en 15 deja muchísimo margen; se puede
bajar a 5 sin ningún riesgo práctico.

---

## 7. Si algo falla

El sistema nunca deja al paciente sin respuesta: ante cualquier problema
con OpenAI, contestan los flujos. Lo que cambia es lo que se ve en el
registro.

| Síntoma | Causa | Solución |
|---|---|---|
| `401 invalid_api_key` | Clave mal copiada o revocada | Crear otra y reemplazarla |
| `429 insufficient_quota` | Sin saldo en la cuenta | Cargar saldo |
| `429 rate_limit_exceeded` | Demasiadas llamadas seguidas | Se reintenta solo; raro en este volumen |
| `ia.configurada: false` | La variable no llegó al servicio | Revisar Railway y volver a desplegar |
| Contesta, pero repite | Cayó a modo básico | Mirar el registro; suele ser una de las de arriba |

**Si la clave se expuso** —una captura, un repositorio, un mensaje—
revocarla en el acto desde el panel de OpenAI y crear otra. Revocar es
inmediato y no rompe nada más que esa clave.
