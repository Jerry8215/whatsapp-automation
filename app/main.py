"""Aplicación. `uvicorn app.main:aplicacion --reload`"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pathlib import Path

from app.config import config
from app.db import crear_tablas
from app.panel.api import router as panel_router
from app.panel.contenido import router as contenido_router
from app.whatsapp.webhook import router as webhook_router

logging.basicConfig(
    level=logging.INFO if config.entorno == "produccion" else logging.DEBUG,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
)
log = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def ciclo_vida(app: FastAPI):
    from app import tareas

    crear_tablas()
    log.info("Base de datos lista")
    log.info("Entorno: %s · agenda: %s · modo: %s",
             config.entorno, config.agenda_proveedor, config.modo_asistente)
    if config.entorno == "produccion" and not config.wa_app_secret:
        log.error("SIN WA_APP_SECRET EN PRODUCCIÓN: el webhook rechazará todo")

    tareas.iniciar()
    yield
    tareas.detener()
    log.info("Servicio detenido")


aplicacion = FastAPI(
    title="Asistente WhatsApp — Consultorio Dr. Padilla",
    version="0.1.0",
    lifespan=ciclo_vida,
    docs_url="/docs" if config.entorno != "produccion" else None,
)

aplicacion.include_router(webhook_router)
aplicacion.include_router(panel_router)
aplicacion.include_router(contenido_router)

# Diagnóstico: consulta el estado de la configuración de Meta desde el
# servidor, sin necesidad de entrar a la consola. Solo para el administrador.
from app.diagnostico import router as diagnostico_router  # noqa: E402

aplicacion.include_router(diagnostico_router)

# Simulador. En producción queda detrás de la sesión del panel: sirve para
# que el consultorio pruebe el asistente antes de que Meta esté configurado,
# que es justo cuando más falta hace.
from app.simulador import router as simulador_router  # noqa: E402

aplicacion.include_router(simulador_router)
log.info("Simulador disponible en /simulador")

ESTATICOS = Path(__file__).resolve().parent / "panel" / "static"
PANEL = ESTATICOS / "panel.html"


# ----------------------------------------------------------------------
#  App instalable en el celular
#
#  El consultorio agrega el panel a la pantalla de inicio y le queda un
#  ícono como cualquier otra app, a pantalla completa. Los tres archivos
#  van en la raíz a propósito: el service worker solo puede controlar
#  páginas que estén por debajo de su propia ruta, y desde /panel/sw.js no
#  alcanzaría a la raíz del sitio.
# ----------------------------------------------------------------------

@aplicacion.get("/manifest.webmanifest", include_in_schema=False)
async def manifiesto() -> FileResponse:
    return FileResponse(
        ESTATICOS / "manifest.webmanifest",
        media_type="application/manifest+json",
    )


@aplicacion.get("/sw.js", include_in_schema=False)
async def service_worker() -> FileResponse:
    return FileResponse(
        ESTATICOS / "sw.js",
        media_type="application/javascript",
        # Sin esto el navegador puede quedarse con un service worker viejo
        # y el panel no se actualiza nunca.
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


@aplicacion.get("/iconos/{nombre}", include_in_schema=False)
async def icono(nombre: str) -> FileResponse:
    archivo = (ESTATICOS / "iconos" / nombre).resolve()
    if archivo.parent != (ESTATICOS / "iconos").resolve() or not archivo.is_file():
        raise HTTPException(status_code=404, detail="No existe")
    return FileResponse(archivo, media_type="image/png")


@aplicacion.get("/apple-touch-icon.png", include_in_schema=False)
@aplicacion.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
async def icono_apple() -> FileResponse:
    """iOS lo busca en la raíz, sin preguntarle al manifiesto."""
    return FileResponse(ESTATICOS / "iconos" / "apple-touch-icon.png",
                        media_type="image/png")


@aplicacion.get("/panel", include_in_schema=False)
@aplicacion.get("/panel/{ruta:path}", include_in_schema=False)
async def panel(ruta: str = "") -> FileResponse:
    """
    El panel es una sola página. Cualquier ruta bajo /panel la sirve, y el
    enrutado ocurre del lado del navegador — así un enlace de aviso como
    /panel/conversaciones/12 abre directo sin dar 404.
    """
    return FileResponse(PANEL)


@aplicacion.get("/salud", tags=["sistema"])
async def salud() -> JSONResponse:
    from app.brain.ai import consumo_del_mes, tope_alcanzado

    consumo = consumo_del_mes()

    # `configurada` existe porque su ausencia es un fallo silencioso: sin
    # clave el asistente sigue contestando, pero solo con los flujos, y
    # desde afuera parece que funciona bien. Se ve acá y en el panel.
    configurada = bool(config.openai_api_key)
    efectivo = (
        "basico" if (tope_alcanzado() or not configurada)
        else config.modo_asistente
    )

    return JSONResponse({
        "estado": "ok",
        "entorno": config.entorno,
        "agenda": config.agenda_proveedor,
        "modo": efectivo,
        "modo_configurado": config.modo_asistente,
        "ia": {
            "configurada": configurada,
            "modelo": config.openai_model if configurada else "",
            "gasto_usd": round(consumo.costo_usd, 4),
            "limite_usd": config.ia_limite_mensual_usd,
            "tope_alcanzado": tope_alcanzado(),
        },
    })


@aplicacion.get("/", include_in_schema=False)
async def raiz() -> RedirectResponse:
    return RedirectResponse("/panel")


@aplicacion.get("/maqueta", include_in_schema=False, response_model=None)
async def maqueta() -> FileResponse | JSONResponse:
    """Maqueta aprobada por el consultorio. Se conserva como referencia visual."""
    archivo = RAIZ / "panel-asistente-dr-padilla.html"
    if archivo.exists():
        return FileResponse(archivo)
    return JSONResponse({"servicio": "asistente-whatsapp", "estado": "ok"})
