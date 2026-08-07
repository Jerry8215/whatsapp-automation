"""
Pruebas de las franjas reservadas.

Doctoralia confirmó que no hay API, ni integración externa, ni exportación
de calendario (caso MX-03213156). El asistente no puede ver la agenda real
de ninguna manera.

La respuesta es de diseño: el consultorio bloquea franjas en Doctoralia y
las destina solo a WhatsApp. Dentro de esas franjas este sistema es la
única fuente de verdad, así que el choque no se detecta — no puede ocurrir.

Lo que estas pruebas defienden es exactamente eso: que el asistente NUNCA
ofrezca un horario fuera de las franjas reservadas.
"""

import json
from datetime import datetime, time, timedelta

import pytest
from sqlmodel import select

from app.agenda.franjas import FranjasReservadas, citas_por_cargar, hay_franjas
from app.db import sesion
from app.models import Cita, EstadoCita, Paciente, Sede
from app.tiempo import a_local

LUNES, MARTES, MIERCOLES, JUEVES, VIERNES = 0, 1, 2, 3, 4


@pytest.fixture
def sede_con_franjas():
    """Sede que atiende 9-14 pero solo reserva 10-12 para WhatsApp."""
    with sesion() as s:
        sede = s.exec(select(Sede).where(Sede.activa)).first()
        sede.horario_json = json.dumps([
            {"dia": d, "desde": "09:00", "hasta": "14:00"} for d in range(5)
        ])
        sede.franjas_json = json.dumps([
            {"dia": MARTES, "desde": "10:00", "hasta": "12:00"},
            {"dia": JUEVES, "desde": "10:00", "hasta": "12:00"},
        ])
        sede.duracion_cita_min = 30
        s.add(sede)
        s.commit()
        return sede.id


@pytest.fixture
def sede_sin_franjas():
    with sesion() as s:
        sede = s.exec(
            select(Sede).where(Sede.activa).order_by(Sede.orden.desc())  # type: ignore[attr-defined]
        ).first()
        sede.franjas_json = "[]"
        s.add(sede)
        s.commit()
        return sede.id


async def huecos_de(sede_id: int, dias: int = 21):
    desde = datetime.utcnow()
    return await FranjasReservadas().huecos(sede_id, desde, desde + timedelta(days=dias))


# ----------------------------------------------------------------------
#  Lo esencial: nunca fuera de la franja
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_solo_se_ofrecen_horarios_dentro_de_las_franjas(sede_con_franjas):
    huecos = await huecos_de(sede_con_franjas)
    assert huecos, "No ofreció ningún horario"

    for h in huecos:
        local = a_local(h.inicio)
        assert local.weekday() in (MARTES, JUEVES), (
            f"Ofreció un {local:%A}, y solo hay franjas martes y jueves"
        )
        assert time(10, 0) <= local.time() < time(12, 0), (
            f"Ofreció las {local:%H:%M}, fuera de la franja de 10:00 a 12:00"
        )


@pytest.mark.asyncio
async def test_no_se_ofrece_nada_en_horario_de_atencion_sin_franja(sede_con_franjas):
    """
    La sede atiende de 9 a 14, pero solo reservó de 10 a 12. Las 9:00 y las
    13:00 son horario de atención y NO deben ofrecerse: ahí puede haber una
    cita tomada desde el sitio web que el asistente no ve.
    """
    huecos = await huecos_de(sede_con_franjas)
    horas = {a_local(h.inicio).time() for h in huecos}

    assert time(9, 0) not in horas
    assert time(9, 30) not in horas
    assert time(12, 0) not in horas
    assert time(13, 0) not in horas


@pytest.mark.asyncio
async def test_una_sede_sin_franjas_no_ofrece_nada(sede_sin_franjas):
    """
    Sin franjas configuradas el asistente no puede prometer ningún horario.
    Prometer a ciegas sería peor que no prometer nada.
    """
    assert await huecos_de(sede_sin_franjas) == []
    assert hay_franjas(sede_sin_franjas) is False


def test_hay_franjas_distingue_bien(sede_con_franjas, sede_sin_franjas):
    assert hay_franjas(sede_con_franjas) is True
    assert hay_franjas(sede_sin_franjas) is False


# ----------------------------------------------------------------------
#  Dentro de la franja no puede haber choques
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_un_horario_ya_tomado_deja_de_ofrecerse(sede_con_franjas, telefono):
    huecos = await huecos_de(sede_con_franjas)
    elegido = huecos[0]

    with sesion() as s:
        p = Paciente(telefono=telefono, nombre="Ana López")
        s.add(p)
        s.commit()
        s.refresh(p)
        s.add(Cita(
            paciente_id=p.id,  # type: ignore[arg-type]
            sede_id=sede_con_franjas,
            inicio=elegido.inicio,
            fin=elegido.fin,
            estado=EstadoCita.AGENDADA,
        ))
        s.commit()

    despues = await huecos_de(sede_con_franjas)
    assert all(h.inicio != elegido.inicio for h in despues), (
        "Volvió a ofrecer un horario ya tomado"
    )


