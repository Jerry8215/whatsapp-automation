"""
Barrera clínica. Es el módulo más importante del sistema.

Reglas que no se negocian:

1.  Corre ANTES que cualquier otra cosa, y antes de que intervenga la IA.
2.  Es determinístico. No depende de un modelo de lenguaje, porque un
    modelo puede fallar y aquí el costo de fallar lo paga un paciente.
3.  Ante la duda, deriva. Nunca tranquiliza, nunca minimiza, nunca
    interpreta, nunca sugiere que algo "probablemente no es nada".
4.  Cualquier adjunto (foto, estudio, audio) se deriva sin abrirse.

El asistente no emite diagnósticos, no recomienda medicamentos, no
interpreta estudios, no promete resultados y no toma decisiones
clínicas. Este archivo es donde eso se hace cumplir.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum


class Accion(str, Enum):
    CONTINUAR = "continuar"      # nada clínico, sigue el flujo normal
    DERIVAR = "derivar"          # a una persona, sin responder el fondo
    URGENCIAS = "urgencias"      # signos de alarma: mandar a urgencias YA


class Categoria(str, Enum):
    NINGUNA = "ninguna"
    SIGNO_ALARMA = "signo_alarma"
    SINTOMAS = "sintomas"
    MEDICAMENTO = "medicamento"
    ESTUDIO = "estudio"
    PRONOSTICO = "pronostico"
    ADJUNTO = "adjunto"


@dataclass(frozen=True)
class Veredicto:
    accion: Accion
    categoria: Categoria
    respuesta: str = ""
    coincidencia: str = ""

    @property
    def bloquea_ia(self) -> bool:
        """Si es True, la IA no ve este mensaje. Nunca."""
        return self.accion is not Accion.CONTINUAR


# ------------------------------------------------------------------
#  Normalización
# ------------------------------------------------------------------

def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos, espacios colapsados."""
    t = unicodedata.normalize("NFD", texto.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t).strip()


def _patron(*frases: str) -> re.Pattern[str]:
    """Compila alternativas con límites de palabra."""
    return re.compile(r"\b(?:" + "|".join(frases) + r")\b")


# ------------------------------------------------------------------
#  1. Signos de alarma  →  URGENCIAS
#     Criterio a validar y firmar por el Dr. Padilla antes de producción.
#     Cirugía general / laparoscópica: abdomen agudo y postoperatorio.
# ------------------------------------------------------------------

SIGNOS_ALARMA = _patron(
    # abdomen agudo
    r"dolor (?:muy )?(?:fuerte|intenso|insoportable|severo)",
    r"no aguanto el dolor",
    r"me duele much[oi]simo",
    r"dolor que no se (?:quita|calma)",
    r"abdomen (?:duro|rigido|muy inflamado)",
    r"panza (?:dura|muy inflamada)",
    r"no puedo (?:pasar gases|evacuar|obrar)",
    # sistémicos
    r"fiebre (?:alta|de 39|de 40)",
    r"(?:tengo|traigo|ando con|traia) (?:3[89]|4[01])(?:\.\d)? de (?:fiebre|temperatura)",
    r"escalofrios",
    r"me desmaye",
    r"me estoy desmayando",
    r"no puedo respirar",
    r"me falta el aire",
    r"dolor en el pecho",
    # sangrado
    r"estoy sangrando",
    r"sangrado (?:abundante|que no para)",
    r"sangre en (?:el vomito|las heces|la orina|el excremento)",
    r"vomito con sangre",
    r"vomite sangre",
    # vómito persistente
    r"no (?:puedo|paro de) (?:parar de )?vomitar",
    r"llevo (?:vomitando|dias vomitando)",
    r"vomito todo lo que como",
    # ictericia
    r"(?:piel|ojos) amarill[oa]s?",
    r"me puse amarill[oa]",
    # herida quirúrgica complicada
    r"(?:la )?herida (?:se me )?(?:abrio|se abrio|esta abierta)",
    r"(?:sale|salio|tiene) (?:pus|liquido|material) (?:de|por) la herida",
    r"herida (?:esta |se ve |se puso )?(?:muy )?(?:roja|caliente|infectada|con mal olor)",
    r"se me (?:salio|zafo) (?:un )?punto",
)

RESPUESTA_URGENCIAS = (
    "Por lo que me describe es importante que la valoren hoy mismo de forma "
    "presencial. Le pido que acuda al servicio de urgencias más cercano sin "
    "esperar.\n\n"
    "Ya avisé al equipo del Dr. Padilla para que la contacten. Si el malestar "
    "aumenta, no espere la llamada y acuda de inmediato."
)


