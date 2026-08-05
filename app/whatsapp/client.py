"""
Cliente de la Cloud API.

Dos formas de enviar:

- `enviar_texto`  — solo válido dentro de la ventana de 24 horas que abre
                    el paciente al escribir. Es gratuito.
- `enviar_plantilla` — para iniciar la conversación nosotros (recordatorios).
                    Requiere plantilla aprobada por Meta y sí tiene costo.

Usar texto libre fuera de la ventana de 24 h falla, y hacerlo de forma
repetida afecta la calificación de calidad del número.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import config

log = logging.getLogger(__name__)

TIEMPO_ESPERA = 20.0


class ErrorWhatsApp(RuntimeError):
    pass


def _url() -> str:
    return f"{config.wa_api_base}/{config.wa_phone_number_id}/messages"


def _cabeceras() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.wa_token}",
        "Content-Type": "application/json",
    }


async def _publicar(carga: dict[str, Any]) -> dict[str, Any]:
    if not config.wa_token or not config.wa_phone_number_id:
        log.warning("WhatsApp sin configurar; mensaje no enviado: %s", carga)
        return {"simulado": True}

    async with httpx.AsyncClient(timeout=TIEMPO_ESPERA) as cliente:
        r = await cliente.post(_url(), headers=_cabeceras(), json=carga)

    if r.status_code >= 400:
        log.error("Error de la Cloud API %s: %s", r.status_code, r.text)
        raise ErrorWhatsApp(f"{r.status_code}: {r.text}")

    return r.json()


async def enviar_texto(telefono: str, texto: str) -> dict[str, Any]:
    """Respuesta dentro de la ventana de 24 h. Sin costo."""
    return await _publicar({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": telefono,
        "type": "text",
        "text": {"preview_url": False, "body": texto[:4096]},
    })


async def enviar_botones(
    telefono: str, texto: str, botones: list[tuple[str, str]]
) -> dict[str, Any]:
    """Hasta 3 botones de respuesta rápida: [(id, título)]."""
    return await _publicar({
        "messaging_product": "whatsapp",
        "to": telefono,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": texto[:1024]},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": bid, "title": titulo[:20]}}
                    for bid, titulo in botones[:3]
                ]
            },
        },
    })


async def enviar_lista(
    telefono: str, texto: str, boton: str, opciones: list[tuple[str, str, str]]
) -> dict[str, Any]:
    """Lista desplegable: [(id, título, descripción)]. Hasta 10 opciones."""
    return await _publicar({
        "messaging_product": "whatsapp",
        "to": telefono,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": texto[:1024]},
            "action": {
                "button": boton[:20],
                "sections": [{
                    "title": "Opciones",
                    "rows": [
                        {"id": oid, "title": t[:24], "description": d[:72]}
                        for oid, t, d in opciones[:10]
                    ],
                }],
            },
        },
    })


async def enviar_ubicacion(
    telefono: str, lat: float, lon: float, nombre: str, direccion: str
) -> dict[str, Any]:
    return await _publicar({
        "messaging_product": "whatsapp",
        "to": telefono,
        "type": "location",
        "location": {
            "latitude": lat,
            "longitude": lon,
            "name": nombre,
            "address": direccion,
        },
    })


async def enviar_plantilla(
    telefono: str,
    nombre_plantilla: str,
    parametros: list[str],
    idioma: str = "es_MX",
) -> dict[str, Any]:
    """
    Mensaje que iniciamos nosotros: recordatorios y confirmaciones.
    La plantilla debe estar aprobada por Meta previamente.
    """
    return await _publicar({
        "messaging_product": "whatsapp",
        "to": telefono,
        "type": "template",
        "template": {
            "name": nombre_plantilla,
            "language": {"code": idioma},
            "components": [{
                "type": "body",
                "parameters": [{"type": "text", "text": p} for p in parametros],
            }],
        },
    })


async def marcar_leido(wa_message_id: str) -> dict[str, Any]:
    return await _publicar({
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": wa_message_id,
    })
