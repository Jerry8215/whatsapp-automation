"""
Cuándo la conversación deja de ser del asistente y pasa a una persona.

Las reglas acordadas con el consultorio:

  1. El paciente describe una posible urgencia          → inmediato
  2. Menciona síntomas o envía fotografías              → inmediato
  3. Pide hablar directamente con el doctor             → inmediato
  4. Se detecta molestia o reclamo                      → inmediato
  5. Repite la misma pregunta sin obtener respuesta     → al 2º intento
  6. La conversación lleva más de 10 min sin avanzar    → por tiempo
  7. Pide factura                                       → a la asistente

Regla de diseño: es preferible derivar de más que de menos. Una
conversación derivada sin necesidad le cuesta a la asistente treinta
segundos. Una que debió derivarse y no se derivó le puede costar a un
paciente mucho más.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.brain.intents import Clasificacion
from app.brain.safety import Accion, Veredicto, normalizar
from app.models import Intencion, MotivoEscalado

MINUTOS_ESTANCADA = 10
INTENTOS_ANTES_DE_DERIVAR = 2


@dataclass(frozen=True)
class Decision:
    escalar: bool
    motivo: MotivoEscalado | None = None
    urgente: bool = False
    aviso: str = ""          # texto del aviso a la asistente / Telegram

    @property
    def prioridad(self) -> str:
        return "alta" if self.urgente else "normal"


NO_ESCALAR = Decision(escalar=False)


PIDE_DOCTOR = re.compile(
    r"\b(?:quiero|necesito|puedo|prefiero|me gustaria) (?:hablar|platicar|que me (?:llame|contacte|explique)) "
    r"(?:con )?(?:el |la )?(?:dr|dra|doctor|doctora|padilla)\b"
    r"|\bcon (?:el |la )?(?:dr|doctor|doctora) padilla\b"
    r"|\bque me (?:llame|marque|contacte) (?:una persona|alguien|el doctor)\b"
    r"|\bquiero hablar con (?:alguien|una persona|un humano)\b"
    r"|\bno quiero (?:hablar con )?(?:un )?(?:bot|robot|maquina)\b"
    r"|\beres (?:un )?(?:bot|robot|maquina)\b"
)

MOLESTIA = re.compile(
    r"\bno me parece\b"
    r"|\besto es (?:un )?(?:desastre|pesimo|inaceptable|una falta de respeto)\b"
    r"|\b(?:pesimo|pesima|malisimo|terrible) (?:servicio|atencion)\b"
    r"|\b(?:ya )?(?:van|llevo) (?:dos|tres|varias|muchas) veces\b"
    r"|\bes la (?:segunda|tercera) vez que\b"
    r"|\bquiero (?:poner )?(?:una )?queja\b"
    r"|\bvoy a (?:reclamar|quejarme|reportar)\b"
    r"|\bme (?:estan )?(?:haciendo perder el tiempo|tomando el pelo)\b"
    r"|\bque falta de (?:respeto|seriedad|profesionalismo)\b"
    r"|\bexijo\b"
    r"|\bme (?:urge|corre prisa) y nadie\b"
    r"|\bnadie me (?:contesta|responde|hace caso)\b"
    r"|\bya me (?:cansé|canse|harté|harte)\b"
)

FRUSTRACION_SUAVE = re.compile(
    r"\bno (?:me )?(?:entiendes|entiende|estas entendiendo)\b"
    r"|\bno es lo que (?:pregunte|te pregunte|estoy preguntando)\b"
    r"|\bte estoy diciendo que\b"
    r"|\bya te dije\b"
    r"|\bootra vez lo mismo\b"
)


def decidir(
    *,
    veredicto: Veredicto,
    clasificacion: Clasificacion,
    texto: str,
    intentos_fallidos: int,
    abierta_en: datetime,
    ahora: datetime | None = None,
) -> Decision:
    """
    Se llama con cada mensaje del paciente, después de la barrera clínica
    y de la clasificación de intención.
    """
    ahora = ahora or datetime.utcnow()
    t = normalizar(texto)

    # 1 y 2 — la barrera clínica manda. Ya decidió.
    if veredicto.accion is Accion.URGENCIAS:
        return Decision(
            escalar=True,
            motivo=MotivoEscalado.POSIBLE_URGENCIA,
            urgente=True,
            aviso=(
                "POSIBLE URGENCIA. El paciente describe signos de alarma "
                f"(«{veredicto.coincidencia}»). Se le indicó acudir a urgencias. "
                "Contactar de inmediato."
            ),
        )

    if veredicto.accion is Accion.DERIVAR:
        return Decision(
            escalar=True,
            motivo=MotivoEscalado.CONTENIDO_CLINICO,
            urgente=False,
            aviso=(
                f"Contenido clínico ({veredicto.categoria.value}). El asistente "
                "no respondió el fondo y derivó la conversación."
            ),
        )

    # 3 — pidió expresamente a una persona
    if PIDE_DOCTOR.search(t):
        return Decision(
            escalar=True,
            motivo=MotivoEscalado.PIDIO_DOCTOR,
            aviso="El paciente pidió hablar directamente con el doctor o con una persona.",
        )

    # 4 — molestia o reclamo
    if MOLESTIA.search(t):
        return Decision(
            escalar=True,
            motivo=MotivoEscalado.MOLESTIA,
            urgente=True,
            aviso="Se detectó molestia o reclamo del paciente. Conviene atenderlo pronto.",
        )

    # 7 — facturación: el asistente no factura, la asistente sí
    if clasificacion.intencion is Intencion.FACTURACION and clasificacion.es_confiable:
        return Decision(
            escalar=True,
            motivo=MotivoEscalado.FACTURACION,
            aviso="Solicitud de facturación. Requiere a la asistente.",
        )

    # 5 — no se le entiende, o muestra frustración tras un tropiezo
    sin_entender = (
        clasificacion.intencion is Intencion.DESCONOCIDA
        or not clasificacion.es_confiable
    )
    if sin_entender and intentos_fallidos + 1 >= INTENTOS_ANTES_DE_DERIVAR:
        return Decision(
            escalar=True,
            motivo=MotivoEscalado.NO_COMPRENDIDO,
            aviso=(
                f"El asistente no logró interpretar al paciente en "
                f"{intentos_fallidos + 1} intentos."
            ),
        )

    if FRUSTRACION_SUAVE.search(t) and intentos_fallidos >= 1:
        return Decision(
            escalar=True,
            motivo=MotivoEscalado.NO_COMPRENDIDO,
            aviso="El paciente indica que no se le está entendiendo.",
        )

    # 6 — estancada
    if ahora - abierta_en > timedelta(minutes=MINUTOS_ESTANCADA) and sin_entender:
        return Decision(
            escalar=True,
            motivo=MotivoEscalado.ESTANCADA,
            aviso=(
                f"Conversación de más de {MINUTOS_ESTANCADA} minutos sin avanzar."
            ),
        )

    return NO_ESCALAR


MENSAJE_TRANSICION = (
    "Permítame un momento, la comunico con el equipo del consultorio para "
    "que la atiendan personalmente."
)

MENSAJE_TRANSICION_FUERA_HORARIO = (
    "Permítame un momento. En este momento el consultorio está cerrado, pero "
    "ya dejé su mensaje marcado como prioritario y la contactan en cuanto "
    "abran.\n\n"
    "Si se trata de algo que no puede esperar, acuda al servicio de urgencias "
    "más cercano."
)