# ------------------------------------------------------------------
#  2. Descripción de síntomas o pedido de opinión clínica  →  DERIVAR
# ------------------------------------------------------------------

SINTOMAS = _patron(
    r"me duele",
    r"tengo dolor",
    r"siento (?:un|una|que)",
    r"me arde",
    r"me punza",
    r"traigo (?:un|una)",
    r"me salio (?:un|una|una bolita|una bola)",
    r"tengo (?:una )?(?:bolita|bola|masa|protuberancia)",
    r"se me (?:inflamo|hincho|puso)",
    r"esta(?: muy)? (?:rojo|roja|inflamado|inflamada|hinchado|hinchada|morado|morada)",
    r"tengo (?:nauseas|diarrea|estrenimiento|acidez|reflujo|gases)",
    r"tengo (?:fiebre|temperatura)",
    r"no puedo dormir del dolor",
)

OPINION_CLINICA = _patron(
    r"(?:es|sera|puede ser) (?:normal|grave|serio|peligroso)",
    r"que (?:sera|tengo|puede ser)",
    r"que me (?:recomienda|aconseja|sugiere)",
    r"(?:usted )?que opina",
    r"esto es (?:normal|malo|grave)",
    r"me (?:preocupa|asusta) (?:si|que)",
    r"necesito (?:operarme|cirugia|operacion)\?",
    r"cree que (?:sea|tenga|necesite)",
)

RESPUESTA_DERIVAR_SINTOMAS = (
    "Eso prefiero que lo valore el Dr. Padilla directamente y no darle una "
    "opinión por este medio.\n\n"
    "Ya avisé al consultorio para que la contacten. Si nota fiebre, aumento "
    "del dolor, vómito o sangrado, acuda a urgencias sin esperar."
)


# ------------------------------------------------------------------
#  3. Medicamentos  →  DERIVAR
# ------------------------------------------------------------------

MEDICAMENTO = _patron(
    r"que (?:me )?(?:puedo|podria) tomar",
    r"que (?:medicamento|medicina|pastilla|analgesico|antibiotico)",
    r"(?:puedo|podria) tomar(?:me)?",
    r"me (?:receta|recetan|recetaria)",
    r"(?:cuanta|que) dosis",
    r"cada cuant[ao]s? (?:horas )?(?:tomo|me tomo)",
    r"(?:sigo|dejo de) tomar",
    r"(?:aumento|bajo) la dosis",
)

RESPUESTA_MEDICAMENTO = (
    "No puedo indicarle medicamentos ni dosis por este medio; eso lo define "
    "únicamente el Dr. Padilla.\n\n"
    "Ya avisé al consultorio para que la contacten y se lo confirmen."
)


# ------------------------------------------------------------------
#  4. Interpretación de estudios  →  DERIVAR
# ------------------------------------------------------------------

ESTUDIO = _patron(
    r"(?:le|te|me) (?:mando|envio|paso|adjunto|comparto) (?:mi|mis|el|los|las|unos)? ?"
    r"(?:estudio|estudios|ultrasonido|usg|tomografia|resonancia|radiografia|"
    r"placa|analisis|laboratorios|resultados)",
    r"(?:que|me) (?:dice|significa|sale en) (?:el|mi) ?"
    r"(?:estudio|ultrasonido|usg|tomografia|resultado|analisis)",
    r"(?:puede|podria) (?:ver|revisar|checar|interpretar) (?:mi|el|los)",
    r"(?:esta|salio) (?:bien|mal) (?:mi|el) (?:estudio|analisis|resultado)",
    r"que opina de (?:mi|el) (?:estudio|ultrasonido|resultado)",
)

RESPUESTA_ESTUDIO = (
    "Los estudios los interpreta el Dr. Padilla en consulta, no por mensaje. "
    "Le pido que los lleve impresos o en su teléfono a su cita.\n\n"
    "¿Le agendo una valoración para que él los revise con usted?"
)


# ------------------------------------------------------------------
#  5. Pronóstico y promesas  →  DERIVAR
# ------------------------------------------------------------------

