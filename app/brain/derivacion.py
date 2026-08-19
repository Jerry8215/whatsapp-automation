"""
Derivación a otro profesional.

El caso concreto que planteó el consultorio: hoy una sola asistente lleva la
agenda del Dr. Padilla y la de su esposa desde el mismo número. Al separar
las agendas, el número actual queda solo para él — pero los pacientes que ya
lo tienen guardado van a seguir escribiendo ahí para pedir cita con ella.

Sin esto, esos pacientes terminarían agendados con el médico equivocado, o
la conversación caería en la bandeja de la asistente una y otra vez por el
mismo motivo.

Lo que hace: reconoce que el paciente busca a otro profesional y le pasa el
número correcto, con el nombre de a quién está escribiendo. Nada más. No
agenda, no promete horarios, no reenvía el mensaje: pasar mensajes de un
número a otro sin que el paciente lo sepa es peor que decirle a dónde ir.

**Por qué no lo resuelve la IA.** Porque tiene que funcionar igual en modo
básico, cuando no hay IA, y porque mandar mal un número es un error que el
paciente paga con un viaje perdido. Es una regla, no una interpretación.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlmodel import select

from app.brain.safety import normalizar
from app.db import sesion
from app.models import Profesional


@dataclass(frozen=True)
class Derivacion:
    profesional_id: int
    nombre: str
    telefono: str
    texto: str


#: Señales de que el paciente quiere algo DE esa persona, y no solo la
#: mencionó al pasar. «La doctora me recomendó operarme» no es un pedido de
#: cita con ella; «quiero cita con la doctora» sí.
_CONTEXTO = re.compile(
    r"\b(?:cita|citas|consulta|consultar|agendar|agenda|turno|espacio|cupo|"
    r"valoracion|atiende|atienden|horario|horarios|cuanto cuesta|costo|precio|"
    r"numero|telefono|contacto|hablar|comunicar|ver a|con la|con el)\b"
)


def profesionales_que_derivan() -> list[Profesional]:
    with sesion() as s:
        return list(s.exec(
            select(Profesional)
            .where(Profesional.deriva, Profesional.activo)  # type: ignore[arg-type]
            .order_by(Profesional.orden)  # type: ignore[arg-type]
        ).all())


def detectar(texto: str, *, intencion_de_cita: bool = False) -> Derivacion | None:
    """
    ¿El paciente está buscando a otro profesional?

    Devuelve None cuando no hay nada que derivar, que es el caso normal.

    Se exige que además del nombre aparezca un contexto de consulta, o que
    la intención ya venga clasificada como cita. Sin eso, mencionar a la
    doctora en una frase cualquiera desviaría al paciente sin motivo — y un
    paciente desviado por error es un paciente perdido.
    """
    candidatos = profesionales_que_derivan()
    if not candidatos:
        return None

    t = normalizar(texto)
    if not t:
        return None

    hay_contexto = intencion_de_cita or bool(_CONTEXTO.search(t))
    if not hay_contexto:
        return None

    for profesional in candidatos:
        if _lo_nombra(t, profesional):
            return Derivacion(
                profesional_id=profesional.id,  # type: ignore[arg-type]
                nombre=profesional.nombre_completo,
                telefono=profesional.telefono_whatsapp,
                texto=mensaje(profesional),
            )
    return None


def _lo_nombra(texto_normalizado: str, profesional: Profesional) -> bool:
    """
    ¿El mensaje nombra a este profesional?

    Se compara con palabra completa: sin eso, una clave corta como «ana»
    coincidiría dentro de «mañana» y desviaría a medio consultorio.
    """
    claves = [
        c.strip() for c in
        (profesional.palabras_clave or "").split(",")
        if c.strip()
    ]
    # El apellido siempre cuenta, aunque no lo hayan cargado como clave.
    partes = profesional.nombre.split()
    if partes:
        claves.append(partes[-1])
        claves.append(profesional.nombre)

    for clave in claves:
        c = normalizar(clave)
        if not c:
            continue
        if re.search(rf"(?<!\w){re.escape(c)}(?!\w)", texto_normalizado):
            return True
    return False


def mensaje(profesional: Profesional) -> str:
    """
    Lo que se le responde al paciente.

    Se dice con quién está hablando antes de pasarle el número: un número
    suelto, sin explicación, parece que lo están sacando de encima.
    """
    if profesional.mensaje_derivacion:
        return profesional.mensaje_derivacion

    nombre = profesional.nombre_completo
    especialidad = f" ({profesional.especialidad})" if profesional.especialidad else ""

    if not profesional.telefono_whatsapp:
        # Configuración incompleta. Antes que dar un número inventado, se
        # deriva a una persona — el router se encarga.
        return (
            f"Las citas con {nombre}{especialidad} se atienden por otra vía. "
            f"Permítame comunicarla con el consultorio para pasarle el contacto."
        )

    return (
        f"Con gusto le ayudo. Este número atiende la agenda del Dr. José "
        f"Guadalupe Padilla.\n\n"
        f"Para {nombre}{especialidad} la agenda se lleva por otro número:\n"
        f"📱 {profesional.telefono_whatsapp}\n\n"
        f"Escríbale por ahí y la atienden directamente. Si además necesita "
        f"algo con el Dr. Padilla, con gusto se lo veo yo por aquí."
    )


def configuracion_incompleta(derivacion: Derivacion) -> bool:
    """Sin número que dar, esto tiene que llegar a una persona."""
    return not derivacion.telefono
