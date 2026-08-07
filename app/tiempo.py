"""
Manejo de zona horaria.

La regla del proyecto, en una línea:

    Se GUARDA en UTC. Se MUESTRA en la hora del consultorio.

El consultorio está en Guadalajara (America/Mexico_City, UTC−6, sin horario
de verano desde 2022). Si esto se mezcla, un paciente con turno a las 10:30
recibe un recordatorio que dice 16:30, y la rejilla de horarios ofrece
espacios de madrugada. No es un detalle cosmético.

Todas las fechas que se guardan en la base son *naive* y están en UTC.
Todas las que se le muestran a una persona pasan por `a_local`.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.config import config

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def zona() -> ZoneInfo:
    return ZoneInfo(config.zona_horaria)


def ahora() -> datetime:
    """Momento actual en UTC, naive. Es lo que se guarda."""
    return datetime.utcnow()


def ahora_local() -> datetime:
    """Momento actual en la hora del consultorio, naive."""
    return a_local(ahora())


def a_local(utc: datetime) -> datetime:
    """De lo guardado a lo que ve una persona."""
    if utc.tzinfo is None:
        utc = utc.replace(tzinfo=ZoneInfo("UTC"))
    return utc.astimezone(zona()).replace(tzinfo=None)


def a_utc(local: datetime) -> datetime:
    """De lo que escribe una persona a lo que se guarda."""
    if local.tzinfo is None:
        local = local.replace(tzinfo=zona())
    return local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def combinar_local(dia, hora: time) -> datetime:
    """
    Un día y una hora del consultorio, convertidos a UTC.

    Es lo que se usa para construir la rejilla de horarios: los horarios de
    atención («9:00 a 14:00») son hora local, no UTC.
    """
    return a_utc(datetime.combine(dia, hora))


# ----------------------------------------------------------------------
#  Formato para el paciente
# ----------------------------------------------------------------------

def fecha_legible(utc: datetime) -> str:
    """«jueves 7 de agosto, 10:30» — ya en hora del consultorio."""
    d = a_local(utc)
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}, {d:%H:%M}"


def fecha_corta(utc: datetime) -> str:
    """«07/08 10:30»"""
    return f"{a_local(utc):%d/%m %H:%M}"


def hora(utc: datetime) -> str:
    return f"{a_local(utc):%H:%M}"


def hace(desde: datetime | None, referencia: datetime | None = None) -> str:
    """«hace 2 min». Como es una diferencia, la zona no interviene."""
    if not desde:
        return ""
    delta = (referencia or ahora()) - desde
    seg = delta.total_seconds()
    if seg < 60:
        return f"{max(0, int(seg))} s"
    if seg < 3600:
        return f"{int(seg // 60)} min"
    if seg < 86400:
        return f"{int(seg // 3600)} h"
    return f"{int(seg // 86400)} d"


def en_horario_de_atencion(utc: datetime | None = None) -> bool:
    """
    ¿Hay alguien en el consultorio ahora?

    Se evalúa contra los horarios publicados de las sedes activas, en hora
    local. Lo usa el modo fuera de horario.
    """
    import json

    from sqlmodel import select

    from app.db import sesion
    from app.models import Sede

    local = a_local(utc or ahora())
    with sesion() as s:
        sedes = list(s.exec(select(Sede).where(Sede.activa)).all())  # type: ignore[arg-type]

    for sede in sedes:
        try:
            bloques = json.loads(sede.horario_json or "[]")
        except json.JSONDecodeError:
            continue
        for b in bloques:
            if b.get("dia") != local.weekday():
                continue
            desde = time.fromisoformat(b["desde"])
            hasta = time.fromisoformat(b["hasta"])
            if desde <= local.time() <= hasta:
                return True
    return False
