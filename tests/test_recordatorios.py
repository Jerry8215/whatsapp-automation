"""
Pruebas de recordatorios y del ciclo de vida de la cita.

Acá el sistema le escribe primero al paciente, y cada envío cuesta y afecta
la calificación del número. Lo que más se verifica es lo que NO debe
enviarse: repetido, para citas canceladas, o para algo que ya pasó.
"""

from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from app.models import Cita, Conversacion, EstadoCita, Paciente, Sede
from app.recordatorios import (
    BOTON_CONFIRMAR,
    BOTON_REPROGRAMAR,
    cerrar_conversaciones_inactivas,
    depurar_historiales,
    enviar_pendientes,
    marcar_ausencias,
    responder_boton,
)
from app.db import sesion


def crear_cita(
    telefono: str,
    *,
    en_horas: float = 20,
    estado: EstadoCita = EstadoCita.AGENDADA,
    recordado: bool = False,
) -> int:
    with sesion() as s:
        paciente = s.exec(select(Paciente).where(Paciente.telefono == telefono)).first()
        if not paciente:
            paciente = Paciente(telefono=telefono, nombre="Ana López")
            s.add(paciente)
            s.commit()
            s.refresh(paciente)

        sede = s.exec(select(Sede).where(Sede.activa)).first()
        inicio = datetime.utcnow() + timedelta(hours=en_horas)

        cita = Cita(
            paciente_id=paciente.id,  # type: ignore[arg-type]
            sede_id=sede.id,  # type: ignore[arg-type]
            inicio=inicio,
            fin=inicio + timedelta(minutes=30),
            estado=estado,
            recordatorio_enviado_en=datetime.utcnow() if recordado else None,
        )
        s.add(cita)
        s.commit()
        s.refresh(cita)
        return cita.id  # type: ignore[return-value]


def leer(cita_id: int) -> Cita:
    with sesion() as s:
        return s.get(Cita, cita_id)  # type: ignore[return-value]


# ----------------------------------------------------------------------
#  Cuándo se envía y cuándo no
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_se_recuerda_la_cita_de_manana(telefono):
    cita_id = crear_cita(telefono, en_horas=20)
    await enviar_pendientes()
    assert leer(cita_id).recordatorio_enviado_en is not None


@pytest.mark.asyncio
async def test_nunca_se_recuerda_dos_veces(telefono):
    """Un recordatorio duplicado cuesta dinero y molesta al paciente."""
    cita_id = crear_cita(telefono, en_horas=20)
    await enviar_pendientes()
    primera = leer(cita_id).recordatorio_enviado_en

    await enviar_pendientes()
    assert leer(cita_id).recordatorio_enviado_en == primera


@pytest.mark.asyncio
async def test_no_se_recuerda_una_cita_cancelada(telefono):
    cita_id = crear_cita(telefono, en_horas=20, estado=EstadoCita.CANCELADA)
    await enviar_pendientes()
    assert leer(cita_id).recordatorio_enviado_en is None


@pytest.mark.asyncio
async def test_no_se_recuerda_una_cita_lejana(telefono):
    """A cinco días todavía no corresponde."""
    cita_id = crear_cita(telefono, en_horas=120)
    await enviar_pendientes()
    assert leer(cita_id).recordatorio_enviado_en is None


@pytest.mark.asyncio
async def test_no_se_recuerda_algo_inminente(telefono):
    """A una hora ya no sirve de nada y solo molesta."""
    cita_id = crear_cita(telefono, en_horas=1)
    await enviar_pendientes()
    assert leer(cita_id).recordatorio_enviado_en is None


@pytest.mark.asyncio
async def test_no_se_recuerda_algo_que_ya_paso(telefono):
    cita_id = crear_cita(telefono, en_horas=-5)
    await enviar_pendientes()
    assert leer(cita_id).recordatorio_enviado_en is None


