"""
Pruebas del modo fuera de horario.

Lo crítico está en la urgencia. Dentro del horario el asistente puede decir
«ya avisé al equipo para que la contacten». Fuera de horario **no**, porque
a las tres de la madrugada no hay nadie — y un paciente con signos de
alarma que se queda esperando una llamada que no va a llegar es el peor
resultado posible de este sistema.
"""

import json
from datetime import datetime

import pytest
from sqlmodel import select

from app.brain import safety
from app.brain.router import procesar_mensaje
from app.db import sesion
from app.models import EstadoConversacion, Sede
from app.tiempo import a_local, en_horario_de_atencion
from app.whatsapp.parser import MensajeEntrante

from tests.test_pipeline import conversacion, entrante, respuestas


@pytest.fixture
def consultorio_abierto_siempre():
    """Todas las sedes abiertas las 24 horas, para forzar «en horario»."""
    with sesion() as s:
        original = {}
        for sede in s.exec(select(Sede)).all():
            original[sede.id] = (sede.horario_json, sede.activa)
            sede.horario_json = json.dumps([
                {"dia": d, "desde": "00:00", "hasta": "23:59"} for d in range(7)
            ])
            sede.activa = True
            s.add(sede)
        s.commit()
    yield
    with sesion() as s:
        for sede_id, (horario, activa) in original.items():
            sede = s.get(Sede, sede_id)
            sede.horario_json, sede.activa = horario, activa
            s.add(sede)
        s.commit()


@pytest.fixture
def consultorio_cerrado_siempre():
    with sesion() as s:
        original = {}
        for sede in s.exec(select(Sede)).all():
            original[sede.id] = sede.horario_json
            sede.horario_json = "[]"
            s.add(sede)
        s.commit()
    yield
    with sesion() as s:
        for sede_id, horario in original.items():
            sede = s.get(Sede, sede_id)
            sede.horario_json = horario
            s.add(sede)
        s.commit()


# ----------------------------------------------------------------------
#  Lo esencial
# ----------------------------------------------------------------------

def test_fuera_de_horario_no_se_promete_una_llamada():
    """
    Es la prueba más importante del módulo. Si la respuesta de urgencia
    fuera de horario dice que van a llamar, el paciente puede quedarse
    esperando en vez de ir a urgencias.
    """
    veredicto = safety.evaluar("Tengo un dolor muy fuerte y fiebre alta")
    texto = safety.respuesta_para(veredicto, en_horario=False).lower()

    assert "urgencias" in texto
    for promesa in ("la contactan", "lo contactan", "para que la contacten"):
        assert promesa not in texto, f"Promete una llamada que no va a ocurrir: «{promesa}»"


def test_en_horario_si_se_avisa_que_van_a_contactar():
    veredicto = safety.evaluar("Tengo un dolor muy fuerte y fiebre alta")
    texto = safety.respuesta_para(veredicto, en_horario=True).lower()

    assert "urgencias" in texto
    assert "contacten" in texto


def test_la_urgencia_manda_a_urgencias_en_cualquier_horario():
    veredicto = safety.evaluar("no puedo respirar")
    for abierto in (True, False):
        assert "urgencias" in safety.respuesta_para(veredicto, abierto).lower()


def test_fuera_de_horario_se_insiste_en_no_esperar():
    veredicto = safety.evaluar("estoy sangrando y no para")
    texto = safety.respuesta_para(veredicto, en_horario=False).lower()
    assert "no espere" in texto or "ahora mismo" in texto


def test_lo_no_urgente_no_cambia_de_texto():
    """Solo la urgencia cambia según el horario."""
    veredicto = safety.evaluar("¿qué me puedo tomar para el dolor?")
    assert (
        safety.respuesta_para(veredicto, True)
        == safety.respuesta_para(veredicto, False)
    )


# ----------------------------------------------------------------------
#  Horario de atención
# ----------------------------------------------------------------------

def test_se_detecta_el_horario_de_atencion(consultorio_abierto_siempre):
    assert en_horario_de_atencion() is True


def test_se_detecta_el_consultorio_cerrado(consultorio_cerrado_siempre):
    assert en_horario_de_atencion() is False


# ----------------------------------------------------------------------
#  Circuito completo
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_el_saludo_fuera_de_horario_atiende_en_vez_de_anunciar_el_cierre(
    telefono, consultorio_cerrado_siempre
):
    """
    Antes el saludo abría diciendo «el consultorio está cerrado». El
    consultorio lo probó y objetó, con razón: el paciente que escribe de
    noche no necesita que le digan que nadie lo va a atender, necesita que
    lo atiendan. El asistente resuelve dudas y agenda igual, y anunciar el
    cierre de entrada espanta justo al que venía a convertirse en cita.

    Lo que sí sigue prohibido fuera de horario es prometer que una persona
    va a contestar. Eso lo cubren las pruebas de más abajo.
    """
    await procesar_mensaje(entrante(telefono, "Hola"))

    texto = " ".join(respuestas(telefono)).lower()
    assert "cerrado" not in texto
    assert "agend" in texto or "ayud" in texto


@pytest.mark.asyncio
async def test_el_saludo_no_menciona_cierre_si_esta_abierto(
    telefono, consultorio_abierto_siempre
):
    await procesar_mensaje(entrante(telefono, "Hola"))
    assert "cerrado" not in " ".join(respuestas(telefono)).lower()


@pytest.mark.asyncio
async def test_urgencia_fuera_de_horario_no_promete_llamada(
    telefono, consultorio_cerrado_siempre
):
    await procesar_mensaje(entrante(
        telefono, "Tengo un dolor muy fuerte del lado derecho y fiebre alta"
    ))

    texto = " ".join(respuestas(telefono)).lower()
    assert "urgencias" in texto
    assert "la contactan" not in texto
    assert conversacion(telefono).estado is EstadoConversacion.REQUIERE_ATENCION


@pytest.mark.asyncio
async def test_fuera_de_horario_igual_se_puede_agendar(
    telefono, consultorio_cerrado_siempre
):
    """
    Un paciente que escribe a las once de la noche debe poder agendar. Si
    el asistente solo dijera «estamos cerrados», se pierde el paciente.
    """
    await procesar_mensaje(entrante(telefono, "Quiero agendar una cita"))

    texto = " ".join(respuestas(telefono)).lower()
    assert "consultorio" in texto or "sede" in texto
    assert conversacion(telefono).estado is EstadoConversacion.BOT
