"""
Pruebas de zona horaria.

La regla: se guarda en UTC, se muestra en hora del consultorio.

Si esto se rompe, a un paciente con turno a las 10:30 le llega un
recordatorio que dice 16:30, y la rejilla ofrece espacios de madrugada. Es
de los errores que no se ven en desarrollo —el servidor de pruebas suele
estar en UTC— y aparecen recién con pacientes reales.
"""

import json
from datetime import datetime, time, timedelta

import pytest
from sqlmodel import select

from app.db import sesion
from app.models import Sede
from app.tiempo import (
    a_local,
    a_utc,
    combinar_local,
    en_horario_de_atencion,
    fecha_legible,
    hace,
    hora,
)

#: Guadalajara: UTC−6 todo el año, sin horario de verano desde 2022.
DESFASE = 6


def test_guadalajara_esta_seis_horas_atras():
    utc = datetime(2026, 8, 7, 16, 30)
    assert a_local(utc) == datetime(2026, 8, 7, 10, 30)


def test_ida_y_vuelta_no_pierde_nada():
    utc = datetime(2026, 8, 7, 16, 30)
    assert a_utc(a_local(utc)) == utc


def test_la_fecha_para_el_paciente_va_en_hora_local():
    """Guardado 16:30 UTC, el paciente debe leer 10:30."""
    texto = fecha_legible(datetime(2026, 8, 7, 16, 30))
    assert "10:30" in texto
    assert "16:30" not in texto
    assert "viernes" in texto
    assert "7 de agosto" in texto


def test_la_hora_del_panel_va_en_hora_local():
    assert hora(datetime(2026, 8, 7, 16, 30)) == "10:30"


def test_el_cambio_de_dia_se_respeta():
    """02:00 UTC del día 8 son las 20:00 del día 7 en el consultorio."""
    local = a_local(datetime(2026, 8, 8, 2, 0))
    assert local.day == 7
    assert local.hour == 20


def test_un_horario_local_se_convierte_bien_a_utc():
    """Las 9:00 del consultorio son las 15:00 UTC."""
    assert combinar_local(datetime(2026, 8, 7).date(), time(9, 0)) == datetime(2026, 8, 7, 15, 0)


def test_hace_no_depende_de_la_zona():
    referencia = datetime(2026, 8, 7, 12, 0)
    assert hace(referencia - timedelta(minutes=5), referencia) == "5 min"
    assert hace(referencia - timedelta(hours=3), referencia) == "3 h"
    assert hace(None) == ""


# ----------------------------------------------------------------------
#  La rejilla de horarios
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_los_turnos_ofrecidos_caen_dentro_del_horario_publicado():
    """
    Es la prueba que atrapa el error de fondo: si la rejilla se arma en UTC,
    los turnos aparecen de madrugada en hora local.
    """
    from app.agenda.calendar_sync import SincroniaCalendario

    with sesion() as s:
        sede = s.exec(select(Sede).where(Sede.activa)).first()
        sede.horario_json = json.dumps([
            {"dia": d, "desde": "09:00", "hasta": "14:00"} for d in range(7)
        ])
        sede.duracion_cita_min = 30
        s.add(sede)
        s.commit()
        sede_id = sede.id

    desde = datetime.utcnow() + timedelta(days=1)
    huecos = await SincroniaCalendario().huecos(sede_id, desde, desde + timedelta(days=3))

    assert huecos, "No ofreció ningún horario"
    for h in huecos:
        local = a_local(h.inicio)
        assert time(9, 0) <= local.time() < time(14, 0), (
            f"Ofreció un turno a las {local:%H:%M} hora del consultorio, "
            f"fuera del horario de 9:00 a 14:00"
        )


@pytest.mark.asyncio
async def test_no_se_ofrecen_turnos_en_dias_sin_atencion():
    from app.agenda.calendar_sync import SincroniaCalendario

    with sesion() as s:
        sede = s.exec(select(Sede).where(Sede.activa)).first()
        # Solo lunes.
        sede.horario_json = json.dumps([{"dia": 0, "desde": "09:00", "hasta": "14:00"}])
        s.add(sede)
        s.commit()
        sede_id = sede.id

    desde = datetime.utcnow()
    huecos = await SincroniaCalendario().huecos(sede_id, desde, desde + timedelta(days=14))

    for h in huecos:
        assert a_local(h.inicio).weekday() == 0, (
            f"Ofreció un turno en {a_local(h.inicio):%A}, y solo se atiende lunes"
        )


def test_el_horario_de_atencion_se_evalua_en_hora_local():
    with sesion() as s:
        for sede in s.exec(select(Sede)).all():
            sede.horario_json = json.dumps([
                {"dia": d, "desde": "09:00", "hasta": "14:00"} for d in range(7)
            ])
            sede.activa = True
            s.add(sede)
        s.commit()

    # 16:00 UTC = 10:00 del consultorio → abierto
    assert en_horario_de_atencion(datetime(2026, 8, 7, 16, 0)) is True
    # 06:00 UTC = 00:00 del consultorio → cerrado
    assert en_horario_de_atencion(datetime(2026, 8, 7, 6, 0)) is False


# ----------------------------------------------------------------------
#  El saludo
# ----------------------------------------------------------------------

def test_el_saludo_usa_la_hora_del_consultorio_no_la_del_servidor():
    """Un servidor en Europa saludaría «buenas tardes» a las siete de la mañana."""
    from app.brain.flows import _saludo_por_hora

    assert _saludo_por_hora(datetime(2026, 8, 7, 16, 0)) == "Buenos días"     # 10:00 local
    assert _saludo_por_hora(datetime(2026, 8, 7, 21, 0)) == "Buenas tardes"   # 15:00 local
    assert _saludo_por_hora(datetime(2026, 8, 8, 3, 0)) == "Buenas noches"    # 21:00 local
