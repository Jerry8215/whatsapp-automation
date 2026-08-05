"""
Verificación de la firma de Meta y utilidades de acceso.

Sin la validación de firma, cualquiera que conozca la URL del webhook
podría inyectar mensajes falsos y hacer que el asistente responda o
agende citas. No es opcional.
"""

from __future__ import annotations

import hashlib
import hmac

import bcrypt

from app.config import config

#: bcrypt ignora todo lo que pase de 72 bytes. Se trunca de forma
#: explícita para que cifrar y verificar coincidan siempre.
_MAX_BYTES = 72


def firma_valida(cuerpo: bytes, cabecera: str | None) -> bool:
    """
    Compara el HMAC-SHA256 del cuerpo crudo contra X-Hub-Signature-256.

    Importante: se usa el cuerpo TAL CUAL llegó. Si se serializa de nuevo
    el JSON, la firma deja de coincidir.
    """
    if not config.wa_app_secret:
        # En desarrollo se permite trabajar sin secreto configurado.
        # En producción esto es un fallo duro.
        if config.entorno == "produccion":
            return False
        return True

    if not cabecera or not cabecera.startswith("sha256="):
        return False

    esperada = hmac.new(
        config.wa_app_secret.encode("utf-8"), cuerpo, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(esperada, cabecera.removeprefix("sha256="))


def verificacion_webhook(modo: str | None, token: str | None) -> bool:
    """El apretón de manos inicial de Meta (petición GET)."""
    return modo == "subscribe" and bool(token) and hmac.compare_digest(
        token or "", config.wa_verify_token
    )


def _bytes(clave: str) -> bytes:
    return clave.encode("utf-8")[:_MAX_BYTES]


def cifrar_clave(clave: str) -> str:
    return bcrypt.hashpw(_bytes(clave), bcrypt.gensalt()).decode("utf-8")


def clave_correcta(clave: str, hash_guardado: str) -> bool:
    try:
        return bcrypt.checkpw(_bytes(clave), hash_guardado.encode("utf-8"))
    except ValueError:
        return False
