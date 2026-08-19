"""
Baja: «responda BAJA en cualquier momento».

Esa frase va en el aviso de consentimiento que recibe cada paciente en su
primer mensaje. No es una cortesía: es lo que hace válido el consentimiento
bajo la LFPDPPP.

Antes de este módulo la promesa no se cumplía. Un paciente que escribía
BAJA recibía «no le entendí», se le pedía que repitiera, y los
recordatorios le seguían llegando igual.
"""

from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from app.brain import baja
from app.db import sesion
from app.models import Cita, EstadoCita, Paciente, Sede
from app.whatsapp.parser import MensajeEntrante


@pytest.fixture
def enviados(monkeypatch):
    salida = []

    async def enviar(destino, texto, *a, **k):
        salida.append(texto)

    monkeypatch.setattr("app.whatsapp.client.enviar_texto", enviar)
    monkeypatch.setattr("app.whatsapp.client.enviar_lista", enviar)
    monkeypatch.setattr("app.whatsapp.client.enviar_botones", enviar)
    return salida


async def _hablar(telefono, texto, wa_id="wamid.baja"):
    from app.brain import router

    await router.procesar_mensaje(MensajeEntrante(
        telefono=telefono, texto=texto, wa_message_id=wa_id,
        nombre_perfil="Ana López",
    ))


def _paciente(telefono) -> Paciente:
    with sesion() as s:
        return s.exec(select(Paciente).where(Paciente.telefono == telefono)).first()


# ----------------------------------------------------------------------
#  Reconocer el pedido
# ----------------------------------------------------------------------

@pytest.mark.parametrize("mensaje", [
    "BAJA", "baja", "Baja.", "  baja  ",
    "dar de baja", "darme de baja", "quiero la baja",
    "ya no quiero mensajes", "no quiero recibir mas",
    "STOP",
])
def test_reconoce_el_pedido_de_baja(mensaje):
    assert baja.pide_baja(mensaje), mensaje


@pytest.mark.parametrize("mensaje", [
    "me dieron de baja del seguro",
    "ya bajé de peso como me dijo",
    "quiero agendar una cita",
    "¿la clínica está en planta baja?",
    "no quiero ir el jueves, mejor el viernes",
])
def test_no_confunde_otras_frases_con_una_baja(mensaje):
    """
    Darle de baja a alguien que no lo pidió lo deja sin recordatorios sin
    que se entere. Por eso se exige que el mensaje sea prácticamente solo
    ese pedido.
    """
    assert not baja.pide_baja(mensaje), mensaje


# ----------------------------------------------------------------------
#  Cumplirlo
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_el_paciente_recibe_confirmacion_y_queda_de_baja(enviados, telefono):
    await _hablar(telefono, "BAJA")

    paciente = _paciente(telefono)
    assert paciente.baja_en is not None
    assert enviados, "no se le confirmó nada al paciente"
    assert "ALTA" in enviados[-1], "no se le dijo cómo volver"


@pytest.mark.asyncio
async def test_no_termina_en_la_bandeja_como_si_no_se_entendiera(enviados, telefono):
    """
    Antes, «BAJA» no lo reconocía ninguna regla y la conversación acababa
    derivada a una persona. Es un trámite, no algo que requiera criterio.
    """
    from app.models import Conversacion, EstadoConversacion

    await _hablar(telefono, "baja")

    paciente = _paciente(telefono)
    with sesion() as s:
        conversacion = s.exec(
            select(Conversacion).where(Conversacion.paciente_id == paciente.id)
        ).first()

    assert conversacion.estado is not EstadoConversacion.REQUIERE_ATENCION
    assert not any("no logré entenderle" in t for t in enviados)


@pytest.mark.asyncio
async def test_avisa_al_consultorio(enviados, telefono, monkeypatch):
    avisos = []

    async def avisar_falso(**kwargs):
        avisos.append(kwargs)

    monkeypatch.setattr("app.brain.router.avisar", avisar_falso)

    await _hablar(telefono, "BAJA")

    assert avisos, "el consultorio no se enteró"
    assert "baja" in avisos[0]["cuerpo"].lower()


