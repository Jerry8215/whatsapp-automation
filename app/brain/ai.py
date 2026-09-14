"""
Capa de IA — la que conversa.

En modo híbrido y en modo IA, esto es lo que le contesta al paciente. No es
un respaldo para cuando las reglas fallan: es el asistente. Las reglas
quedaron para el modo básico y para cuando la IA no está disponible.

El cambio importa. Un catálogo de respuestas fijas contesta bien la pregunta
que alguien previó, y contesta *lo mismo* a las otras diez formas de
preguntar lo mismo. Un paciente que escribe «oiga y si me urge, hay chance
hoy?» no está en ningún catálogo.

Además de hablar, el asistente **hace**: consulta la agenda real, reserva,
cancela y deriva, mediante las herramientas de `app/brain/herramientas.py`.
El modelo decide cuándo; el código decide qué pasa.

Tres candados, en este orden:

1. La barrera clínica ya corrió. Si bloqueó, la IA NO ve el mensaje. Ese
   sigue siendo el invariante del sistema.
2. Tope duro de gasto mensual. Al alcanzarlo el sistema cae solo a modo
   básico y avisa al consultorio. Nunca hay cargos sorpresa.
3. El prompt lleva las restricciones clínicas incorporadas, como segunda
   línea de defensa. La primera sigue siendo el paso 1.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import select

from app.config import config
from app.db import sesion
from app.models import ConsumoIA

log = logging.getLogger(__name__)

# Precio por millón de tokens. VERIFICAR contra la lista vigente de
# OpenAI antes de producción y al cambiar de modelo — estos valores
# cambian y de acá sale el medidor que ve el consultorio.
PRECIOS_USD_POR_MILLON: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}


@dataclass
class RespuestaIA:
    texto: str
    tokens_entrada: int = 0
    tokens_salida: int = 0
    costo_usd: float = 0.0
    uso_modelo: bool = True


def periodo_actual() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def consumo_del_mes() -> ConsumoIA:
    p = periodo_actual()
    with sesion() as s:
        registro = s.exec(select(ConsumoIA).where(ConsumoIA.periodo == p)).first()
        if not registro:
            registro = ConsumoIA(periodo=p)
            s.add(registro)
            s.commit()
            s.refresh(registro)
        return registro


def tope_alcanzado() -> bool:
    """True si ya se llegó al límite mensual configurado."""
    if config.ia_limite_mensual_usd <= 0:
        return False
    return consumo_del_mes().costo_usd >= config.ia_limite_mensual_usd


def _registrar(entrada: int, salida: int, costo: float) -> None:
    p = periodo_actual()
    with sesion() as s:
        registro = s.exec(select(ConsumoIA).where(ConsumoIA.periodo == p)).first()
        if not registro:
            registro = ConsumoIA(periodo=p)
        registro.tokens_entrada += entrada
        registro.tokens_salida += salida
        registro.costo_usd += costo
        registro.llamadas += 1
        if (
            config.ia_limite_mensual_usd > 0
            and registro.costo_usd >= config.ia_limite_mensual_usd
            and registro.tope_alcanzado_en is None
        ):
            registro.tope_alcanzado_en = datetime.utcnow()
            log.warning(
                "Tope mensual de IA alcanzado (USD %.2f). Se pasa a modo básico.",
                registro.costo_usd,
            )
        s.add(registro)
        s.commit()


def _costo(modelo: str, entrada: int, salida: int) -> float:
    p_ent, p_sal = PRECIOS_USD_POR_MILLON.get(modelo, (0.15, 0.60))
    return (entrada / 1_000_000) * p_ent + (salida / 1_000_000) * p_sal


# ----------------------------------------------------------------------
#  Prompt
# ----------------------------------------------------------------------

def construir_sistema(
    contexto_consultorio: str,
    contexto_paciente: str = "",
    *,
    abierto: bool = True,
    dichas: list[str] | None = None,
) -> str:
    from app.brain.safety import RESTRICCIONES_PROMPT
    from app.tiempo import DIAS, MESES, ahora_local

    ahora = ahora_local()
    momento = (
        f"Hoy es {DIAS[ahora.weekday()]} {ahora.day} de {MESES[ahora.month - 1]} "
        f"de {ahora.year}, y son las {ahora:%H:%M} en Guadalajara."
    )

    horario = (
        "El consultorio está ABIERTO en este momento."
        if abierto else
        "El consultorio está CERRADO en este momento. Puedes resolver dudas y "
        "agendar igual, pero NO prometas que alguien va a contestar ni que lo "
        "van a llamar en un rato: no hay nadie hasta que abran."
    )

    # Lo que ya se dijo en esta conversación. Sin esto, un paciente que
    # insiste recibe el mismo párrafo tres veces y siente que habla con una
    # grabación — que es exactamente lo que se quiere evitar.
    evitar = ""
    if dichas:
        listado = "\n".join(f"- «{t[:160]}»" for t in dichas[-3:])
        evitar = f"""
