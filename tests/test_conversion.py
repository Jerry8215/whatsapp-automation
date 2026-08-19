"""
Los fallos que encontró el consultorio probando, y que no pueden volver.

Los cuatro salieron de una misma sesión de pruebas del Dr. Padilla, y su
conclusión fue «dista mucho de lo que acordamos». Tenía razón: el propósito
del asistente no es solo agendar, es atender bien y convertir. Un asistente
que contesta cualquier cosa, o que confirma citas que no existen, hace lo
contrario.

El peor de todos es el primero.
"""

from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from app.brain import flows, intents
from app.db import sesion
from app.models import (
    Cita,
    Conversacion,
    EstadoCita,
    Intencion,
    Mensaje,
    Paciente,
    Remitente,
    RespuestaFrecuente,
    Sede,
)


@pytest.fixture
def conversacion(telefono):
    with sesion() as s:
        p = Paciente(telefono=telefono, nombre="Ana López")
        s.add(p)
        s.commit()
        s.refresh(p)
        c = Conversacion(paciente_id=p.id)
        s.add(c)
        s.commit()
        s.refresh(c)
        s.refresh(p)      # el segundo commit expiró al paciente
        return p, c


def _dijo_el_bot(conversacion_id: int, texto: str) -> None:
    with sesion() as s:
        s.add(Mensaje(conversacion_id=conversacion_id, remitente=Remitente.BOT, texto=texto))
        s.commit()


# ======================================================================
#  1. El «sí» que confirmaba una cita inexistente
# ======================================================================

def test_un_si_despues_de_ofrecer_agendar_arranca_el_agendamiento(conversacion):
    """
    El error más grave que tuvo el sistema. El asistente ofrecía agendar, el
    paciente decía «sí», y se le respondía «queda confirmada, aquí la
    esperamos» sin crear ninguna cita. El paciente se presentaba un día que
    nadie lo esperaba.
    """
    paciente, conv = conversacion
    _dijo_el_bot(conv.id, "¿Le agendo una valoración para que él los revise con usted?")

    salida = flows.atender(
        intencion=Intencion.CONFIRMAR, texto="si",
        paciente=paciente, conversacion=conv,
    )

    assert "queda confirmada" not in salida.texto.lower()
    # Arrancó el agendamiento de verdad: o pregunta la sede, o va a buscar
    # horarios.
    assert salida.paso.startswith("cita:") or salida.opciones or salida.botones


def test_un_si_sin_nada_ofrecido_no_confirma_nada(conversacion):
    paciente, conv = conversacion
    _dijo_el_bot(conv.id, "El consultorio está en Av. Pablo Neruda 3265.")

    salida = flows.atender(
        intencion=Intencion.CONFIRMAR, texto="si",
        paciente=paciente, conversacion=conv,
    )

    assert "queda confirmada" not in salida.texto.lower()
    assert "horario" in salida.texto.lower()


def test_un_si_con_cita_existente_confirma_esa_cita(conversacion):
    """Y dice cuál, para que el paciente pueda detectar un error."""
    paciente, conv = conversacion
    with sesion() as s:
        sede = s.exec(select(Sede).where(Sede.activa).order_by(Sede.orden)).first()  # type: ignore[arg-type]
        cita = Cita(
            paciente_id=paciente.id, sede_id=sede.id,
            inicio=datetime.utcnow() + timedelta(days=2),
            fin=datetime.utcnow() + timedelta(days=2, minutes=30),
            estado=EstadoCita.AGENDADA,
        )
        s.add(cita)
        s.commit()
        s.refresh(cita)
        cita_id = cita.id

    _dijo_el_bot(conv.id, "Le recuerdo su cita.")

    salida = flows.atender(
        intencion=Intencion.CONFIRMAR, texto="si confirmo",
        paciente=paciente, conversacion=conv,
    )

    assert "queda confirmada" in salida.texto.lower()
    # Dice cuál es, para que el paciente pueda detectar un error.
    with sesion() as s:
        guardada = s.get(Cita, cita_id)
    assert flows.fecha_legible(guardada.inicio) in salida.texto

    with sesion() as s:
        assert s.get(Cita, cita_id).estado is EstadoCita.CONFIRMADA


# ======================================================================
#  2. La respuesta frecuente equivocada
# ======================================================================

@pytest.fixture
def frecuentes_cargadas():
    """Las dos que trae el consultorio de fábrica, que se pisaban entre sí."""
    with sesion() as s:
        previas = list(s.exec(select(RespuestaFrecuente)).all())
        for r in previas:
            s.delete(r)
        s.add(RespuestaFrecuente(
            intencion=Intencion.INFORMACION,
            disparadores="documentos,llevar,traer,papeles,requisitos",
            respuesta="Traiga identificación oficial y sus estudios.",
        ))
        s.add(RespuestaFrecuente(
            intencion=Intencion.INFORMACION,
            disparadores="especialidad,que hace,que opera,cirugias",
            respuesta="El Dr. Padilla es Cirujano General y Laparoscópico.",
        ))
        s.commit()
    yield
    with sesion() as s:
        for r in s.exec(select(RespuestaFrecuente)).all():
            s.delete(r)
        s.commit()


def test_contesta_la_respuesta_que_corresponde(frecuentes_cargadas):
    """
    Antes se devolvía siempre la primera cargada, así que a «¿qué opera el
    doctor?» se le contestaba qué documentos llevar. Contestar cualquier
    cosa es peor que no contestar: el paciente cree que le respondieron.
    """
    assert "Cirujano General" in flows.respuesta_guardada(
        Intencion.INFORMACION, "que opera el dr?")
    assert "identificación" in flows.respuesta_guardada(
        Intencion.INFORMACION, "que documentos llevo?")


def test_si_ninguna_coincide_no_se_contesta_cualquiera(frecuentes_cargadas):
    assert flows.respuesta_guardada(Intencion.INFORMACION, "a que hora abren?") == ""


# ======================================================================
#  3. «¿Qué cirugías realiza?»
# ======================================================================

@pytest.mark.parametrize("mensaje", [
    "que cirugias realiza",
    "¿Qué cirugías hace el doctor?",
    "que opera el dr?",
    "que procedimientos realizan",
    "es especialista en que",
    "a que se dedica el doctor",
])
def test_se_reconoce_que_opera_el_doctor(mensaje):
    clasificacion = intents.clasificar(mensaje)
    assert clasificacion.es_confiable, mensaje
    assert clasificacion.intencion is Intencion.INFORMACION, mensaje


# ======================================================================
#  4. El saludo fuera de horario
# ======================================================================

def test_fuera_de_horario_no_abre_diciendo_que_esta_cerrado(conversacion):
    """
    El paciente que escribe de noche no necesita que le digan que nadie lo
    va a atender: necesita que lo atiendan. El asistente puede resolver
    dudas y agendar igual, y anunciar el cierre de entrada espanta al que
    venía a convertirse en cita.
    """
    paciente, conv = conversacion

    salida = flows.atender(
        intencion=Intencion.SALUDO, texto="buenos dias",
        paciente=paciente, conversacion=conv, abierto=False,
    )

    assert "cerrado" not in salida.texto.lower()
    assert "agend" in salida.texto.lower()


def test_dentro_de_horario_saluda_normal(conversacion):
    paciente, conv = conversacion
    salida = flows.atender(
        intencion=Intencion.SALUDO, texto="buenos dias",
        paciente=paciente, conversacion=conv, abierto=True,
    )
    assert "cerrado" not in salida.texto.lower()
    assert "Padilla" in salida.texto