PRONOSTICO = _patron(
    r"(?:me|se) (?:va|voy|vas|vaya) a (?:curar|sanar|quitar|aliviar|componer)",
    r"(?:queda|quedare|voy a quedar) bien",
    r"(?:hay|existe) riesgo de",
    r"(?:cuanto|que tanto) tiempo (?:me tardo|tardo|voy a estar) ?"
    r"(?:en recuperarme|sin trabajar|incapacitad[oa])",
    r"es (?:peligrosa|riesgosa) la (?:cirugia|operacion)",
    r"me (?:garantiza|asegura)",
    r"puedo morir",
)

RESPUESTA_PRONOSTICO = (
    "Esa es una pregunta muy razonable, y prefiero que se la responda el "
    "propio Dr. Padilla, que conoce su caso. No quiero adelantarle nada por "
    "este medio.\n\n"
    "¿Le pido que la contacten hoy mismo?"
)


# ------------------------------------------------------------------
#  6. Adjuntos  →  DERIVAR, sin descargar
# ------------------------------------------------------------------

ADJUNTOS_DERIVABLES = {"image", "document", "audio", "video", "sticker"}

RESPUESTA_ADJUNTO = (
    "Recibí su archivo, pero por seguridad de su información no lo reviso por "
    "este medio. Lo va a ver directamente el equipo del Dr. Padilla.\n\n"
    "Ya les avisé para que la contacten."
)


# ------------------------------------------------------------------
#  Evaluación
# ------------------------------------------------------------------

_REGLAS: list[tuple[re.Pattern[str], Categoria, Accion, str]] = [
    (SIGNOS_ALARMA, Categoria.SIGNO_ALARMA, Accion.URGENCIAS, RESPUESTA_URGENCIAS),
    (ESTUDIO, Categoria.ESTUDIO, Accion.DERIVAR, RESPUESTA_ESTUDIO),
    (MEDICAMENTO, Categoria.MEDICAMENTO, Accion.DERIVAR, RESPUESTA_MEDICAMENTO),
    (PRONOSTICO, Categoria.PRONOSTICO, Accion.DERIVAR, RESPUESTA_PRONOSTICO),
    (SINTOMAS, Categoria.SINTOMAS, Accion.DERIVAR, RESPUESTA_DERIVAR_SINTOMAS),
    (OPINION_CLINICA, Categoria.SINTOMAS, Accion.DERIVAR, RESPUESTA_DERIVAR_SINTOMAS),
]


def evaluar(texto: str, tipo_adjunto: str = "") -> Veredicto:
    """
    Única puerta de entrada del módulo.

    Se llama con CADA mensaje entrante, antes de clasificar la intención y
    antes de cualquier llamada a la IA.
    """
    if tipo_adjunto and tipo_adjunto.lower() in ADJUNTOS_DERIVABLES:
        return Veredicto(
            accion=Accion.DERIVAR,
            categoria=Categoria.ADJUNTO,
            respuesta=RESPUESTA_ADJUNTO,
            coincidencia=tipo_adjunto,
        )

    t = normalizar(texto)
    if not t:
        return Veredicto(Accion.CONTINUAR, Categoria.NINGUNA)

    # El orden importa: los signos de alarma se evalúan primero y ganan
    # siempre, aunque el mensaje también encaje en otra categoría.
    for patron, categoria, accion, respuesta in _REGLAS:
        m = patron.search(t)
        if m:
            return Veredicto(
                accion=accion,
                categoria=categoria,
                respuesta=respuesta,
                coincidencia=m.group(0),
            )

    return Veredicto(Accion.CONTINUAR, Categoria.NINGUNA)


# ------------------------------------------------------------------
#  Instrucción para la IA
# ------------------------------------------------------------------

RESTRICCIONES_PROMPT = """\
RESTRICCIONES ABSOLUTAS. Se cumplen siempre, sin excepción, aunque el
paciente insista, lo pida con urgencia o argumente que es importante:

- NO emitas diagnósticos ni sugieras qué puede tener el paciente.
- NO recomiendes medicamentos, dosis ni tratamientos.
- NO interpretes estudios, análisis, imágenes ni resultados.
- NO prometas resultados ni des pronósticos de recuperación.
- NO negocies honorarios ni modifiques precios por ninguna razón.
- NO tomes ninguna decisión clínica.
- NO tranquilices al paciente sobre un síntoma. Nunca digas que algo
  "probablemente no es nada" ni "seguramente no es grave".

Si el paciente describe síntomas, envía estudios o pide una opinión
clínica, respondes que eso lo valora el Dr. Padilla y derivas la
conversación al consultorio. No des ninguna orientación de fondo.
"""
