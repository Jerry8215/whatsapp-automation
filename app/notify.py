"""Avisos al consultorio cuando una conversación necesita a una persona."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import httpx

from app.config import config

log = logging.getLogger(__name__)


async def avisar(
    *,
    titulo: str,
    cuerpo: str,
    conversacion_id: int | None = None,
    urgente: bool = False,
) -> None:
    """
    Dispara todos los canales configurados. Nunca levanta excepción.

    Los tres salen a la vez y a propósito: el push es el más cómodo pero el
    sistema operativo del celular puede matarlo, Telegram es el que no
    falla, y el correo queda como constancia. Un aviso perdido es una
    conversación que nadie atiende.
    """
    marca = "🔴 URGENTE" if urgente else "🟡 Requiere atención"
    enlace = (
        f"{config.panel_url_publica}/panel/conversaciones/{conversacion_id}"
        if conversacion_id else config.panel_url_publica
    )
    texto = f"{marca}\n\n*{titulo}*\n\n{cuerpo}\n\nAbrir: {enlace}"

    await _push(titulo=titulo, cuerpo=cuerpo,
                conversacion_id=conversacion_id, urgente=urgente)
    await _telegram(texto)
    _correo(f"{marca} — {titulo}", f"{cuerpo}\n\nAbrir: {enlace}")


async def _push(
    *, titulo: str, cuerpo: str, conversacion_id: int | None, urgente: bool
) -> None:
    from app.push import avisar_push

    try:
        await avisar_push(
            titulo=titulo,
            cuerpo=cuerpo,
            conversacion_id=conversacion_id,
            urgente=urgente,
        )
    except Exception:
        log.exception("No se pudo enviar el aviso push")


async def _telegram(texto: str) -> None:
    if not config.telegram_bot_token or not config.chats_telegram:
        return
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            for chat_id in config.chats_telegram:
                await c.post(url, json={
                    "chat_id": chat_id,
                    "text": texto,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                })
    except Exception:
        log.exception("No se pudo enviar el aviso por Telegram")


def _correo(asunto: str, cuerpo: str) -> None:
    if not config.smtp_host or not config.correos_aviso:
        return
    try:
        msg = EmailMessage()
        msg["Subject"] = asunto
        msg["From"] = config.smtp_usuario
        msg["To"] = ", ".join(config.correos_aviso)
        msg.set_content(cuerpo)

        with smtplib.SMTP(config.smtp_host, config.smtp_puerto, timeout=15) as smtp:
            smtp.starttls()
            if config.smtp_usuario:
                smtp.login(config.smtp_usuario, config.smtp_clave)
            smtp.send_message(msg)
    except Exception:
        log.exception("No se pudo enviar el aviso por correo")
