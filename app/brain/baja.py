"""
Baja: el paciente pide que no le escribamos más.

En el primer contacto se le promete por escrito: «Si prefiere que no le
escribamos, responda BAJA en cualquier momento». Esa frase es parte del
aviso de consentimiento, así que no es una cortesía: es lo que hace que el
consentimiento sea válido bajo la LFPDPPP.

Hasta que existió este módulo la promesa no se cumplía. Un paciente que
escribía BAJA recibía «no le entendí», se le pedía que repitiera, y
terminaba en la bandeja de la asistente. Peor todavía: los recordatorios
le seguían llegando.

Qué hace la baja y qué no:

  * **Deja de escribirle el consultorio.** No sale ningún recordatorio ni
    ninguna plantilla hacia ese número. Es lo que se le prometió.
  * **No lo deja sin atención.** Si el paciente vuelve a escribir, el
    asistente le responde: fue él quien inició el contacto. Callarle sería
    castigarlo por ejercer un derecho.
  * **No borra sus datos.** Eso es un derecho distinto —la supresión— y se
    tramita desde el panel, no por un mensaje de WhatsApp.

Se puede revertir escribiendo ALTA, y así se le dice.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from app.brain.safety import normalizar

log = logging.getLogger(__name__)

#: «BAJA» a secas, o la frase completa. Se exige que el mensaje sea
#: prácticamente solo eso: «me dieron de baja del seguro» o «ya bajé de
#: peso» no son pedidos de baja, y darlos por tales dejaría al paciente sin
#: recordatorios sin que él lo pidiera.
_BAJA = re.compile(
    r"^(?:"
    r"baja|darme de baja|dar de baja|me doy de baja|quiero (?:la )?baja|"
    r"stop|unsubscribe|"
    # «no quiero recibir más», «ya no me manden mensajes», y las combinaciones
    # de esas mismas palabras. Cualquier otra cosa detrás —«no quiero ir el
    # jueves»— no coincide, que es justamente lo que se busca.
    r"(?:ya )?no (?:quiero|deseo|me manden|me envien|me escriban)"
    r"(?:\s+(?:mas|recibir|que|me|nada|mensajes|recordatorios|publicidad|"
    r"escriban|manden|envien|escribir))*"
    r")[\s.!]*$"
)

_ALTA = re.compile(
    r"^(?:alta|darme de alta|quiero (?:volver|recibir)|"
    r"si quiero (?:recibir|mensajes|recordatorios))[\s.!]*$"
)

CONFIRMACION_BAJA = (
    "Listo. No volveremos a enviarle mensajes ni recordatorios desde este "
    "número.\n\n"
    "Sus citas ya agendadas siguen en pie; simplemente no le recordaremos. "
    "Si en algún momento quiere volver a recibirlos, responda ALTA.\n\n"
    "Si necesita algo del consultorio, puede escribirnos cuando quiera."
)

CONFIRMACION_ALTA = (
    "Listo, volvió a quedar activo. Le enviaremos el recordatorio de sus "
    "citas como antes.\n\n¿En qué le puedo ayudar?"
)


def pide_baja(texto: str) -> bool:
    return bool(_BAJA.match(normalizar(texto)))


def pide_alta(texto: str) -> bool:
    return bool(_ALTA.match(normalizar(texto)))


def dar_de_baja(paciente_id: int) -> str:
    """Registra la baja. Devuelve el nombre, para el aviso al consultorio."""
    return _marcar(paciente_id, datetime.utcnow())


def dar_de_alta(paciente_id: int) -> str:
    return _marcar(paciente_id, None)


def _marcar(paciente_id: int, cuando: datetime | None) -> str:
    from app.db import sesion
    from app.models import Paciente, RegistroAuditoria

    with sesion() as s:
        paciente = s.get(Paciente, paciente_id)
        if not paciente:
            return ""
        paciente.baja_en = cuando
        s.add(paciente)
        s.add(RegistroAuditoria(
            actor="paciente",
            accion="paciente.baja" if cuando else "paciente.alta",
            entidad="paciente",
            entidad_id=paciente_id,
            detalle=paciente.telefono,
        ))
        s.commit()
        return paciente.nombre or paciente.telefono


def esta_de_baja(paciente_id: int | None) -> bool:
    """¿Este paciente pidió que no le escribamos?"""
    if paciente_id is None:
        return False
    from app.db import sesion
    from app.models import Paciente

    with sesion() as s:
        paciente = s.get(Paciente, paciente_id)
    return bool(paciente and paciente.baja_en)
