"""
«¿A qué hora es mi cita?»

Lo probó el consultorio y el asistente contestó «no le entendí». Era una
pregunta que se responde sola —el dato está en la base— y terminaba
derivada a una persona después de hacérsela repetir dos veces.

Es de lo primero que pregunta un paciente ya agendado, así que se responde
sin IA: tiene que funcionar también en modo básico y sin costo.
"""

from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from app.brain import flows
from app.db import sesion
from app.models import Cita, EstadoCita, Paciente, Sede


@pytest.fixture
def paciente_con_cita(telefono):
    with sesion() as s:
        sede = s.exec(select(Sede).where(Sede.activa).order_by(Sede.orden)).first()  # type: ignore[arg-type]
        p = Paciente(telefono=telefono, nombre="Ana López")
        s.add(p)
        s.commit()
        s.refresh(p)
        cita = Cita(
            paciente_id=p.id, sede_id=sede.id,
            inicio=datetime.utcnow() + timedelta(days=3, hours=1),
            fin=datetime.utcnow() + timedelta(days=3, hours=1, minutes=30),
            estado=EstadoCita.AGENDADA,
        )
        s.add(cita)
        s.commit()
        s.refresh(p)
        return p


@pytest.fixture
def paciente_sin_cita(telefono):
    with sesion() as s:
        p = Paciente(telefono=telefono, nombre="Luis Pérez")
        s.add(p)
        s.commit()
        s.refresh(p)
        return p


# ----------------------------------------------------------------------
#  Reconocer la pregunta
# ----------------------------------------------------------------------

@pytest.mark.parametrize("mensaje", [
    "¿A qué hora es mi cita?",
    "a que hora tengo la cita",
    "cuando es mi cita?",
    "que dia es mi consulta",
    "oiga y mi cita cuando es",
    "cuando me toca",
    "quiero confirmar mi cita",
    "me recuerda mi cita porfa",
    "a que hora quedo mi consulta",
])
def test_reconoce_la_pregunta(mensaje):
    assert flows.pregunta_por_su_cita(mensaje), mensaje


@pytest.mark.parametrize("mensaje", [
    "Quiero agendar una cita",
    "quisiera sacar una cita",
    "¿Cuánto cuesta la consulta?",
    "¿Dónde están ubicados?",
    "necesito agendar una consulta",
])
def test_no_confunde_con_pedir_una_cita_nueva(mensaje):
    """
    Quien quiere agendar no está preguntando por una que ya tiene. Si se
    confundieran, al paciente nuevo se le diría que no tiene ninguna cita.
    """
    assert not flows.pregunta_por_su_cita(mensaje), mensaje


# ----------------------------------------------------------------------
#  Responderla
# ----------------------------------------------------------------------

def test_le_dice_cuando_es_y_donde(paciente_con_cita):
    from app.models import Conversacion

    salida = flows.atender(
        intencion=flows.Intencion.DESCONOCIDA,
        texto="¿A qué hora es mi cita?",
        paciente=paciente_con_cita,
        conversacion=Conversacion(paciente_id=paciente_con_cita.id),
    )

    assert salida.resuelto and not salida.vacio
    cita = flows.proxima_cita(paciente_con_cita)
    assert flows.fecha_legible(cita["inicio"]) in salida.texto
    assert cita["sede"] in salida.texto


def test_ofrece_confirmar_o_reprogramar(paciente_con_cita):
    from app.models import Conversacion

    salida = flows.atender(
        intencion=flows.Intencion.DESCONOCIDA,
        texto="cuando es mi cita",
        paciente=paciente_con_cita,
        conversacion=Conversacion(paciente_id=paciente_con_cita.id),
    )
    payloads = [p for p, _ in salida.botones]
    assert "confirmar" in payloads
    assert "reprogramar" in payloads


def test_sin_cita_lo_dice_y_ofrece_agendar(paciente_sin_cita):
    from app.models import Conversacion

    salida = flows.atender(
        intencion=flows.Intencion.DESCONOCIDA,
        texto="¿a qué hora es mi cita?",
        paciente=paciente_sin_cita,
        conversacion=Conversacion(paciente_id=paciente_sin_cita.id),
    )

    assert "No encuentro" in salida.texto
    assert "horario" in salida.texto


def test_no_se_confunde_con_una_cita_ya_pasada(paciente_con_cita):
    """Una cita de la semana pasada no es «su próxima cita»."""
    with sesion() as s:
        cita = s.exec(
            select(Cita).where(Cita.paciente_id == paciente_con_cita.id)
        ).first()
        cita.inicio = datetime.utcnow() - timedelta(days=7)
        cita.fin = cita.inicio + timedelta(minutes=30)
        s.add(cita)
        s.commit()

    assert flows.proxima_cita(paciente_con_cita) is None


def test_una_cita_cancelada_no_cuenta(paciente_con_cita):
    with sesion() as s:
        cita = s.exec(
            select(Cita).where(Cita.paciente_id == paciente_con_cita.id)
        ).first()
        cita.estado = EstadoCita.CANCELADA
        s.add(cita)
        s.commit()

    assert flows.proxima_cita(paciente_con_cita) is None


# ----------------------------------------------------------------------
#  Y que la IA también lo sepa
# ----------------------------------------------------------------------

def test_la_cita_viaja_en_el_contexto_de_la_ia(paciente_con_cita):
    """
    Si el modelo no recibe la cita, o dice que no sabe o se la inventa. Las
    dos cosas son malas; la segunda es peor.
    """
    contexto = flows.contexto_paciente(paciente_con_cita)
    cita = flows.proxima_cita(paciente_con_cita)

    assert "TIENE UNA CITA AGENDADA" in contexto
    assert flows.fecha_legible(cita["inicio"]) in contexto
    assert "No inventes" in contexto


def test_sin_cita_el_contexto_lo_dice_explicitamente(paciente_sin_cita):
    contexto = flows.contexto_paciente(paciente_sin_cita)
    assert "No tiene ninguna cita agendada" in contexto
