"""
Pruebas del circuito completo, de mensaje entrante a respuesta enviada.

Los envíos a WhatsApp quedan simulados (sin token configurado), así que
se verifica lo que el sistema GUARDÓ: los mensajes del bot, el estado de
la conversación y el motivo del escalado.
"""

import pytest
from sqlmodel import select

from app.brain.router import procesar_mensaje
from app.db import sesion
from app.models import (
    Conversacion,
    EstadoConversacion,
    Mensaje,
    MotivoEscalado,
    Paciente,
    Remitente,
)
from app.whatsapp.parser import MensajeEntrante


def entrante(telefono: str, texto: str, adjunto: str = "") -> MensajeEntrante:
    return MensajeEntrante(
        wa_message_id=f"wamid.{telefono}.{abs(hash(texto)) % 10**8}",
        telefono=telefono,
        nombre_perfil="Paciente de Prueba",
        texto=texto,
        tipo_adjunto=adjunto,
    )


def respuestas(telefono: str) -> list[str]:
    """Todo lo que el bot le respondió a ese teléfono."""
    with sesion() as s:
        paciente = s.exec(select(Paciente).where(Paciente.telefono == telefono)).first()
        if not paciente:
            return []
        convs = s.exec(
            select(Conversacion).where(Conversacion.paciente_id == paciente.id)
        ).all()
        ids = [c.id for c in convs]
        if not ids:
            return []
        msgs = s.exec(
            select(Mensaje)
            .where(Mensaje.conversacion_id.in_(ids))  # type: ignore[attr-defined]
            .where(Mensaje.remitente == Remitente.BOT)
            .order_by(Mensaje.id)  # type: ignore[arg-type]
        ).all()
    return [m.texto for m in msgs]


def conversacion(telefono: str) -> Conversacion | None:
    with sesion() as s:
        paciente = s.exec(select(Paciente).where(Paciente.telefono == telefono)).first()
        if not paciente:
            return None
        return s.exec(
            select(Conversacion)
            .where(Conversacion.paciente_id == paciente.id)
            .order_by(Conversacion.id.desc())  # type: ignore[attr-defined]
        ).first()


# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_saludo_de_paciente_nuevo(telefono):
    await procesar_mensaje(entrante(telefono, "Hola, buenos días"))

    salidas = respuestas(telefono)
    assert salidas, "El bot no respondió nada"
    assert "Padilla" in salidas[0]
    assert conversacion(telefono).estado is EstadoConversacion.BOT


@pytest.mark.asyncio
async def test_el_aviso_de_privacidad_se_manda_una_sola_vez(telefono):
    await procesar_mensaje(entrante(telefono, "Hola"))
    await procesar_mensaje(entrante(telefono, "¿Dónde están ubicados?"))

    avisos = [t for t in respuestas(telefono) if "no compartimos su información" in t.lower()]
    assert len(avisos) == 1


@pytest.mark.asyncio
async def test_consulta_de_costos_responde_el_precio(telefono):
    await procesar_mensaje(entrante(telefono, "¿Cuánto cuesta la consulta?"))

    texto = " ".join(respuestas(telefono))
    assert "900" in texto
    assert conversacion(telefono).estado is EstadoConversacion.BOT


@pytest.mark.asyncio
async def test_ubicacion_lista_solo_las_sedes_activas(telefono):
    await procesar_mensaje(entrante(telefono, "¿Dónde está el consultorio?"))

    texto = " ".join(respuestas(telefono))
    assert "Providencia" in texto
    assert "Puerta de Hierro" in texto
    assert "Tercera sede" not in texto, "Ofreció una sede desactivada"


@pytest.mark.asyncio
async def test_urgencia_manda_a_urgencias_y_escala(telefono):
    await procesar_mensaje(entrante(
        telefono, "Tengo un dolor muy fuerte del lado derecho y fiebre alta"
    ))

    texto = " ".join(respuestas(telefono)).lower()
    assert "urgencias" in texto

    c = conversacion(telefono)
    assert c.estado is EstadoConversacion.REQUIERE_ATENCION
    assert c.motivo_escalado is MotivoEscalado.POSIBLE_URGENCIA


@pytest.mark.asyncio
async def test_la_urgencia_nunca_se_minimiza(telefono):
    await procesar_mensaje(entrante(telefono, "no puedo respirar bien"))

    texto = " ".join(respuestas(telefono)).lower()
    for frase in ("no se preocupe", "no es nada", "probablemente", "seguramente"):
        assert frase not in texto


@pytest.mark.asyncio
async def test_sintoma_se_deriva_sin_opinar(telefono):
    await procesar_mensaje(entrante(telefono, "¿es normal que la herida se vea rosada?"))

    c = conversacion(telefono)
    assert c.estado is EstadoConversacion.REQUIERE_ATENCION
    assert c.motivo_escalado is MotivoEscalado.CONTENIDO_CLINICO