# ----------------------------------------------------------------------
#  Respuesta del paciente
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confirmar_deja_la_cita_confirmada(telefono):
    cita_id = crear_cita(telefono, en_horas=20)
    texto = await responder_boton(telefono, BOTON_CONFIRMAR)

    assert texto and "confirmada" in texto.lower()
    cita = leer(cita_id)
    assert cita.estado is EstadoCita.CONFIRMADA
    assert cita.confirmada_por_paciente_en is not None


@pytest.mark.asyncio
async def test_pedir_reprogramar_no_libera_el_cupo_todavia(telefono):
    """
    Cancelar antes de que el paciente elija otro horario es la forma más
    rápida de dejarlo sin ninguno.
    """
    cita_id = crear_cita(telefono, en_horas=20)
    texto = await responder_boton(telefono, BOTON_REPROGRAMAR)

    assert texto
    assert leer(cita_id).estado is not EstadoCita.CANCELADA


@pytest.mark.asyncio
async def test_un_boton_ajeno_no_se_atiende(telefono):
    crear_cita(telefono, en_horas=20)
    assert await responder_boton(telefono, "otra_cosa") is None


@pytest.mark.asyncio
async def test_confirmar_sin_cita_no_revienta(telefono):
    texto = await responder_boton(telefono, BOTON_CONFIRMAR)
    assert texto and "no encuentro" in texto.lower()


# ----------------------------------------------------------------------
#  Mantenimiento
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_las_citas_pasadas_se_cierran(telefono):
    cita_id = crear_cita(telefono, en_horas=-10)
    await marcar_ausencias()
    assert leer(cita_id).estado is not EstadoCita.AGENDADA


@pytest.mark.asyncio
async def test_una_conversacion_abandonada_se_cierra_como_perdida(telefono):
    with sesion() as s:
        p = Paciente(telefono=telefono, nombre="Sofía Delgado")
        s.add(p)
        s.commit()
        s.refresh(p)
        c = Conversacion(
            paciente_id=p.id,  # type: ignore[arg-type]
            ultima_actividad=datetime.utcnow() - timedelta(hours=20),
        )
        s.add(c)
        s.commit()
        s.refresh(c)
        conv_id = c.id

    await cerrar_conversaciones_inactivas()

    with sesion() as s:
        c = s.get(Conversacion, conv_id)
        assert c.cerrada_en is not None
        assert c.motivo_perdida == "Dejó de responder"


@pytest.mark.asyncio
async def test_una_conversacion_pendiente_no_se_cierra_sola(telefono):
    """Lo que espera a una persona sigue a la vista hasta que alguien lo atienda."""
    from app.models import EstadoConversacion

    with sesion() as s:
        p = Paciente(telefono=telefono, nombre="Teresa Ruiz")
        s.add(p)
        s.commit()
        s.refresh(p)
        c = Conversacion(
            paciente_id=p.id,  # type: ignore[arg-type]
            estado=EstadoConversacion.REQUIERE_ATENCION,
            ultima_actividad=datetime.utcnow() - timedelta(hours=48),
        )
        s.add(c)
        s.commit()
        s.refresh(c)
        conv_id = c.id

    await cerrar_conversaciones_inactivas()

    with sesion() as s:
        assert s.get(Conversacion, conv_id).cerrada_en is None


@pytest.mark.asyncio
async def test_la_retencion_no_toca_lo_reciente(telefono):
    """Solo se depura lo vencido, no lo de esta semana."""
    from app.models import Mensaje, Remitente

    with sesion() as s:
        p = Paciente(telefono=telefono, nombre="Luis Ramírez")
        s.add(p)
        s.commit()
        s.refresh(p)
        c = Conversacion(
            paciente_id=p.id,  # type: ignore[arg-type]
            cerrada_en=datetime.utcnow() - timedelta(days=3),
        )
        s.add(c)
        s.commit()
        s.refresh(c)
        s.add(Mensaje(conversacion_id=c.id, remitente=Remitente.PACIENTE, texto="Hola"))  # type: ignore[arg-type]
        s.commit()
        conv_id = c.id

    await depurar_historiales()

    with sesion() as s:
        quedan = s.exec(select(Mensaje).where(Mensaje.conversacion_id == conv_id)).all()
        assert len(quedan) == 1
