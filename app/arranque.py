"""
Preparación previa al arranque.  `python -m app.arranque`

La ejecuta el Procfile antes de levantar el servidor: crea las tablas y
siembra los datos iniciales si la base está vacía. Es seguro repetirla en
cada despliegue — no pisa nada de lo que ya haya.
"""

from __future__ import annotations

import logging
import sys

from sqlmodel import select

from app.config import config
from app.db import crear_tablas, sesion

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
log = logging.getLogger("arranque")


def main() -> int:
    log.info("Entorno: %s · agenda: %s", config.entorno, config.agenda_proveedor)

    crear_tablas()
    log.info("Tablas listas")

    from app.models import Sede, Usuario

    with sesion() as s:
        hay_sedes = s.exec(select(Sede)).first() is not None
        hay_usuarios = s.exec(select(Usuario)).first() is not None

    if not hay_sedes or not hay_usuarios:
        from app.seed import sembrar

        log.info("Base vacía: sembrando datos iniciales")
        sembrar()
    else:
        log.info("La base ya tiene datos; no se siembra nada")

    # Avisos que conviene ver en el registro del despliegue, no descubrir
    # cuando un paciente escriba.
    if config.entorno == "produccion":
        if not config.wa_app_secret:
            log.error("SIN WA_APP_SECRET: el webhook va a rechazar todo")
        if config.panel_secreto in ("cambiar-esto", ""):
            log.error("PANEL_SECRETO sin definir: las sesiones son falsificables")
        if config.url_base_datos.startswith("sqlite"):
            log.warning(
                "Base SQLite en producción: se pierde en cada despliegue. "
                "Usar PostgreSQL."
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