@pytest.mark.asyncio
async def test_adjunto_se_deriva_sin_abrirse(telefono):
    await procesar_mensaje(entrante(telefono, "Le mando esto", adjunto="image"))

    c = conversacion(telefono)
    assert c.estado is EstadoConversacion.REQUIERE_ATENCION
    texto = " ".join(respuestas(telefono)).lower()
    assert "no lo reviso por este medio" in texto


@pytest.mark.asyncio
async def test_pedir_al_doctor_escala(telefono):
    await procesar_mensaje(entrante(telefono, "quiero hablar con el doctor Padilla"))

    c = conversacion(telefono)
    assert c.estado is EstadoConversacion.REQUIERE_ATENCION
    assert c.motivo_escalado is MotivoEscalado.PIDIO_DOCTOR


@pytest.mark.asyncio
async def test_paciente_molesto_escala(telefono):
    await procesar_mensaje(entrante(
        telefono, "Ya van tres veces que me cambian la cita, no me parece"
    ))

    c = conversacion(telefono)
    assert c.estado is EstadoConversacion.REQUIERE_ATENCION
    assert c.motivo_escalado is MotivoEscalado.MOLESTIA


@pytest.mark.asyncio
async def test_facturacion_va_a_la_asistente(telefono):
    await procesar_mensaje(entrante(telefono, "Necesito una factura de mi consulta"))

    c = conversacion(telefono)
    assert c.motivo_escalado is MotivoEscalado.FACTURACION


@pytest.mark.asyncio
async def test_agendar_pregunta_primero_la_sede(telefono):
    """Nunca se ofrecen horarios antes de saber a qué consultorio va."""
    await procesar_mensaje(entrante(telefono, "Quiero agendar una cita"))

    texto = " ".join(respuestas(telefono)).lower()
    assert "consultorio" in texto or "sede" in texto
    assert conversacion(telefono).paso == "cita:elegir_sede"


@pytest.mark.asyncio
async def test_cuando_una_persona_toma_el_control_el_bot_calla(telefono):
    await procesar_mensaje(entrante(telefono, "Hola"))

    with sesion() as s:
        c = s.get(Conversacion, conversacion(telefono).id)
        c.estado = EstadoConversacion.HUMANO
        s.add(c)
        s.commit()

    antes = len(respuestas(telefono))
    await procesar_mensaje(entrante(telefono, "¿Cuánto cuesta la consulta?"))
    assert len(respuestas(telefono)) == antes, "El bot respondió estando en manos humanas"


@pytest.mark.asyncio
async def test_se_registra_la_fuente_del_paciente(telefono):
    await procesar_mensaje(entrante(telefono, "Hola, los encontré en Doctoralia"))

    with sesion() as s:
        p = s.exec(select(Paciente).where(Paciente.telefono == telefono)).first()
    assert p.fuente == "doctoralia"


@pytest.mark.asyncio
async def test_nunca_se_deja_al_paciente_sin_respuesta(telefono):
    """Aun con algo incomprensible, siempre sale una respuesta."""
    await procesar_mensaje(entrante(telefono, "asdkjhasd qwe zzz"))

    assert respuestas(telefono), "El paciente quedó sin respuesta"


# ----------------------------------------------------------------------
#  Primer contacto
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_al_paciente_nuevo_se_le_presenta_completo(telefono):
    """
    WhatsApp entrega el nombre del perfil desde el primer mensaje, pero eso
    no significa que el consultorio ya lo conozca. Un paciente que escribe
    por primera vez debe recibir la presentación completa: es el momento en
    que se genera la confianza.
    """
    await procesar_mensaje(entrante(telefono, "Hola"))

    texto = " ".join(respuestas(telefono))
    assert "Cirujano General" in texto, "No se presentó ante un paciente nuevo"


@pytest.mark.asyncio
async def test_al_paciente_conocido_se_lo_saluda_por_su_nombre(telefono):
    from datetime import datetime, timedelta

    from app.models import Cita, EstadoCita, Sede

    await procesar_mensaje(entrante(telefono, "Hola"))

    with sesion() as s:
        p = s.exec(select(Paciente).where(Paciente.telefono == telefono)).first()
        p.nombre = "Ana López"
        s.add(p)
        sede = s.exec(select(Sede).where(Sede.activa)).first()
        inicio = datetime.utcnow() - timedelta(days=30)
        s.add(Cita(
            paciente_id=p.id, sede_id=sede.id,
            inicio=inicio, fin=inicio + timedelta(minutes=30),
            estado=EstadoCita.ASISTIO,
        ))
        s.commit()
        # Se cierra la conversación para que el siguiente saludo abra otra.
        c = s.exec(
            select(Conversacion)
            .where(Conversacion.paciente_id == p.id)
            .order_by(Conversacion.id.desc())
        ).first()
        c.cerrada_en = datetime.utcnow()
        s.add(c)
        s.commit()

    antes = len(respuestas(telefono))
    await procesar_mensaje(entrante(telefono, "Buenos días"))

    nuevas = " ".join(respuestas(telefono)[antes:])
    assert "Ana" in nuevas, "No lo saludó por su nombre"
    assert "Cirujano General" not in nuevas, "Se volvió a presentar a un paciente conocido"
