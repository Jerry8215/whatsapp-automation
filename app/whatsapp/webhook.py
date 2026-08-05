"""
Endpoints del webhook de Meta.

Dos reglas operativas:

1. Se responde 200 SIEMPRE y de inmediato. Si tardamos o devolvemos error,
   Meta reintenta y el paciente recibe respuestas duplicadas.
2. El procesamiento va en segundo plano, después de responder.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Header, Request, Response

from app.security import firma_valida, verificacion_webhook
from app.whatsapp.parser import extraer

log = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["whatsapp"])


@router.get("")
async def verificar(request: Request) -> Response:
    """Apretón de manos que Meta hace al registrar la URL."""
    p = request.query_params
    if verificacion_webhook(p.get("hub.mode"), p.get("hub.verify_token")):
        log.info("Webhook verificado por Meta")
        return Response(content=p.get("hub.challenge", ""), media_type="text/plain")

    log.warning("Verificación de webhook rechazada")
    return Response(status_code=403, content="token inválido")


@router.post("")
async def recibir(
    request: Request,
    tareas: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None),
) -> Response:
    cuerpo = await request.body()

    if not firma_valida(cuerpo, x_hub_signature_256):
        log.warning("Firma inválida en el webhook — carga descartada")
        return Response(status_code=403, content="firma inválida")

    try:
        carga = await request.json()
    except Exception:
        log.exception("Carga del webhook ilegible")
        return Response(status_code=200)

    mensajes, estados = extraer(carga)

    # Importación diferida: evita un ciclo de importaciones y mantiene
    # liviano el arranque del webhook.
    from app.brain.router import procesar_mensaje, registrar_estado

    for m in mensajes:
        tareas.add_task(procesar_mensaje, m)
    for e in estados:
        tareas.add_task(registrar_estado, e)

    return Response(status_code=200)
