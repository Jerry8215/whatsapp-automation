"""Aplicación. `uvicorn app.main:aplicacion --reload`"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path

from app.config import config
from app.db import crear_tablas
from app.whatsapp.webhook import router as webhook_router

logging.basicConfig(
    level=logging.INFO if config.entorno == "produccion" else logging.DEBUG,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
)
log = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def ciclo_vida(app: FastAPI):
    crear_tablas()
    log.info("Base de datos lista")
    log.info("Entorno: %s · agenda: %s · modo: %s",
             config.entorno, config.agenda_proveedor, config.modo_asistente)
    if config.entorno == "produccion" and not config.wa_app_secret:
        log.error("SIN WA_APP_SECRET EN PRODUCCIÓN: el webhook rechazará todo")
    yield
    log.info("Servicio detenido")


aplicacion = FastAPI(
    title="Asistente WhatsApp — Consultorio Dr. Padilla",
    version="0.1.0",
    lifespan=ciclo_vida,
    docs_url="/docs" if config.entorno != "produccion" else None,
)

aplicacion.include_router(webhook_router)


@aplicacion.get("/salud", tags=["sistema"])
async def salud() -> JSONResponse:
    from app.brain.ai import consumo_del_mes, tope_alcanzado

    consumo = consumo_del_mes()
    return JSONResponse({
        "estado": "ok",
        "entorno": config.entorno,
        "agenda": config.agenda_proveedor,
        "modo": "basico" if tope_alcanzado() else config.modo_asistente,
        "ia": {
            "gasto_usd": round(consumo.costo_usd, 4),
            "limite_usd": config.ia_limite_mensual_usd,
            "tope_alcanzado": tope_alcanzado(),
        },
    })


@aplicacion.get("/", include_in_schema=False, response_model=None)
async def maqueta() -> FileResponse | JSONResponse:
    """Maqueta del panel aprobada por el consultorio. El panel real va en el Hito 3."""
    archivo = RAIZ / "panel-asistente-dr-padilla.html"
    if archivo.exists():
        return FileResponse(archivo)
    return JSONResponse({"servicio": "asistente-whatsapp", "estado": "ok"})
