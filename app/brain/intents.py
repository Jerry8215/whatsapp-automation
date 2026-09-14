"""
Clasificación de intención por reglas.

Cumple dos papeles:

- En MODO BÁSICO es el único clasificador. Costo cero.
- En MODO HÍBRIDO es el filtro barato: si reconoce la intención con
  confianza suficiente, resuelve con flujos y la IA no se invoca. Solo
  lo que no reconoce llega al modelo. De ahí sale el ahorro de ~80%.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.brain.safety import normalizar
from app.models import Intencion

UMBRAL_CONFIANZA = 0.6


@dataclass(frozen=True)
class Clasificacion:
    intencion: Intencion
    confianza: float
    coincidencias: tuple[str, ...] = ()

    @property
    def es_confiable(self) -> bool:
        return self.confianza >= UMBRAL_CONFIANZA


# Cada intención con sus señales. El peso refleja cuán inequívoca es la
# frase: "quiero agendar" no deja lugar a dudas; "cita" sola, sí.
SENALES: dict[Intencion, list[tuple[str, float]]] = {
    Intencion.CITA: [
        (r"\b(?:quiero|quisiera|necesito|me gustaria|puedo) (?:agendar|sacar|hacer|programar|pedir)\b", 1.0),
        (r"\bagendar (?:una )?(?:cita|consulta|valoracion)\b", 1.0),
        (r"\b(?:quiero|quisiera|necesito|ocupo|busco|me gustaria|me (?:da|puede dar|podria dar)) (?:una |un )?(?:cita|consulta|valoracion)\b", 1.0),
        (r"\b(?:tiene|tienen|hay) (?:algun )?(?:espacio|lugar|cupo|disponibilidad)\b", 0.9),
        (r"\bpara cuando (?:hay|tiene|tienen)\b", 0.8),
        (r"\b(?:cita|consulta|valoracion)\b", 0.5),
        (r"\bconsultar (?:con )?el doctor\b", 0.6),
    ],
    Intencion.COSTOS: [
        (r"\bcuanto (?:cuesta|sale|vale|es)\b", 1.0),
        (r"\b(?:cual es el |el )?(?:costo|precio|tarifa|honorarios)\b", 0.9),
        (r"\bque precio\b", 0.9),
        (r"\b(?:aceptan|toman|trabajan con) (?:seguro|aseguradora|gastos medicos)\b", 0.8),
        (r"\b(?:manejan|hay|tienen) (?:pagos|meses sin intereses|financiamiento|facilidades)\b", 0.8),
        (r"\bes caro\b", 0.6),
    ],
    Intencion.UBICACION: [
        (r"\b(?:donde|en donde) (?:esta|estan|queda|se encuentra|los encuentro|atiende)\b", 1.0),
        (r"\b(?:cual es la |la )?direccion\b", 0.9),
        (r"\bcomo (?:llego|llegar)\b", 0.9),
        (r"\b(?:hay|tienen) estacionamiento\b", 0.8),
        (r"\bubicacion\b", 0.8),
        (r"\ben que (?:piso|consultorio|torre)\b", 0.7),
    ],
    Intencion.POSTOPERATORIO: [
        (r"\b(?:ya )?(?:me|lo|la) operaron\b", 0.9),
        (r"\b(?:despues|luego) de (?:mi|la) (?:cirugia|operacion)\b", 0.9),
        (r"\bmi (?:cirugia|operacion) fue\b", 0.8),
        (r"\b(?:cita de |mi )?control (?:postoperatorio|post operatorio)\b", 1.0),
        (r"\b(?:cuando|ya) puedo (?:banarme|manejar|hacer ejercicio|trabajar|cargar)\b", 0.8),
        (r"\b(?:retiro|quitan) (?:de )?(?:puntos|grapas)\b", 0.8),
    ],
    Intencion.CANCELAR: [
        (r"\b(?:quiero|necesito|puedo) cancelar\b", 1.0),
        (r"\bcancelar (?:mi|la) (?:cita|consulta)\b", 1.0),
        (r"\bya no (?:voy a poder|podre|puedo) (?:ir|asistir)\b", 0.9),
        (r"\b(?:cambiar|mover|reprogramar) (?:mi|la) cita\b", 0.9),
        (r"\bno voy a poder llegar\b", 0.8),
    ],
    Intencion.CONFIRMAR: [
        (r"^(?:si|si confirmo|confirmo|confirmado|de acuerdo|ok|okay|va|sale)\.?$", 0.9),
        (r"\bconfirmo (?:mi|la) (?:cita|asistencia)\b", 1.0),
        (r"\bahi (?:estare|nos vemos)\b", 0.8),
    ],
    Intencion.FACTURACION: [
        (r"\b(?:necesito|quiero|me pueden dar) (?:una )?factura\b", 1.0),
        (r"\bfacturacion\b", 0.9),
        (r"\b(?:datos|constancia) (?:de|para) fact\w*\b", 0.9),
        (r"\brfc\b", 0.8),
        (r"\bcomprobante fiscal\b", 0.9),
    ],
    Intencion.REFERENCIA: [
        (r"\bme (?:refirio|mando|recomendo) (?:el|la|un|una) (?:dr|dra|doctor|doctora|medico)\b", 1.0),
        (r"\b(?:traigo|tengo) (?:un|una) (?:pase|referencia|interconsulta)\b", 0.9),
        (r"\bme (?:lo|la) recomendo\b", 0.7),
    ],
    Intencion.INFORMACION: [
        (r"\b(?:que|cuales|cual es el|cuál) (?:son (?:los|las) )?"
         r"(?:horarios?|dias|dias de atencion)\b", 0.9),
        (r"\bhorarios? (?:de atencion|manejan|tienen|hay)\b", 0.9),
        (r"\b(?:a que hora|hasta que hora) (?:abren|cierran|atienden)\b", 0.9),
        (r"\b(?:que dias|cuando) (?:atiende|atienden|consulta)\b", 0.9),
        (r"\b(?:que|cuales) (?:estudios|documentos|papeles) (?:llevo|necesito|debo llevar)\b", 0.9),
        (r"\b(?:que|cual) (?:especialidad|hace|opera) el (?:dr|doctor)\b", 0.8),
        # «¿Qué cirugías realiza?» no coincidía con nada y terminaba en «no
        # le entendí». Es de las primeras preguntas de un paciente nuevo.
        (r"\bque (?:cirugias|operaciones|procedimientos|padecimientos)\b", 0.9),
        (r"\b(?:que|cuales) (?:opera|operan|realiza|realizan|atiende|atienden|trata|tratan)\b", 0.8),
        (r"\b(?:es|son) (?:especialista|cirujano|cirujana)\b", 0.8),
        (r"\b(?:a que|de que) se dedica\b", 0.8),
        (r"\bhace (?:cirugia|operaciones)\b", 0.8),
        (r"\b(?:atiende|atienden) (?:ninos|pediatric)\w*\b", 0.8),
        (r"\bpreparacion (?:previa|para la cirugia)\b", 0.8),
    ],
    # Un saludo puede venir encadenado ("hola, buenos días doctor") o con
    # signos de puntuación. Lo que NO puede es traer otra intención pegada:
    # "hola, quiero agendar" debe clasificar como CITA, y así ocurre porque
    # esa señal pesa 1.0 y gana.
    Intencion.SALUDO: [
        (r"^(?:hol+a+|buenas|buen dia|buenos dias|buenas tardes|buenas noches|"
         r"que tal|saludos|disculpe|buenas tardes doctor)"
         r"(?:[\s,;!.]+(?:hol+a+|buenas|buen dia|buenos dias|buenas tardes|"
         r"buenas noches|que tal|doctor|doctora|dr|dra|padilla))*"
         r"[\s!.,¿?]*$", 1.0),
        (r"^(?:hola|buenas)\b", 0.4),
    ],
}

_COMPILADAS: dict[Intencion, list[tuple[re.Pattern[str], float]]] = {
    intencion: [(re.compile(p), peso) for p, peso in senales]
    for intencion, senales in SENALES.items()
}


def clasificar(texto: str) -> Clasificacion:
    """Devuelve la intención más probable y qué tan segura es."""
    t = normalizar(texto)
    if not t:
        return Clasificacion(Intencion.DESCONOCIDA, 0.0)

    mejor = Intencion.DESCONOCIDA
    mejor_peso = 0.0
    mejor_coincidencias: tuple[str, ...] = ()

    for intencion, patrones in _COMPILADAS.items():
        peso = 0.0
        encontradas: list[str] = []
        for patron, p in patrones:
            m = patron.search(t)
            if m:
                peso = max(peso, p)
                encontradas.append(m.group(0))
        if peso > mejor_peso:
            mejor, mejor_peso, mejor_coincidencias = intencion, peso, tuple(encontradas)

    # Un saludo con algo pegado detrás ("hola, los encontré en Doctoralia")
    # sigue siendo un saludo, siempre que no traiga otra intención más
    # fuerte. Sin esto, un primer mensaje amable se trataba como
    # incomprensible y terminaba en la bandeja de la asistente.
    if mejor_peso < UMBRAL_CONFIANZA and _EMPIEZA_SALUDANDO.match(t):
        return Clasificacion(Intencion.SALUDO, 0.7, ("saludo inicial",))

    return Clasificacion(mejor, mejor_peso, mejor_coincidencias)


_EMPIEZA_SALUDANDO = re.compile(
    r"^(?:hol+a+|buenas|buen dia|buenos dias|buenas tardes|buenas noches|"
    r"que tal|saludos|disculpe|con permiso)\b"
)


def detectar_fuente(texto: str) -> str:
    """De dónde llegó el paciente, cuando lo menciona espontáneamente."""
    t = normalizar(texto)
    tabla = {
        "google": r"\bgoogle\b|\bbusque en internet\b|\ben internet\b",
        "facebook": r"\bfacebook\b|\bfb\b",
        "instagram": r"\binstagram\b|\big\b",
        "doctoralia": r"\bdoctoralia\b",
        "web": r"\b(?:su |la )?pagina(?: web)?\b|\bsitio web\b",
        "recomendacion": r"\bme (?:recomendo|refirio|mando)\b|\bpor recomendacion\b|\bun conocido\b",
    }
    for fuente, patron in tabla.items():
        if re.search(patron, t):
            return fuente
    return ""
