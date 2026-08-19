"""
Servicio de agenda: lo que usa el resto del sistema.

Elige el proveedor según la configuración y agrega lo que debe cumplirse
independientemente de cuál esté activo:

  * re-verificación del cupo en el instante de confirmar
  * persistencia local de la cita
  * registro de auditoría
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlmodel import select

from app.agenda.base import (
    CupoYaOcupado,
    Hueco,
    ProveedorAgenda,
    ResultadoReserva,
)
from app.config import config
from app.db import sesion
from app.models import Cita, EstadoCita, Paciente, RegistroAuditoria, Sede

log = logging.getLogger(__name__)

_proveedor: ProveedorAgenda | None = None
_origen_activo: str = ""

#: Los orígenes de agenda que el consultorio puede elegir desde el panel.
#: `api` y `calendar` no están: Doctoralia confirmó que no existen para su
#: cuenta, y ofrecerlos sería ofrecer algo que no funciona.
ORIGENES = ("franjas", "google")


def origen() -> str:
    """
    De dónde sale la agenda hoy.

    Se guarda en la base y no en el entorno, porque es una decisión del
    consultorio y no del despliegue: el día que dejen Doctoralia, cambian el
    interruptor del panel y listo. Google queda construido y en pausa hasta
    entonces, tal como se acordó.
    """
    from app.models import Ajuste

    with sesion() as s:
        ajuste = s.get(Ajuste, "agenda_origen")
    valor = ajuste.valor if ajuste else config.agenda_proveedor
    return valor if valor in ("franjas", "google", "api", "calendar") else "franjas"


def proveedor() -> ProveedorAgenda:
    global _proveedor, _origen_activo

    elegido = origen()
    if _proveedor is not None and _origen_activo == elegido:
        return _proveedor

    if elegido == "api":
        from app.agenda.doctoralia_api import DoctoraliaAPI

        _proveedor = DoctoraliaAPI()
        log.info("Agenda: API de Doctoralia (descartada el 07/08/2026)")
    elif elegido == "calendar":
        from app.agenda.calendar_sync import SincroniaCalendario

        _proveedor = SincroniaCalendario()
        log.info("Agenda: sincronización por calendario")
    elif elegido == "google":
        from app.agenda.google_calendar import AgendaGoogle

        _proveedor = AgendaGoogle()
        log.info("Agenda: Google Calendar (lectura y escritura reales)")
    else:
        from app.agenda.franjas import FranjasReservadas

        _proveedor = FranjasReservadas()
        log.info("Agenda: franjas reservadas para WhatsApp")

    _origen_activo = elegido
    return _proveedor


def reiniciar_proveedor() -> None:
    """Para cuando se cambie el origen desde el panel, sin reiniciar nada."""
    global _proveedor, _origen_activo
    _proveedor = None
    _origen_activo = ""


# ----------------------------------------------------------------------


async def ofrecer_horarios(
    sede_id: int, dias: int = 14, cantidad: int = 3
) -> list[Hueco]:
    """
    Primeros huecos disponibles de una sede.

    Se ofrecen pocos a propósito: una lista de veinte horarios abruma y
    baja la conversión. Tres opciones concretas funcionan mejor.
    """
    desde = datetime.utcnow()
    hasta = desde + timedelta(days=dias)
    libres = await proveedor().huecos(sede_id, desde, hasta)
    libres.sort(key=lambda h: h.inicio)
    return libres[:cantidad]


async def agendar(
    *,
    paciente_id: int,
    sede_id: int,
    inicio: datetime,
    tipo: str = "valoracion",
    motivo: str = "",
    creada_por: str = "bot",
) -> Cita:
    """
    Reserva de verdad.

    Levanta CupoYaOcupado si el horario se tomó entre que se ofreció y que
    el paciente eligió. Quien llame debe atrapar esa excepción y ofrecer
    alternativas, nunca dejar al paciente sin respuesta.
    """
    with sesion() as s:
        sede = s.get(Sede, sede_id)
        paciente = s.get(Paciente, paciente_id)
        if not sede or not paciente:
            raise ValueError("Sede o paciente inexistente")
        if not sede.activa:
            raise ValueError(f"La sede «{sede.nombre}» está desactivada")
        duracion = sede.duracion_cita_min or 30
        nombre_sede = sede.nombre
        nombre_paciente = paciente.nombre or "Paciente de WhatsApp"
        telefono = paciente.telefono

    fin = inicio + timedelta(minutes=duracion)

    resultado: ResultadoReserva = await proveedor().reservar(
        sede_id=sede_id,
        inicio=inicio,
        fin=fin,
        nombre_paciente=nombre_paciente,
        telefono=telefono,
        motivo=motivo,
    )

    estado = (
        EstadoCita.SOLICITADA
        if resultado.requiere_confirmacion_humana
        else EstadoCita.AGENDADA
    )

    # Si el proveedor escribió la cita en la agenda de verdad —hoy solo
    # Google— no queda ningún paso manual, así que no debe aparecer en la
    # lista de «por cargar». Las citas creadas antes de la mudanza siguen
    # marcadas como pendientes: esas sí hay que copiarlas.
    ya_esta_en_la_agenda = proveedor().escribe_en_la_agenda

    with sesion() as s:
        cita = Cita(
            paciente_id=paciente_id,
            sede_id=sede_id,
            inicio=inicio,
            fin=fin,
            estado=estado,
            tipo=tipo,
            externo_id=resultado.externo_id,
            creada_por=creada_por,
            notas=resultado.motivo,
            cargada_en_doctoralia=ya_esta_en_la_agenda,
            cargada_en_doctoralia_en=(
                datetime.utcnow() if ya_esta_en_la_agenda else None
            ),
        )
        s.add(cita)
        s.add(RegistroAuditoria(
            actor=creada_por,
            accion="cita.creada",
            entidad="cita",
            detalle=(
                f"{nombre_paciente} · {nombre_sede} · "
                f"{inicio:%d/%m/%Y %H:%M} · estado {estado.value}"
            ),
        ))
        s.commit()
        s.refresh(cita)
        return cita


async def cancelar(cita_id: int, por: str = "bot") -> bool:
    with sesion() as s:
        cita = s.get(Cita, cita_id)
        if not cita:
            return False
        externo = cita.externo_id

    ok = await proveedor().cancelar(externo) if externo else True

    with sesion() as s:
        cita = s.get(Cita, cita_id)
        if cita:
            cita.estado = EstadoCita.CANCELADA
            s.add(cita)
            s.add(RegistroAuditoria(
                actor=por,
                accion="cita.cancelada",
                entidad="cita",
                entidad_id=cita_id,
                detalle=(
                    "" if proveedor().escribe_en_la_agenda
                    else "Hay que retirarla también de Doctoralia, a mano."
                ),
            ))
            s.commit()
    return ok


async def citas_para_recordar(horas_antes: int = 24) -> list[Cita]:
    """Citas cuyo recordatorio corresponde enviar ahora."""
    objetivo = datetime.utcnow() + timedelta(hours=horas_antes)
    with sesion() as s:
        return list(s.exec(
            select(Cita).where(
                Cita.estado.in_([  # type: ignore[attr-defined]
                    EstadoCita.AGENDADA, EstadoCita.CONFIRMADA
                ]),
                Cita.recordatorio_enviado_en.is_(None),  # type: ignore[union-attr]
                Cita.inicio <= objetivo,
                Cita.inicio > datetime.utcnow(),
            )
        ).all())


def sedes_activas() -> list[Sede]:
    with sesion() as s:
        return list(s.exec(
            select(Sede).where(Sede.activa).order_by(Sede.orden)  # type: ignore[arg-type]
        ).all())