@pytest.mark.asyncio
async def test_con_alta_vuelve_a_recibir(enviados, telefono):
    await _hablar(telefono, "BAJA", wa_id="wamid.baja.1")
    assert _paciente(telefono).baja_en is not None

    await _hablar(telefono, "ALTA", wa_id="wamid.baja.2")
    assert _paciente(telefono).baja_en is None


@pytest.mark.asyncio
async def test_si_vuelve_a_escribir_se_le_sigue_atendiendo(enviados, telefono):
    """
    La baja es sobre los mensajes que inicia el consultorio. Si el paciente
    escribe, fue él quien buscó el contacto: dejarlo sin respuesta sería
    castigarlo por ejercer un derecho.
    """
    await _hablar(telefono, "BAJA", wa_id="wamid.baja.3")
    cuantos = len(enviados)

    await _hablar(telefono, "¿Cuánto cuesta la consulta?", wa_id="wamid.baja.4")

    assert len(enviados) > cuantos
    assert "900" in enviados[-1]


# ----------------------------------------------------------------------
#  Lo que de verdad importa: que dejen de salir los recordatorios
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_se_le_manda_el_recordatorio(enviados, telefono):
    from app.recordatorios import enviar_pendientes

    with sesion() as s:
        sede = s.exec(select(Sede).where(Sede.activa).order_by(Sede.orden)).first()  # type: ignore[arg-type]
        paciente = Paciente(telefono=telefono, nombre="Ana López")
        s.add(paciente)
        s.commit()
        s.refresh(paciente)
        cita = Cita(
            paciente_id=paciente.id, sede_id=sede.id,
            inicio=datetime.utcnow() + timedelta(hours=23),
            fin=datetime.utcnow() + timedelta(hours=23, minutes=30),
            estado=EstadoCita.AGENDADA,
        )
        s.add(cita)
        s.commit()
        s.refresh(cita)
        cita_id = cita.id
        paciente_id = paciente.id

    baja.dar_de_baja(paciente_id)
    await enviar_pendientes()

    with sesion() as s:
        cita = s.get(Cita, cita_id)

    # La cita sigue en pie: lo que no sale es el mensaje.
    assert cita.estado is EstadoCita.AGENDADA
    assert "baja" in cita.notas.lower()
    assert not any("recordatorio" in t.lower() for t in enviados)


@pytest.mark.asyncio
async def test_un_paciente_activo_si_recibe_el_recordatorio(enviados, telefono):
    """El control de la prueba anterior: sin baja, el recordatorio sale."""
    from app.recordatorios import enviar_pendientes

    with sesion() as s:
        sede = s.exec(select(Sede).where(Sede.activa).order_by(Sede.orden)).first()  # type: ignore[arg-type]
        paciente = Paciente(telefono=telefono, nombre="Luis Pérez")
        s.add(paciente)
        s.commit()
        s.refresh(paciente)
        s.add(Cita(
            paciente_id=paciente.id, sede_id=sede.id,
            inicio=datetime.utcnow() + timedelta(hours=23),
            fin=datetime.utcnow() + timedelta(hours=23, minutes=30),
            estado=EstadoCita.AGENDADA,
        ))
        s.commit()
        paciente_id = paciente.id

    assert await enviar_pendientes() >= 1

    with sesion() as s:
        cita = s.exec(select(Cita).where(Cita.paciente_id == paciente_id)).first()
    assert cita.recordatorio_enviado_en is not None


def test_queda_registrado_quien_pidio_la_baja(telefono):
    from app.models import RegistroAuditoria

    with sesion() as s:
        p = Paciente(telefono=telefono, nombre="Ana López")
        s.add(p)
        s.commit()
        s.refresh(p)
        paciente_id = p.id

    baja.dar_de_baja(paciente_id)

    with sesion() as s:
        registros = [r for r in s.exec(select(RegistroAuditoria)).all()
                     if r.accion == "paciente.baja"]
    assert any(r.entidad_id == paciente_id for r in registros)
