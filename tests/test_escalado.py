"""
Pruebas de cuándo se deriva a una persona — y, sobre todo, de cuándo NO.

Un asistente que deriva de más satura la bandeja de la asistente, y una
bandeja saturada se deja de mirar. Cuando eso pasa, las derivaciones que
sí importan (una urgencia, un paciente molesto) se pierden entre el ruido.

Por eso hay tantas pruebas de lo que NO debe escalar como de lo que sí.
"""

import pytest
from sqlmodel import select

from app.brain.intents import clasificar
from app.brain.router import procesar_mensaje
from app.db import sesion
from app.models import (
    Conversacion,
    EstadoConversacion,
    Intencion,
    MotivoEscalado,
    Paciente,
)
from app.whatsapp.parser import MensajeEntrante


def entrante(telefono: str, texto: str) -> MensajeEntrante:
    return MensajeEntrante(
        wa_message_id=f"wamid.{telefono}.{abs(hash(texto)) % 10**8}",
        telefono=telefono,
        nombre_perfil="Paciente",
        texto=texto,
    )


def estado(telefono: str) -> Conversacion | None:
    with sesion() as s:
        p = s.exec(select(Paciente).where(Paciente.telefono == telefono)).first()
        if not p:
            return None
        return s.exec(
            select(Conversacion)
            .where(Conversacion.paciente_id == p.id)
            .order_by(Conversacion.id.desc())  # type: ignore[attr-defined]
        ).first()


# ----------------------------------------------------------------------
#  Lo que SÍ debe llegar a una persona
# ----------------------------------------------------------------------

@pytest.mark.parametrize("mensaje,motivo", [
    ("Tengo un dolor muy fuerte y fiebre alta", MotivoEscalado.POSIBLE_URGENCIA),
    ("¿Es normal que la herida se vea rosada?", MotivoEscalado.CONTENIDO_CLINICO),
    ("Quiero hablar con el doctor Padilla", MotivoEscalado.PIDIO_DOCTOR),
    ("Ya van tres veces que me cambian la cita, no me parece", MotivoEscalado.MOLESTIA),
    ("Necesito una factura", MotivoEscalado.FACTURACION),
])
@pytest.mark.asyncio
async def test_estos_casos_llegan_a_una_persona(telefono, mensaje, motivo):
    await procesar_mensaje(entrante(telefono, mensaje))
    c = estado(telefono)
    assert c.estado is EstadoConversacion.REQUIERE_ATENCION
    assert c.motivo_escalado is motivo


# ----------------------------------------------------------------------
#  Lo que NO debe molestar a nadie
# ----------------------------------------------------------------------

@pytest.mark.parametrize("mensaje", [
    "Hola, buenos días",
    "Buenas tardes",
    "Hola, los encontré en Doctoralia",
    "Buen día, los vi en Google",
    "Hola, me recomendó un conocido",
    "¿Cuánto cuesta la consulta?",
    "¿Dónde está el consultorio?",
    "¿Qué horarios manejan?",
    "¿Qué días atienden?",
    "¿A qué hora abren?",
    "Quiero agendar una cita",
    "¿Qué documentos llevo?",
])
@pytest.mark.asyncio
async def test_lo_rutinario_lo_resuelve_el_asistente(telefono, mensaje):
    await procesar_mensaje(entrante(telefono, mensaje))
    c = estado(telefono)
    assert c.estado is EstadoConversacion.BOT, (
        f"Derivó de más: {mensaje!r} → {c.motivo_escalado}"
    )


@pytest.mark.asyncio
async def test_al_primer_tropiezo_se_pide_aclaracion_sin_derivar(telefono):
    """Un mensaje incomprensible no debe paginar a nadie de entrada."""
    await procesar_mensaje(entrante(telefono, "zzz qqq xyz"))

    c = estado(telefono)
    assert c.estado is EstadoConversacion.BOT
    assert c.intentos_fallidos == 1


@pytest.mark.asyncio
async def test_al_segundo_tropiezo_si_se_deriva(telefono):
    await procesar_mensaje(entrante(telefono, "zzz qqq xyz"))
    await procesar_mensaje(entrante(telefono, "wwww vvvv uuuu"))

    c = estado(telefono)
    assert c.estado is EstadoConversacion.REQUIERE_ATENCION
    assert c.motivo_escalado is MotivoEscalado.NO_COMPRENDIDO


@pytest.mark.asyncio
async def test_un_acierto_borra_los_tropiezos_previos(telefono):
    """Si el paciente se explica, la cuenta vuelve a cero."""
    await procesar_mensaje(entrante(telefono, "zzz qqq xyz"))
    await procesar_mensaje(entrante(telefono, "¿Cuánto cuesta la consulta?"))
    await procesar_mensaje(entrante(telefono, "mmmm nnnn"))

    c = estado(telefono)
    assert c.estado is EstadoConversacion.BOT, "Derivó pese a haber acertado en medio"


# ----------------------------------------------------------------------
#  Clasificación
# ----------------------------------------------------------------------

@pytest.mark.parametrize("mensaje", [
    "Hola",
    "Buenos días",
    "Hola, buenos días",
    "Buenas tardes doctor",
    "Hola, los encontré en Doctoralia",
    "Buen día, una pregunta",
])
def test_un_saludo_se_reconoce_aunque_traiga_algo_pegado(mensaje):
    c = clasificar(mensaje)
    assert c.intencion is Intencion.SALUDO
    assert c.es_confiable


def test_un_saludo_con_intencion_real_gana_la_intencion(telefono):
    """«Hola, quiero agendar» es una cita, no un saludo."""
    assert clasificar("Hola, quiero agendar una cita").intencion is Intencion.CITA
    assert clasificar("Buenos días, ¿cuánto cuesta?").intencion is Intencion.COSTOS


# ----------------------------------------------------------------------
#  Redacción de la respuesta de costos
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_el_precio_no_se_repite_si_es_el_mismo_en_todas_las_sedes(telefono):
    from app.models import Sede

    with sesion() as s:
        for sede in s.exec(select(Sede).where(Sede.activa)).all():
            sede.precio_valoracion = 900
            s.add(sede)
        s.commit()

    await procesar_mensaje(entrante(telefono, "¿Cuánto cuesta la consulta?"))

    from tests.test_pipeline import respuestas
    texto = " ".join(respuestas(telefono))
    assert texto.count("900") == 1, "Repitió el mismo precio una vez por sede"
