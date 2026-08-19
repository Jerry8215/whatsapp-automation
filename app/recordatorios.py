"""
Recordatorios de cita y su respuesta.

Es la funcionalidad que más ausencias evita, y también la única en la que
el sistema le escribe primero al paciente. Eso implica dos cosas:

1. Fuera de la ventana de 24 horas hay que usar una plantilla aprobada por
   Meta (ver `docs/plantillas-whatsapp.md`). El texto libre falla.
2. Cada envío tiene costo y afecta la calificación de calidad del número.
   Por eso nunca se manda dos veces la misma cita, ni se manda para citas
   canceladas o ya pasadas.

El recordatorio lleva la dirección de SU sede. En un consultorio con tres
ubicaciones, un recordatorio genérico manda al paciente a la dirección
equivocada, que es la causa más común de ausencia.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlmodel import select

from app.db import sesion
from app.models import (
    Cita,
    Conversacion,
    EstadoCita,
    EstadoConversacion,
    Mensaje,
    Paciente,
    RegistroAuditoria,
    Remitente,
    Sede,
)
from app.whatsapp import client

log = logging.getLogger(__name__)

HORAS_ANTES = 24
#: No se manda un recordatorio para algo que ocurre en menos de este plazo.
#: Sirve de poco y molesta.
HORAS_MINIMAS = 2

PLANTILLA_RECORDATORIO = "recordatorio_cita"
PLANTILLA_CONFIRMACION = "confirmacion_cita"
PLANTILLA_REPROGRAMADA = "cita_reprogramada"

# Identificadores de los botones de la plantilla.
BOTON_CONFIRMAR = "confirmar_cita"
BOTON_REPROGRAMAR = "reprogramar_cita"


def fecha_legible(dt: datetime) -> str:
    from app.brain.flows import fecha_legible as _f

    return _f(dt)


# ======================================================================
#  Envío
# ======================================================================

async def enviar_pendientes() -> int:
    """
    Manda los recordatorios que corresponden ahora. La ejecuta el
    programador cada 15 minutos.
    """
    ahora = datetime.utcnow()
    limite = ahora + timedelta(hours=HORAS_ANTES)
    minimo = ahora + timedelta(hours=HORAS_MINIMAS)

    with sesion() as s:
        pendientes = list(s.exec(
            select(Cita).where(
                Cita.estado.in_([  # type: ignore[attr-defined]
                    EstadoCita.AGENDADA, EstadoCita.CONFIRMADA
                ]),
                Cita.recordatorio_enviado_en.is_(None),  # type: ignore[union-attr]
                Cita.inicio <= limite,
                Cita.inicio >= minimo,
            )
        ).all())

    enviados = 0
    for cita in pendientes:
        if await _enviar_uno(cita.id):  # type: ignore[arg-type]
            enviados += 1

    if enviados:
        log.info("Recordatorios enviados: %s", enviados)
    return enviados


async def _enviar_uno(cita_id: int) -> bool:
    with sesion() as s:
        cita = s.get(Cita, cita_id)
        if not cita or cita.recordatorio_enviado_en:
            return False
        paciente = s.get(Paciente, cita.paciente_id)
        sede = s.get(Sede, cita.sede_id)
        if not paciente or not sede:
            log.warning("Cita %s sin paciente o sede; se omite", cita_id)
            return False

        # El paciente pidió que no le escribiéramos. Es lo que se le
        # prometió en el primer contacto, así que manda por encima de
        # cualquier recordatorio. La cita sigue en pie; lo que no sale es
        # el mensaje.
        if paciente.baja_en:
            cita.recordatorio_enviado_en = datetime.utcnow()
            cita.notas = (cita.notas + " · Sin recordatorio: el paciente pidió la baja.").strip(" ·")
            s.add(cita)
            s.commit()
            log.info("Cita %s: el paciente está de baja; no se envía recordatorio", cita_id)
            return False

        nombre = (paciente.nombre or "").split()[0] if paciente.nombre else "paciente"
        telefono = paciente.telefono
        cuando = fecha_legible(cita.inicio)
        direccion = sede.direccion
        nombre_sede = sede.nombre

    try:
        await client.enviar_plantilla(
            telefono,
            PLANTILLA_RECORDATORIO,
            [nombre, cuando, nombre_sede, direccion],
        )
    except Exception:
        log.exception("Falló el recordatorio de la cita %s", cita_id)
        # No se marca como enviado: se reintenta en la siguiente ronda.
        return False

    with sesion() as s:
        cita = s.get(Cita, cita_id)
        if cita:
            cita.recordatorio_enviado_en = datetime.utcnow()
            s.add(cita)
        s.add(RegistroAuditoria(
            actor="sistema",
            accion="recordatorio.enviado",
            entidad="cita",
            entidad_id=cita_id,
            detalle=f"{nombre_sede} · {cuando}",
        ))
        s.commit()

    _registrar_en_conversacion(
        cita_id,
        f"Recordatorio enviado — {cuando}, {nombre_sede}",
    )
    return True


def _registrar_en_conversacion(cita_id: int, texto: str) -> None:
    """Deja constancia en el hilo, para que el panel muestre lo ocurrido."""
    with sesion() as s:
        cita = s.get(Cita, cita_id)
        if not cita:
            return
        conv = s.exec(
            select(Conversacion)
            .where(Conversacion.paciente_id == cita.paciente_id)
            .order_by(Conversacion.id.desc())  # type: ignore[attr-defined]
        ).first()
        if not conv:
            return
        s.add(Mensaje(
            conversacion_id=conv.id,  # type: ignore[arg-type]
            remitente=Remitente.SISTEMA,
            texto=texto,
        ))
        s.commit()


# ======================================================================
#  Respuesta del paciente
# ======================================================================

async def responder_boton(telefono: str, payload: str) -> str | None:
    """
    Procesa el toque de un botón del recordatorio.

    Devuelve el texto a enviarle al paciente, o None si el payload no
    corresponde a un recordatorio.
    """
    if payload not in (BOTON_CONFIRMAR, BOTON_REPROGRAMAR):
        return None

    cita = _proxima_cita(telefono)
    if not cita:
        return (
            "No encuentro una cita próxima a su nombre. Permítame comunicarla "
            "con el consultorio para revisarlo."
        )

    if payload == BOTON_CONFIRMAR:
        return _confirmar(cita)
    return await _pedir_reprogramacion(cita)


def _proxima_cita(telefono: str) -> Cita | None:
    with sesion() as s:
        paciente = s.exec(
            select(Paciente).where(Paciente.telefono == telefono)
        ).first()
        if not paciente:
            return None
        return s.exec(
            select(Cita)
            .where(
                Cita.paciente_id == paciente.id,
                Cita.inicio >= datetime.utcnow(),
                Cita.estado.in_([  # type: ignore[attr-defined]
                    EstadoCita.AGENDADA, EstadoCita.CONFIRMADA,
                    EstadoCita.SOLICITADA,
                ]),
            )
            .order_by(Cita.inicio)  # type: ignore[arg-type]
        ).first()


def _confirmar(cita: Cita) -> str:
    with sesion() as s:
        actual = s.get(Cita, cita.id)
        if not actual:
            return "No pude registrar su confirmación. La comunico con el consultorio."
        actual.estado = EstadoCita.CONFIRMADA
        actual.confirmada_por_paciente_en = datetime.utcnow()
        s.add(actual)
        s.add(RegistroAuditoria(
            actor="paciente",
            accion="cita.confirmada",
            entidad="cita",
            entidad_id=cita.id,
            detalle="Confirmada desde el recordatorio",
        ))
        s.commit()
        sede = s.get(Sede, actual.sede_id)

    _registrar_en_conversacion(cita.id, "El paciente confirmó su cita")  # type: ignore[arg-type]

    texto = f"Perfecto, queda confirmada para el {fecha_legible(cita.inicio)}"
    if sede:
        texto += f" en {sede.nombre}"
    return texto + ". Aquí la esperamos. 🙌"


async def _pedir_reprogramacion(cita: Cita) -> str:
    """
    El paciente pidió mover la cita.

    La cita **no se cancela todavía**: se marca la intención y se le ofrecen
    alternativas. Liberar el cupo antes de que elija otro es la forma más
    rápida de dejarlo sin ninguno.
    """
    from app.agenda.service import ofrecer_horarios

    with sesion() as s:
        s.add(RegistroAuditoria(
            actor="paciente",
            accion="cita.reprogramacion_solicitada",
            entidad="cita",
            entidad_id=cita.id,
        ))
        s.commit()

    _registrar_en_conversacion(cita.id, "El paciente pidió reprogramar")  # type: ignore[arg-type]

    try:
        huecos = await ofrecer_horarios(cita.sede_id, cantidad=3)
    except Exception:
        log.exception("No se pudieron consultar horarios para reprogramar")
        huecos = []

    if not huecos:
        return (
            "Con gusto la reprogramamos. En este momento no tengo horarios "
            "libres a la mano, así que la comunico con el consultorio para "
            "buscarle un espacio que le acomode."
        )

    listado = "\n".join(f"· {fecha_legible(h.inicio)}" for h in huecos)
    return (
        f"Con gusto la reprogramamos. Tengo estos horarios disponibles:\n\n"
        f"{listado}\n\n¿Cuál prefiere?"
    )


# ======================================================================
#  Tareas de mantenimiento
# ======================================================================

async def marcar_ausencias() -> int:
    """
    Cierra las citas que ya pasaron y nadie tocó.

    Sin esto, las métricas de conversión y ausentismo del panel se
    desvirtúan con el tiempo.
    """
    corte = datetime.utcnow() - timedelta(hours=4)
    with sesion() as s:
        vencidas = list(s.exec(
            select(Cita).where(
                Cita.fin < corte,
                Cita.estado.in_([  # type: ignore[attr-defined]
                    EstadoCita.AGENDADA, EstadoCita.CONFIRMADA,
                    EstadoCita.SOLICITADA,
                ]),
            )
        ).all())
        for cita in vencidas:
            # Sin integración de agenda no hay forma de saber si asistió.
            # Se deja como asistió por omisión, y el consultorio corrige
            # desde el panel lo que corresponda.
            cita.estado = EstadoCita.ASISTIO
            s.add(cita)
        if vencidas:
            s.commit()
    return len(vencidas)


async def cerrar_conversaciones_inactivas() -> int:
    """
    Cierra las que llevan mucho sin movimiento y nadie atendió.

    No toca las que requieren atención de una persona: esas quedan a la
    vista hasta que alguien las resuelva.
    """
    corte = datetime.utcnow() - timedelta(hours=12)
    with sesion() as s:
        viejas = list(s.exec(
            select(Conversacion).where(
                Conversacion.cerrada_en.is_(None),  # type: ignore[union-attr]
                Conversacion.ultima_actividad < corte,
                Conversacion.estado.in_([  # type: ignore[attr-defined]
                    EstadoConversacion.BOT, EstadoConversacion.RESUELTA
                ]),
            )
        ).all())
        for c in viejas:
            c.cerrada_en = datetime.utcnow()
            c.estado = EstadoConversacion.RESUELTA
            if not c.convirtio and not c.motivo_perdida:
                c.motivo_perdida = "Dejó de responder"
            s.add(c)
        if viejas:
            s.commit()
    return len(viejas)


async def depurar_historiales() -> int:
    """
    Elimina los historiales vencidos según la política de retención.

    Es lo que se le prometió al consultorio respecto de la LFPDPPP: los
    datos no se guardan indefinidamente. Se conservan las citas y la ficha
    del paciente; lo que se borra son los mensajes.
    """
    from app.config import config

    if config.retencion_conversaciones_dias <= 0:
        return 0

    corte = datetime.utcnow() - timedelta(days=config.retencion_conversaciones_dias)
    with sesion() as s:
        antiguas = list(s.exec(
            select(Conversacion).where(
                Conversacion.cerrada_en.is_not(None),  # type: ignore[union-attr]
                Conversacion.cerrada_en < corte,
            )
        ).all())

        borrados = 0
        for c in antiguas:
            mensajes = list(s.exec(
                select(Mensaje).where(Mensaje.conversacion_id == c.id)
            ).all())
            for m in mensajes:
                s.delete(m)
                borrados += 1

        if borrados:
            s.add(RegistroAuditoria(
                actor="sistema",
                accion="retencion.depurada",
                detalle=(
                    f"{borrados} mensajes eliminados de {len(antiguas)} "
                    f"conversaciones cerradas hace más de "
                    f"{config.retencion_conversaciones_dias} días"
                ),
            ))
            s.commit()
            log.info("Retención: %s mensajes eliminados", borrados)

    return borrados