YA DIJISTE ESTO EN ESTA CONVERSACIÓN
{listado}

No lo repitas con las mismas palabras. Si el paciente vuelve a preguntar lo
mismo, es señal de que no le quedó claro: explícalo de otra manera, más
concreto, o pregúntale qué parte le falta. Si aun así insiste, deriva.
"""

    return f"""\
Eres el asistente de WhatsApp del consultorio del Dr. José Guadalupe Padilla,
Cirujano General y Laparoscópico, en Guadalajara, México.

Eres una recepcionista con años de experiencia: cálida, concreta y con
criterio. Hablas de usted, en español mexicano natural. Tu trabajo es que el
paciente se sienta atendido y, cuando corresponda, salga con su cita puesta.

{momento}
{horario}

{RESTRICCIONES_PROMPT}

CÓMO CONVERSAS
- Entiendes cómo escribe la gente de verdad: con faltas de ortografía, sin
  acentos, en audio transcrito, a medias, con modismos («ando malo», «me
  urge», «cuánto me sale», «pa cuándo hay»). Nunca le pidas al paciente que
  escriba de otra forma.
- Respondes lo que te preguntaron, no lo que hubieras querido que
  preguntaran. Si preguntan dos cosas, contestas las dos.
- Mensajes cortos: dos o tres oraciones. Es WhatsApp, no un correo.
- Una sola pregunta por mensaje.
- Nada de menús numerados ni de «seleccione una opción».
- No saludas de nuevo si ya venías conversando.
- No repites textual lo que ya dijiste. Reformula.
- No eres insistente. Ofreces la cita una vez; si no la quiere ahora, lo
  dejas ir con la puerta abierta.

LO QUE NUNCA INVENTAS
Precios, horarios, direcciones y disponibilidad salen ÚNICAMENTE de la
información de abajo y de tus herramientas. Lo mismo vale para lo que el
consultorio hace o no hace: qué cirugías o procedimientos realiza el doctor,
si atiende urgencias, si hay descuentos o promociones, qué seguros o
convenios acepta. Si no está escrito abajo, no lo afirmes ni lo niegues.
Dile con naturalidad que ese dato se lo confirma el equipo del consultorio y
ofrécele lo que sí puedes hacer, como agendar una valoración. Inventar es
peor que no saber: el paciente se presenta en una dirección que no existe, o
deja de venir porque le dijiste que algo no se hace.

Para cualquier cosa de agenda usa `consultar_disponibilidad` antes de
mencionar un horario. Jamás supongas que hay lugar.

Nunca anuncies que vas a hacer algo («permítame consultar», «déjeme
revisar»): hazlo en ese mismo momento con la herramienta y contesta con el
resultado. El paciente no ve que estás trabajando; solo ve un mensaje que
promete algo y después silencio.

CUÁNDO PASAS LA CONVERSACIÓN A UNA PERSONA
Usa `derivar_a_persona` si el paciente se molesta, pide hablar con el
doctor, necesita facturación, plantea algo que no puedes resolver, o si ya
diste dos vueltas sin avanzar. Derivar no es fallar: es lo correcto.

INFORMACIÓN DEL CONSULTORIO
{contexto_consultorio}

