"""
Capa de IA. Solo se invoca cuando el asistente no reconoció la intención.

Tres candados, en este orden:

1. La barrera clínica ya corrió. Si bloqueó, la IA NO ve el mensaje.
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

def construir_sistema(contexto_consultorio: str, contexto_paciente: str = "") -> str:
    from app.brain.safety import RESTRICCIONES_PROMPT

    return f"""\
Eres el asistente de WhatsApp del consultorio del Dr. José Guadalupe Padilla,
Cirujano General y Laparoscópico, en Guadalajara, México.

Te comportas como una recepcionista con experiencia: cálida, breve, clara y
profesional. Hablas de usted. No usas menús numerados ni suenas robótica.
Tu objetivo es resolver la consulta y, cuando corresponda, agendar la cita.

{RESTRICCIONES_PROMPT}

CÓMO ESCRIBES
- Mensajes cortos. Dos o tres oraciones. Es WhatsApp, no un correo.
- Una sola pregunta por mensaje.
- Nunca inventas datos. Si no sabes un precio, un horario o una dirección,
  lo dices y derivas al consultorio. Inventar es peor que no saber.
- No eres insistente ni presionas al paciente.

INFORMACIÓN DEL CONSULTORIO
{contexto_consultorio}

{contexto_paciente}

Si el paciente pide algo que no puedes resolver, respondes que lo comunicas
con el equipo del consultorio y que en breve lo contactan.
"""


# ----------------------------------------------------------------------
#  Llamada
# ----------------------------------------------------------------------

async def responder(
    *,
    mensaje: str,
    contexto_consultorio: str,
    contexto_paciente: str = "",
    historial: list[dict[str, str]] | None = None,
) -> RespuestaIA | None:
    """
    Devuelve None si la IA no está disponible: sin clave configurada o con
    el tope de gasto alcanzado. Quien llama debe caer al modo básico.
    """
    if not config.openai_api_key:
        log.info("OPENAI_API_KEY sin configurar; se responde en modo básico")
        return None

    if tope_alcanzado():
        log.warning("Tope de gasto alcanzado; se responde en modo básico")
        return None

    from openai import AsyncOpenAI

    cliente = AsyncOpenAI(api_key=config.openai_api_key)

    mensajes = [{"role": "system", "content": construir_sistema(
        contexto_consultorio, contexto_paciente
    )}]
    mensajes += (historial or [])[-10:]
    mensajes.append({"role": "user", "content": mensaje})

    try:
        r = await cliente.chat.completions.create(
            model=config.openai_model,
            messages=mensajes,  # type: ignore[arg-type]
            temperature=0.4,
            max_tokens=350,
        )
    except Exception:
        log.exception("Falló la llamada a OpenAI; se responde en modo básico")
        return None

    uso = r.usage
    entrada = uso.prompt_tokens if uso else 0
    salida = uso.completion_tokens if uso else 0
    costo = _costo(config.openai_model, entrada, salida)
    _registrar(entrada, salida, costo)

    return RespuestaIA(
        texto=(r.choices[0].message.content or "").strip(),
        tokens_entrada=entrada,
        tokens_salida=salida,
        costo_usd=costo,
    )
