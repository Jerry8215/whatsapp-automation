"""
Avisos push al celular.

Es el canal que el consultorio pidió: que suene el teléfono cuando una
conversación necesita a una persona, sin tener que mirar el panel.

Cómo funciona, en una línea: el navegador entrega un endpoint y dos claves,
el servidor cifra el aviso contra esas claves y se lo pasa al servicio de
envío del navegador (Google, Apple o Mozilla), que lo entrega aunque el
panel esté cerrado.

Tres cosas que conviene tener presentes:

  * **No reemplaza a Telegram.** Es el canal más cómodo, pero depende de que
    el sistema operativo no haya matado la suscripción. Telegram sigue
    siendo el que no falla, y por eso `notify.avisar` dispara los dos.
  * **En iPhone solo funciona con la app agregada a la pantalla de inicio.**
    Es una restricción de Apple (iOS 16.4+), no del sistema. El panel lo
    explica en pantalla en lugar de dejar un botón que no hace nada.
  * **Nada clínico viaja en el aviso.** Solo el nombre del paciente, el
    motivo administrativo y el enlace a la conversación. El aviso pasa por
    un servicio de terceros; el contenido no.

Sin claves VAPID configuradas el módulo no hace nada y no rompe nada.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from sqlmodel import select

from app.config import config
from app.db import sesion
from app.models import SuscripcionPush

log = logging.getLogger(__name__)

#: Endpoints muertos: el navegador se desinstaló o revocó el permiso. La
#: suscripción se borra en vez de reintentarse para siempre.
_CADUCADA = (404, 410)


def _reclamo_vapid() -> dict:
    contacto = config.vapid_contacto or "mailto:soporte@consultorio.local"
    if not contacto.startswith("mailto:"):
        contacto = f"mailto:{contacto}"
    return {"sub": contacto}


def suscripciones(usuario_id: int | None = None) -> list[SuscripcionPush]:
    with sesion() as s:
        consulta = select(SuscripcionPush)
        if usuario_id is not None:
            consulta = consulta.where(SuscripcionPush.usuario_id == usuario_id)
        return list(s.exec(consulta))


def guardar_suscripcion(
    *, usuario_id: int, endpoint: str, p256dh: str, auth: str, agente: str = ""
) -> SuscripcionPush:
    """
    Alta idempotente.

    El navegador puede renovar la suscripción por su cuenta y volver a
    mandarla; si el endpoint ya existe se actualiza en lugar de duplicarse,
    o el aviso saldría dos veces.
    """
    with sesion() as s:
        existente = s.exec(
            select(SuscripcionPush).where(SuscripcionPush.endpoint == endpoint)
        ).first()
        if existente:
            existente.usuario_id = usuario_id
            existente.clave_p256dh = p256dh
            existente.clave_auth = auth
            existente.agente = agente[:200]
            s.add(existente)
            s.commit()
            s.refresh(existente)
            return existente

        nueva = SuscripcionPush(
            usuario_id=usuario_id,
            endpoint=endpoint,
            clave_p256dh=p256dh,
            clave_auth=auth,
            agente=agente[:200],
        )
        s.add(nueva)
        s.commit()
        s.refresh(nueva)
        return nueva


def borrar_suscripcion(endpoint: str) -> bool:
    with sesion() as s:
        fila = s.exec(
            select(SuscripcionPush).where(SuscripcionPush.endpoint == endpoint)
        ).first()
        if not fila:
            return False
        s.delete(fila)
        s.commit()
        return True


def _enviar_una(suscripcion: SuscripcionPush, carga: str) -> int | None:
    """
    Envía a una suscripción. Devuelve el código HTTP si algo salió mal.

    Se ejecuta en un hilo aparte: pywebpush es síncrono y el webhook no
    puede quedarse esperando a Google.
    """
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info={
                "endpoint": suscripcion.endpoint,
                "keys": {
                    "p256dh": suscripcion.clave_p256dh,
                    "auth": suscripcion.clave_auth,
                },
            },
            data=carga,
            vapid_private_key=config.vapid_clave_privada,
            vapid_claims=_reclamo_vapid(),
            timeout=10,
        )
        return None
    except WebPushException as e:
        return getattr(e.response, "status_code", None) or 0
    except Exception:
        log.exception("Fallo inesperado al enviar el aviso push")
        return 0


async def avisar_push(
    *,
    titulo: str,
    cuerpo: str,
    conversacion_id: int | None = None,
    urgente: bool = False,
) -> int:
    """
    Manda el aviso a todos los navegadores suscritos. Nunca levanta.

    Devuelve cuántos avisos salieron, que es lo que miran las pruebas.
    """
    if not config.push_configurado:
        return 0

    destinos = suscripciones()
    if not destinos:
        return 0

    enlace = (
        f"/panel/conversaciones/{conversacion_id}" if conversacion_id else "/panel"
    )
    carga = json.dumps({
        "titulo": ("🔴 " if urgente else "") + titulo,
        "cuerpo": cuerpo,
        "enlace": enlace,
        "urgente": urgente,
        # Un aviso por conversación: si llegan tres mensajes seguidos del
        # mismo paciente, el celular muestra uno actualizado y no tres.
        "etiqueta": f"conv-{conversacion_id}" if conversacion_id else "panel",
    }, ensure_ascii=False)

    enviados = 0
    for suscripcion in destinos:
        codigo = await asyncio.to_thread(_enviar_una, suscripcion, carga)
        if codigo is None:
            enviados += 1
            _marcar_envio(suscripcion.endpoint)
        elif codigo in _CADUCADA:
            log.info("Suscripción push caducada, se elimina: %s", suscripcion.endpoint[:60])
            borrar_suscripcion(suscripcion.endpoint)
        else:
            log.warning("El aviso push falló con código %s", codigo)

    return enviados


def _marcar_envio(endpoint: str) -> None:
    with sesion() as s:
        fila = s.exec(
            select(SuscripcionPush).where(SuscripcionPush.endpoint == endpoint)
        ).first()
        if fila:
            fila.ultimo_envio_en = datetime.utcnow()
            s.add(fila)
            s.commit()
