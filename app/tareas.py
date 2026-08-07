"""
Tareas programadas.

Arrancan con la aplicación. Todas están pensadas para poder ejecutarse dos
veces sin causar daño: si el servicio se reinicia a mitad de una ronda, la
siguiente retoma sin duplicar nada.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import config

log = logging.getLogger(__name__)

_programador: AsyncIOScheduler | None = None


async def _recordatorios() -> None:
    from app.recordatorios import enviar_pendientes

    try:
        await enviar_pendientes()
    except Exception:
        log.exception("Falló la ronda de recordatorios")


async def _mantenimiento() -> None:
    from app.recordatorios import cerrar_conversaciones_inactivas, marcar_ausencias

    try:
        cerradas = await cerrar_conversaciones_inactivas()
        vencidas = await marcar_ausencias()
        if cerradas or vencidas:
            log.info("Mantenimiento: %s conversaciones, %s citas", cerradas, vencidas)
    except Exception:
        log.exception("Falló el mantenimiento")


async def _retencion() -> None:
    from app.recordatorios import depurar_historiales

    try:
        await depurar_historiales()
    except Exception:
        log.exception("Falló la depuración por retención")


def iniciar() -> AsyncIOScheduler:
    global _programador
    if _programador:
        return _programador

    _programador = AsyncIOScheduler(timezone=config.zona_horaria)

    # Cada 15 minutos alcanza: el recordatorio es de 24 horas antes, así que
    # un cuarto de hora de imprecisión no cambia nada, y evita golpear la
    # API de Meta sin necesidad.
    _programador.add_job(
        _recordatorios, IntervalTrigger(minutes=15),
        id="recordatorios", replace_existing=True, max_instances=1,
    )

    _programador.add_job(
        _mantenimiento, IntervalTrigger(hours=1),
        id="mantenimiento", replace_existing=True, max_instances=1,
    )

    # De madrugada, cuando no hay pacientes escribiendo.
    _programador.add_job(
        _retencion, CronTrigger(hour=4, minute=30),
        id="retencion", replace_existing=True, max_instances=1,
    )

    _programador.start()
    log.info(
        "Tareas programadas: recordatorios cada 15 min · mantenimiento cada "
        "hora · retención a las 04:30"
    )
    return _programador


def detener() -> None:
    global _programador
    if _programador:
        _programador.shutdown(wait=False)
        _programador = None