{contexto_paciente}
{evitar}"""


# ----------------------------------------------------------------------
#  Llamada
# ----------------------------------------------------------------------

def disponible() -> bool:
    """¿Se puede usar la IA ahora mismo?"""
    if not config.openai_api_key:
        return False
    return not tope_alcanzado()


#: Cuántas veces puede pedir herramientas antes de tener que contestar.
#: Con dos alcanza para «consulto disponibilidad → agendo → confirmo». El
#: límite existe para que un modelo confundido no encadene llamadas —y
#: gasto— sin fin.
MAX_RONDAS = 3


async def conversar(
    *,
    mensaje: str,
    contexto_consultorio: str,
    contexto_paciente: str = "",
    historial: list[dict[str, str]] | None = None,
    abierto: bool = True,
    dichas: list[str] | None = None,
    ctx=None,
) -> tuple[RespuestaIA | None, object]:
    """
    Conversa, con herramientas.

    Devuelve `(respuesta, efecto)`. `respuesta` es None si la IA no está
    disponible —sin clave o con el tope alcanzado— y ahí quien llama debe
    caer a los flujos. `efecto` dice si hay que derivar o si se creó una
    cita: eso lo aplica el router, no el modelo.
    """
    from app.brain.herramientas import ESQUEMA, Contexto, Efecto, ejecutar

    efecto = Efecto()

    if not config.openai_api_key:
        log.info("OPENAI_API_KEY sin configurar; se responde con los flujos")
        return None, efecto

    if tope_alcanzado():
        log.warning("Tope de gasto alcanzado; se responde con los flujos")
        return None, efecto

    from openai import AsyncOpenAI

    cliente = AsyncOpenAI(api_key=config.openai_api_key)

    mensajes: list[dict] = [{
        "role": "system",
        "content": construir_sistema(
            contexto_consultorio, contexto_paciente,
            abierto=abierto, dichas=dichas,
        ),
    }]
    mensajes += (historial or [])[-14:]
    mensajes.append({"role": "user", "content": mensaje})

    entrada_total = salida_total = 0
    costo_total = 0.0
    # Sin contexto de paciente no se ofrecen herramientas: no habría contra
    # quién agendar. Pasa en el simulador y en las pruebas.
    herramientas = ESQUEMA if ctx else None

    for ronda in range(MAX_RONDAS):
        try:
            peticion = {
                "model": config.openai_model,
                "messages": mensajes,
                "temperature": 0.5,
                "max_tokens": 400,
            }
            if herramientas and ronda < MAX_RONDAS - 1:
                peticion["tools"] = herramientas
                peticion["tool_choice"] = "auto"

            r = await cliente.chat.completions.create(**peticion)  # type: ignore[arg-type]
        except Exception:
            log.exception("Falló la llamada a OpenAI; se responde con los flujos")
            # Si ya se gastó en rondas anteriores, se registra igual: el
            # medidor del consultorio tiene que reflejar lo que se consumió.
            if entrada_total or salida_total:
                _registrar(entrada_total, salida_total, costo_total)
            return None, efecto

        uso = r.usage
        entrada = uso.prompt_tokens if uso else 0
        salida = uso.completion_tokens if uso else 0
        entrada_total += entrada
        salida_total += salida
        costo_total += _costo(config.openai_model, entrada, salida)

        eleccion = r.choices[0].message
        llamadas = getattr(eleccion, "tool_calls", None)

        if not llamadas:
            _registrar(entrada_total, salida_total, costo_total)
            return RespuestaIA(
                texto=(eleccion.content or "").strip(),
                tokens_entrada=entrada_total,
                tokens_salida=salida_total,
                costo_usd=costo_total,
            ), efecto

        mensajes.append({
            "role": "assistant",
            "content": eleccion.content,
            "tool_calls": [
                {
                    "id": l.id,
                    "type": "function",
                    "function": {"name": l.function.name, "arguments": l.function.arguments},
                }
                for l in llamadas
            ],
        })

        for llamada in llamadas:
            resultado = await ejecutar(
                llamada.function.name,
                llamada.function.arguments,
                ctx if isinstance(ctx, Contexto) else Contexto(0, 0, ""),
                efecto,
            )
            mensajes.append({
                "role": "tool",
                "tool_call_id": llamada.id,
                "content": resultado,
            })

    # Agotó las rondas sin redactar una respuesta. Es raro, pero el paciente
    # no puede quedarse esperando: lo atiende una persona.
    _registrar(entrada_total, salida_total, costo_total)
    log.warning("La IA agotó las rondas de herramientas sin responder")
    if not efecto.derivar:
        efecto.derivar = "El asistente no logró cerrar la consulta."
    return None, efecto


async def responder(
    *,
    mensaje: str,
    contexto_consultorio: str,
    contexto_paciente: str = "",
    historial: list[dict[str, str]] | None = None,
) -> RespuestaIA | None:
    """Conversación sin herramientas. Se conserva para el simulador y las pruebas."""
    respuesta, _ = await conversar(
        mensaje=mensaje,
        contexto_consultorio=contexto_consultorio,
        contexto_paciente=contexto_paciente,
        historial=historial,
    )
    return respuesta