@pytest.mark.asyncio
async def test_la_cita_dentro_de_franja_queda_en_firme(sede_con_franjas, telefono):
    """
    Al paciente se le confirma en el momento. Como nadie más puede tomar
    ese horario, no hace falta un «se lo confirmamos luego».
    """
    from app.agenda.service import agendar

    huecos = await huecos_de(sede_con_franjas)

    with sesion() as s:
        p = Paciente(telefono=telefono, nombre="Jorge Aguilar")
        s.add(p)
        s.commit()
        s.refresh(p)
        paciente_id = p.id

    cita = await agendar(
        paciente_id=paciente_id,  # type: ignore[arg-type]
        sede_id=sede_con_franjas,
        inicio=huecos[0].inicio,
    )
    assert cita.estado is EstadoCita.AGENDADA
    assert cita.estado is not EstadoCita.SOLICITADA


@pytest.mark.asyncio
async def test_no_se_puede_agendar_dos_veces_el_mismo_hueco(sede_con_franjas, telefono):
    """Dos pacientes pueden estar eligiendo el mismo horario a la vez."""
    from app.agenda.base import CupoYaOcupado
    from app.agenda.service import agendar

    huecos = await huecos_de(sede_con_franjas)
    momento = huecos[0].inicio

    with sesion() as s:
        a = Paciente(telefono=telefono, nombre="Primero")
        b = Paciente(telefono=telefono + "9", nombre="Segundo")
        s.add(a)
        s.add(b)
        s.commit()
        s.refresh(a)
        s.refresh(b)
        id_a, id_b = a.id, b.id

    await agendar(paciente_id=id_a, sede_id=sede_con_franjas, inicio=momento)  # type: ignore[arg-type]

    with pytest.raises(CupoYaOcupado):
        await agendar(paciente_id=id_b, sede_id=sede_con_franjas, inicio=momento)  # type: ignore[arg-type]


# ----------------------------------------------------------------------
#  Lista de pendientes de la asistente
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_una_cita_nueva_aparece_por_cargar(sede_con_franjas, telefono):
    from app.agenda.service import agendar

    huecos = await huecos_de(sede_con_franjas)
    with sesion() as s:
        p = Paciente(telefono=telefono, nombre="Claudia Ibarra")
        s.add(p)
        s.commit()
        s.refresh(p)
        paciente_id = p.id

    cita = await agendar(
        paciente_id=paciente_id,  # type: ignore[arg-type]
        sede_id=sede_con_franjas,
        inicio=huecos[0].inicio,
    )

    assert cita.cargada_en_doctoralia is False
    assert any(c.id == cita.id for c in citas_por_cargar())


@pytest.mark.asyncio
async def test_al_marcarla_cargada_sale_de_la_lista(sede_con_franjas, telefono):
    from app.agenda.service import agendar

    huecos = await huecos_de(sede_con_franjas)
    with sesion() as s:
        p = Paciente(telefono=telefono, nombre="Luis Ramírez")
        s.add(p)
        s.commit()
        s.refresh(p)
        paciente_id = p.id

    cita = await agendar(
        paciente_id=paciente_id,  # type: ignore[arg-type]
        sede_id=sede_con_franjas,
        inicio=huecos[0].inicio,
    )

    with sesion() as s:
        c = s.get(Cita, cita.id)
        c.cargada_en_doctoralia = True
        s.add(c)
        s.commit()

    assert all(c.id != cita.id for c in citas_por_cargar())


def test_una_cita_pasada_no_queda_en_la_lista(telefono):
    """Lo de ayer ya no hay que cargarlo."""
    with sesion() as s:
        sede = s.exec(select(Sede)).first()
        p = Paciente(telefono=telefono, nombre="Teresa Ruiz")
        s.add(p)
        s.commit()
        s.refresh(p)
        pasado = datetime.utcnow() - timedelta(days=2)
        s.add(Cita(
            paciente_id=p.id,  # type: ignore[arg-type]
            sede_id=sede.id,  # type: ignore[arg-type]
            inicio=pasado,
            fin=pasado + timedelta(minutes=30),
            estado=EstadoCita.AGENDADA,
        ))
        s.commit()

    assert all(c.inicio >= datetime.utcnow() for c in citas_por_cargar())
