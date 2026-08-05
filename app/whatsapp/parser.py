"""
Normaliza lo que manda Meta a una forma manejable.

La carga del webhook viene muy anidada y cambia de forma según el tipo de
mensaje. Todo eso se aplana acá para que el resto del sistema no tenga que
saber cómo es el JSON de Meta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MensajeEntrante:
    wa_message_id: str
    telefono: str
    nombre_perfil: str = ""
    texto: str = ""
    tipo: str = "text"
    tipo_adjunto: str = ""
    respuesta_id: str = ""     # id del botón o de la opción de lista elegida
    marca_tiempo: int = 0
    crudo: dict[str, Any] = field(default_factory=dict)

    @property
    def es_adjunto(self) -> bool:
        return bool(self.tipo_adjunto)


@dataclass
class EstadoEntrega:
    """Acuse de entrega/lectura, o error de envío."""

    wa_message_id: str
    estado: str            # sent | delivered | read | failed
    telefono: str = ""
    error: str = ""


TIPOS_ADJUNTO = {"image", "document", "audio", "video", "sticker"}


def extraer(carga: dict[str, Any]) -> tuple[list[MensajeEntrante], list[EstadoEntrega]]:
    """Devuelve (mensajes, estados) de una carga del webhook."""
    mensajes: list[MensajeEntrante] = []
    estados: list[EstadoEntrega] = []

    for entrada in carga.get("entry", []):
        for cambio in entrada.get("changes", []):
            valor = cambio.get("value", {})

            perfiles = {
                c.get("wa_id", ""): c.get("profile", {}).get("name", "")
                for c in valor.get("contacts", [])
            }

            for m in valor.get("messages", []):
                mensajes.append(_mensaje(m, perfiles))

            for s in valor.get("statuses", []):
                estados.append(EstadoEntrega(
                    wa_message_id=s.get("id", ""),
                    estado=s.get("status", ""),
                    telefono=s.get("recipient_id", ""),
                    error="; ".join(
                        e.get("title", "") for e in s.get("errors", [])
                    ),
                ))

    return mensajes, estados


def _mensaje(m: dict[str, Any], perfiles: dict[str, str]) -> MensajeEntrante:
    telefono = m.get("from", "")
    tipo = m.get("type", "text")

    entrante = MensajeEntrante(
        wa_message_id=m.get("id", ""),
        telefono=telefono,
        nombre_perfil=perfiles.get(telefono, ""),
        tipo=tipo,
        marca_tiempo=int(m.get("timestamp", 0) or 0),
        crudo=m,
    )

    if tipo == "text":
        entrante.texto = m.get("text", {}).get("body", "")

    elif tipo == "interactive":
        inter = m.get("interactive", {})
        if "button_reply" in inter:
            entrante.respuesta_id = inter["button_reply"].get("id", "")
            entrante.texto = inter["button_reply"].get("title", "")
        elif "list_reply" in inter:
            entrante.respuesta_id = inter["list_reply"].get("id", "")
            entrante.texto = inter["list_reply"].get("title", "")

    elif tipo == "button":
        entrante.texto = m.get("button", {}).get("text", "")
        entrante.respuesta_id = m.get("button", {}).get("payload", "")

    elif tipo in TIPOS_ADJUNTO:
        # No se descarga el archivo. Solo se registra que llegó, para
        # derivar la conversación a una persona (ver brain/safety.py).
        entrante.tipo_adjunto = tipo
        entrante.texto = m.get(tipo, {}).get("caption", "")

    elif tipo == "location":
        loc = m.get("location", {})
        entrante.texto = f"[ubicación] {loc.get('name', '')} {loc.get('address', '')}".strip()

    return entrante
