"""
El circuito completo de un mensaje entrante.

Orden fijo, y el orden es lo importante:

    1. Guardar el mensaje                (nunca se pierde nada)
    2. ¿La lleva una persona?            → no responder, solo avisar
    3. BARRERA CLÍNICA                   → antes que todo lo demás
    4. Clasificar intención              (reglas, costo cero)
    5. ¿Hay que escalar?                 → derivar y avisar
    6. Flujos determinísticos            → resuelto sin costo
    7. IA, solo si el modo lo permite y hay presupuesto
    8. Si nada resolvió                  → derivar a una persona

La IA nunca ve un mensaje que la barrera clínica bloqueó. Ese es el
invariante del sistema.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from sqlmodel import select

from app.brain import ai, escalation, flows, intents, safety
from app.config import config
from app.db import sesion
from app.models import (
    Conversacion,
    EstadoConversacion,
    Intencion,
    Mensaje,
    ModoAsistente,
    Paciente,
    RegistroAuditoria,
    Remitente,
    Sede,
)
from app.notify import avisar
from app.whatsapp import client
from app.whatsapp.parser import EstadoEntrega, MensajeEntrante

log = logging.getLogger(__name__)

HORAS_CONVERSACION_NUEVA = 6

AVISO_CONSENTIMIENTO = (
    "Para atenderle por este medio guardamos su nombre, teléfono y sus citas, "
    "y le enviamos recordatorios. No compartimos su información con terceros. "
    "Si prefiere que no le escribamos, responda BAJA en cualquier momento."
)

NO_ENTENDI = (
    "Disculpe, no logré entenderle bien. Permítame comunicarla con el equipo "
    "del consultorio para que la atiendan personalmente."
)

# Primer tropiezo: se pide una aclaración en lugar de molestar a una
# persona. Derivar cada mensaje que no se entiende satura la bandeja de la
# asistente, y una bandeja saturada se deja de mirar — con lo cual las
# derivaciones que sí importan se pierden.
PEDIR_ACLARACION = (
    "Disculpe, no estoy segura de haber entendido. ¿Me ayuda diciéndome si "
    "busca agendar una cita, conocer los costos, la ubicación del consultorio, "
    "o si es otra cosa?"
)


# ======================================================================
#  Entrada
# ======================================================================

async def procesar_mensaje(entrante: MensajeEntrante) -> None:
    try:
        await _procesar(entrante)
    except Exception:
        log.exception("Falló el procesamiento del mensaje %s", entrante.wa_message_id)
        # Nunca se deja al paciente sin respuesta.
        try:
            await client.enviar_texto(entrante.telefono, NO_ENTENDI)
        except Exception:
            log.exception("Tampoco se pudo enviar el mensaje de respaldo")


async def _procesar(entrante: MensajeEntrante) -> None:
    paciente = _paciente(entrante)
    conversacion = _conversacion(paciente)

    _guardar(conversacion.id, Remitente.PACIENTE, entrante.texto,
             wa_id=entrante.wa_message_id, adjunto=entrante.tipo_adjunto)

    # --- 2. ya la lleva una persona -------------------------------------
    if conversacion.estado is EstadoConversacion.HUMANO:
        log.info("Conversación %s en manos de una persona; el bot no responde",
                 conversacion.id)
        return

    # --- 2b. respuesta a un botón ----------------------------------------
    # Los botones son entrada estructurada, no texto libre: el paciente
    # eligió una opción que nosotros le ofrecimos.
    if entrante.respuesta_id:
        if await _atender_boton(entrante, paciente, conversacion):
            return

    # --- 3. barrera clínica ---------------------------------------------
    veredicto = safety.evaluar(entrante.texto, entrante.tipo_adjunto)

    # --- 4. intención ----------------------------------------------------
    clasificacion = intents.clasificar(entrante.texto)

    if not paciente.fuente:
        fuente = intents.detectar_fuente(entrante.texto)
        if fuente:
            _actualizar_paciente(paciente.id, fuente=fuente)

    # --- 5. escalado -----------------------------------------------------
    decision = escalation.decidir(
        veredicto=veredicto,
        clasificacion=clasificacion,
        texto=entrante.texto,
        intentos_fallidos=conversacion.intentos_fallidos,
        abierta_en=conversacion.abierta_en,
    )

    if decision.escalar:
        # Si la barrera clínica dictó una respuesta, se envía ESA, tal cual.
        # No la genera un modelo ni se improvisa.
        respuesta = veredicto.respuesta or escalation.MENSAJE_TRANSICION
        await _responder(conversacion.id, paciente.telefono, respuesta)
        await _escalar(conversacion, paciente, decision)
        return

    # --- 6. flujos --------------------------------------------------------
    salida = flows.atender(
        intencion=clasificacion.intencion if clasificacion.es_confiable else Intencion.DESCONOCIDA,
        texto=entrante.texto,
        paciente=paciente,
        conversacion=conversacion,
    )

    if salida.paso == "cita:buscar_horarios":
        salida = await _buscar_horarios(salida, conversacion)
    elif conversacion.paso == "cita:elegir_horario":
        salida = await _reservar(entrante.texto, paciente, conversacion)

    if salida.resuelto and not salida.vacio:
        await _enviar_salida(conversacion, paciente, salida, clasificacion.intencion)
        return

    # --- 7. IA ------------------------------------------------------------
    if _modo() is not ModoAsistente.BASICO:
        respuesta_ia = await ai.responder(
            mensaje=entrante.texto,
            contexto_consultorio=flows.contexto_para_ia(),
            contexto_paciente=flows.contexto_paciente(paciente),
            historial=_historial(conversacion.id),
        )
        if respuesta_ia and respuesta_ia.texto:
            await _responder(
                conversacion.id, paciente.telefono, respuesta_ia.texto,
                ia=True, uso=respuesta_ia,
            )
            _tocar(conversacion.id, intencion=clasificacion.intencion, reiniciar_intentos=True)
            return

    # --- 8. nadie pudo ----------------------------------------------------
    # Al primer tropiezo se pide una aclaración. Solo se deriva cuando ya se
    # intentó las veces acordadas: así lo que llega a la bandeja de la
    # asistente es lo que de verdad necesita a una persona.
    _sumar_intento(conversacion.id)
    intentos = conversacion.intentos_fallidos + 1

    if intentos < escalation.INTENTOS_ANTES_DE_DERIVAR:
        await _responder(conversacion.id, paciente.telefono, PEDIR_ACLARACION)
        return

    await _responder(conversacion.id, paciente.telefono, NO_ENTENDI)
    await _escalar(conversacion, paciente, escalation.Decision(
        escalar=True,
        motivo=escalation.MotivoEscalado.NO_COMPRENDIDO,
        aviso=f"El asistente no logró resolver la consulta en {intentos} intentos.",
    ))


async def registrar_estado(estado: EstadoEntrega) -> None:
    """Acuses de entrega. Un 'failed' repetido conviene mirarlo."""
    if estado.estado == "failed":
        log.warning("Envío fallido a %s: %s", estado.telefono, estado.error)
        with sesion() as s:
            s.add(RegistroAuditoria(
                actor="whatsapp",
                accion="mensaje.fallido",
                detalle=f"{estado.telefono}: {estado.error}",
            ))
            s.commit()


# ======================================================================
#  Botones
# ======================================================================

async def _atender_boton(
    entrante: MensajeEntrante, paciente: Paciente, conversacion: Conversacion
) -> bool:
    """
    Atiende el toque de un botón. Devuelve True si lo resolvió.

    Si el identificador no es de los nuestros, devuelve False y el mensaje
    sigue el circuito normal — el paciente pudo haber escrito el texto del
    botón a mano.
    """
    from app.recordatorios import responder_boton

    payload = entrante.respuesta_id

    # Botones de la plantilla de recordatorio.
    respuesta = await responder_boton(paciente.telefono, payload)
    if respuesta:
        await _responder(conversacion.id, paciente.telefono, respuesta)
        _tocar(
            conversacion.id,
            intencion=Intencion.CONFIRMAR if "confirm" in payload else Intencion.CANCELAR,
            paso="cita:elegir_horario" if "reprogram" in payload else "",
            contexto=_contexto_reprogramacion(paciente) if "reprogram" in payload else {},
            reiniciar_intentos=True,
        )
        return True

    # Botones del flujo de cancelación.
    if payload == "cancelar":
        await _cancelar_cita(paciente, conversacion)
        return True

    if payload == "reprogramar":
        contexto = _contexto_reprogramacion(paciente)
        if not contexto.get("sede_id"):
            await _responder(
                conversacion.id, paciente.telefono,
                "No encuentro una cita próxima a su nombre. Permítame "
                "comunicarla con el consultorio.",
            )
            await _escalar(conversacion, paciente, escalation.Decision(
                escalar=True,
                motivo=escalation.MotivoEscalado.NO_COMPRENDIDO,
                aviso="Pidió reprogramar pero no se encontró su cita.",
            ))
            return True

        salida = await _buscar_horarios(
            flows.Salida(contexto=contexto, paso="cita:buscar_horarios"), conversacion
        )
        if salida.resuelto and not salida.vacio:
            await _enviar_salida(conversacion, paciente, salida, Intencion.CANCELAR)
            return True

    return False


def _contexto_reprogramacion(paciente: Paciente) -> dict:
    from app.recordatorios import _proxima_cita

    cita = _proxima_cita(paciente.telefono)
    if not cita:
        return {}
    return {"sede_id": cita.sede_id, "reprogramando": cita.id}


async def _cancelar_cita(paciente: Paciente, conversacion: Conversacion) -> None:
    from app.agenda.service import cancelar, proveedor
    from app.recordatorios import _proxima_cita

    cita = _proxima_cita(paciente.telefono)
    if not cita:
        await _responder(
            conversacion.id, paciente.telefono,
            "No encuentro una cita próxima a su nombre. Permítame comunicarla "
            "con el consultorio para revisarlo.",
        )
        return

    await cancelar(cita.id, por="paciente")  # type: ignore[arg-type]

    texto = (
        f"Listo, cancelé su cita del {flows.fecha_legible(cita.inicio)}.\n\n"
        f"Cuando quiera reagendar, escríbame y con gusto le busco un espacio."
    )
    await _responder(conversacion.id, paciente.telefono, texto)
    _marcar_perdida(conversacion.id, "Canceló la cita")

    # Con el Plan B no se puede escribir en Doctoralia: hay que avisarle a
    # la asistente para que libere el cupo allá.
    if not proveedor().escribe_en_doctoralia:
        await avisar(
            titulo=paciente.nombre or paciente.telefono,
            cuerpo=(
                f"Canceló su cita del {flows.fecha_legible(cita.inicio)}. "
                f"Hay que retirarla de Doctoralia a mano."
            ),
            conversacion_id=conversacion.id,
        )


def _marcar_perdida(conversacion_id: int | None, motivo: str) -> None:
    if conversacion_id is None:
        return
    with sesion() as s:
        c = s.get(Conversacion, conversacion_id)
        if c and not c.motivo_perdida:
            c.motivo_perdida = motivo
            s.add(c)
            s.commit()


# ======================================================================
#  Agendamiento
# ======================================================================

async def _buscar_horarios(salida: flows.Salida, conversacion: Conversacion) -> flows.Salida:
    from app.agenda.service import ofrecer_horarios

    sede_id = salida.contexto.get("sede_id")
    if not sede_id:
        return flows.SIN_RESOLVER

    huecos = await ofrecer_horarios(sede_id, cantidad=3)

    if not huecos:
        return flows.Salida(texto=(
            "En este momento no tengo horarios libres en los próximos días. "
            "Permítame comunicarla con el consultorio para buscarle un espacio."
        ), resuelto=False)

    listado = "\n".join(f"· {flows.fecha_legible(h.inicio)}" for h in huecos)
    return flows.Salida(
        texto=f"Tengo estos horarios disponibles:\n\n{listado}\n\n¿Cuál prefiere?",
        opciones=[
            (f"hora:{h.inicio.isoformat()}", flows.fecha_legible(h.inicio), "")
            for h in huecos
        ],
        paso="cita:elegir_horario",
        contexto={**salida.contexto, "ofrecidos": [h.inicio.isoformat() for h in huecos]},
    )


async def _reservar(
    texto: str, paciente: Paciente, conversacion: Conversacion
) -> flows.Salida:
    from app.agenda.base import CupoYaOcupado
    from app.agenda.service import agendar, ofrecer_horarios

    try:
        contexto = json.loads(conversacion.contexto or "{}")
    except json.JSONDecodeError:
        contexto = {}

    sede_id = contexto.get("sede_id")
    inicio = _horario_elegido(texto, contexto.get("ofrecidos", []))

    if not sede_id or not inicio:
        return flows.Salida(
            texto="¿Me confirma cuál de los horarios le acomoda?",
            opciones=[
                (f"hora:{h}", flows.fecha_legible(datetime.fromisoformat(h)), "")
                for h in contexto.get("ofrecidos", [])
            ],
            paso="cita:elegir_horario",
            contexto=contexto,
        )

    try:
        cita = await agendar(
            paciente_id=paciente.id,  # type: ignore[arg-type]
            sede_id=sede_id,
            inicio=inicio,
            motivo=paciente.motivo_consulta,
        )
    except CupoYaOcupado:
        # Alguien reservó ese hueco entre que se ofreció y que eligió — pudo
        # ser el widget del sitio web. Al paciente no se le devuelve un error:
        # se le ofrecen alternativas y sigue el flujo.
        huecos = await ofrecer_horarios(sede_id, cantidad=3)
        if not huecos:
            return flows.SIN_RESOLVER
        listado = "\n".join(f"· {flows.fecha_legible(h.inicio)}" for h in huecos)
        return flows.Salida(
            texto=(
                f"Ese horario se acaba de ocupar. Tengo estos disponibles:\n\n"
                f"{listado}\n\n¿Alguno le sirve?"
            ),
            opciones=[
                (f"hora:{h.inicio.isoformat()}", flows.fecha_legible(h.inicio), "")
                for h in huecos
            ],
            paso="cita:elegir_horario",
            contexto={**contexto, "ofrecidos": [h.inicio.isoformat() for h in huecos]},
        )

    with sesion() as s:
        sede = s.get(Sede, sede_id)

    texto_ok = (
        f"Listo, su cita quedó agendada:\n\n"
        f"📅 {flows.fecha_legible(cita.inicio)}\n"
        f"📍 {sede.nombre}\n"
        f"{sede.direccion}"
    )
    if sede.mapa_url:
        texto_ok += f"\n{sede.mapa_url}"
    texto_ok += "\n\nUn día antes le envío un recordatorio."
    if sede.referencias:
        texto_ok += f"\n\n{sede.referencias}"

    _actualizar_paciente(paciente.id, sede_preferida_id=sede_id)
    _marcar_conversion(conversacion.id)

    return flows.Salida(texto=texto_ok, paso="", contexto={})


def _horario_elegido(texto: str, ofrecidos: list[str]) -> datetime | None:
    t = texto.strip()
    if t.startswith("hora:"):
        try:
            return datetime.fromisoformat(t.removeprefix("hora:"))
        except ValueError:
            return None
    # El paciente escribió el horario en palabras: se busca entre los
    # ofrecidos, no se interpreta libremente. Nunca se agenda algo que no
    # se le mostró.
    normalizado = safety.normalizar(t)
    for iso in ofrecidos:
        dt = datetime.fromisoformat(iso)
        if f"{dt.hour}:{dt.minute:02d}" in normalizado or f"{dt:%H:%M}" in normalizado:
            return dt
        if str(dt.day) in normalizado and flows.DIAS[dt.weekday()] in normalizado:
            return dt
    return None


# ======================================================================
#  Persistencia y envío
# ======================================================================

def _paciente(entrante: MensajeEntrante) -> Paciente:
    with sesion() as s:
        p = s.exec(
            select(Paciente).where(Paciente.telefono == entrante.telefono)
        ).first()
        if not p:
            p = Paciente(
                telefono=entrante.telefono,
                nombre=entrante.nombre_perfil or "",
                consentimiento_en=datetime.utcnow(),
            )
            s.add(p)
            s.add(RegistroAuditoria(
                actor="bot", accion="paciente.alta",
                detalle=f"Nuevo contacto {entrante.telefono}",
            ))
        else:
            p.ultima_interaccion = datetime.utcnow()
            if not p.nombre and entrante.nombre_perfil:
                p.nombre = entrante.nombre_perfil
            s.add(p)
        s.commit()
        s.refresh(p)
        return p


def _conversacion(paciente: Paciente) -> Conversacion:
    corte = datetime.utcnow() - timedelta(hours=HORAS_CONVERSACION_NUEVA)
    with sesion() as s:
        c = s.exec(
            select(Conversacion)
            .where(
                Conversacion.paciente_id == paciente.id,
                Conversacion.cerrada_en.is_(None),  # type: ignore[union-attr]
                Conversacion.ultima_actividad >= corte,
            )
            .order_by(Conversacion.ultima_actividad.desc())  # type: ignore[attr-defined]
        ).first()
        if not c:
            c = Conversacion(paciente_id=paciente.id)  # type: ignore[arg-type]
            s.add(c)
            s.commit()
            s.refresh(c)
        return c


def _guardar(
    conversacion_id: int | None,
    remitente: Remitente,
    texto: str,
    *,
    wa_id: str = "",
    adjunto: str = "",
    ia: bool = False,
    uso: ai.RespuestaIA | None = None,
) -> None:
    if conversacion_id is None:
        return
    with sesion() as s:
        s.add(Mensaje(
            conversacion_id=conversacion_id,
            remitente=remitente,
            texto=texto,
            wa_message_id=wa_id,
            tipo_adjunto=adjunto,
            generado_por_ia=ia,
            tokens_entrada=uso.tokens_entrada if uso else 0,
            tokens_salida=uso.tokens_salida if uso else 0,
            costo_usd=uso.costo_usd if uso else 0.0,
        ))
        c = s.get(Conversacion, conversacion_id)
        if c:
            c.ultima_actividad = datetime.utcnow()
            s.add(c)
        s.commit()


async def _responder(
    conversacion_id: int | None,
    telefono: str,
    texto: str,
    *,
    ia: bool = False,
    uso: ai.RespuestaIA | None = None,
) -> None:
    await client.enviar_texto(telefono, texto)
    _guardar(conversacion_id, Remitente.BOT, texto, ia=ia, uso=uso)


async def _enviar_salida(
    conversacion: Conversacion,
    paciente: Paciente,
    salida: flows.Salida,
    intencion: Intencion,
) -> None:
    if salida.opciones:
        await client.enviar_lista(
            paciente.telefono, salida.texto, "Ver opciones", salida.opciones
        )
    elif salida.botones:
        await client.enviar_botones(paciente.telefono, salida.texto, salida.botones)
    else:
        await client.enviar_texto(paciente.telefono, salida.texto)

    _guardar(conversacion.id, Remitente.BOT, salida.texto)

    # Aviso de privacidad, una sola vez por paciente.
    if _primer_contacto(conversacion.id):
        await client.enviar_texto(paciente.telefono, AVISO_CONSENTIMIENTO)
        _guardar(conversacion.id, Remitente.BOT, AVISO_CONSENTIMIENTO)

    _tocar(
        conversacion.id,
        intencion=intencion,
        paso=salida.paso,
        contexto=salida.contexto,
        reiniciar_intentos=True,
    )


async def _escalar(
    conversacion: Conversacion,
    paciente: Paciente,
    decision: escalation.Decision,
) -> None:
    with sesion() as s:
        c = s.get(Conversacion, conversacion.id)
        if c:
            c.estado = EstadoConversacion.REQUIERE_ATENCION
            c.motivo_escalado = decision.motivo
            c.ultima_actividad = datetime.utcnow()
            s.add(c)
        s.add(RegistroAuditoria(
            actor="bot",
            accion="conversacion.escalada",
            entidad="conversacion",
            entidad_id=conversacion.id,
            detalle=f"{decision.motivo.value if decision.motivo else ''} — {decision.aviso}",
        ))
        s.commit()

    await avisar(
        titulo=paciente.nombre or paciente.telefono,
        cuerpo=decision.aviso,
        conversacion_id=conversacion.id,
        urgente=decision.urgente,
    )


def _tocar(
    conversacion_id: int | None,
    *,
    intencion: Intencion | None = None,
    paso: str | None = None,
    contexto: dict | None = None,
    reiniciar_intentos: bool = False,
) -> None:
    if conversacion_id is None:
        return
    with sesion() as s:
        c = s.get(Conversacion, conversacion_id)
        if not c:
            return
        if intencion and intencion is not Intencion.DESCONOCIDA:
            c.intencion = intencion
        if paso is not None:
            c.paso = paso
        if contexto is not None:
            c.contexto = json.dumps(contexto, default=str)
        if reiniciar_intentos:
            c.intentos_fallidos = 0
        c.ultima_actividad = datetime.utcnow()
        s.add(c)
        s.commit()


def _sumar_intento(conversacion_id: int | None) -> None:
    if conversacion_id is None:
        return
    with sesion() as s:
        c = s.get(Conversacion, conversacion_id)
        if c:
            c.intentos_fallidos += 1
            s.add(c)
            s.commit()


def _marcar_conversion(conversacion_id: int | None) -> None:
    if conversacion_id is None:
        return
    with sesion() as s:
        c = s.get(Conversacion, conversacion_id)
        if c:
            c.convirtio = True
            s.add(c)
            s.commit()


def _actualizar_paciente(paciente_id: int | None, **campos) -> None:
    if paciente_id is None:
        return
    with sesion() as s:
        p = s.get(Paciente, paciente_id)
        if not p:
            return
        for k, v in campos.items():
            setattr(p, k, v)
        s.add(p)
        s.commit()


def _primer_contacto(conversacion_id: int | None) -> bool:
    """True si el bot todavía no había hablado con este paciente."""
    if conversacion_id is None:
        return False
    with sesion() as s:
        c = s.get(Conversacion, conversacion_id)
        if not c:
            return False
        anteriores = s.exec(
            select(Conversacion).where(
                Conversacion.paciente_id == c.paciente_id,
                Conversacion.id != conversacion_id,
            )
        ).all()
        if anteriores:
            return False
        enviados = s.exec(
            select(Mensaje).where(
                Mensaje.conversacion_id == conversacion_id,
                Mensaje.remitente == Remitente.BOT,
            )
        ).all()
        return len(enviados) <= 1


def _historial(conversacion_id: int | None, limite: int = 10) -> list[dict[str, str]]:
    if conversacion_id is None:
        return []
    with sesion() as s:
        mensajes = list(s.exec(
            select(Mensaje)
            .where(Mensaje.conversacion_id == conversacion_id)
            .order_by(Mensaje.enviado_en.desc())  # type: ignore[attr-defined]
            .limit(limite)
        ).all())
    mensajes.reverse()
    return [
        {
            "role": "user" if m.remitente is Remitente.PACIENTE else "assistant",
            "content": m.texto,
        }
        for m in mensajes
        if m.remitente in (Remitente.PACIENTE, Remitente.BOT) and m.texto
    ]


def _modo() -> ModoAsistente:
    """Modo vigente. El tope de gasto manda por encima de lo configurado."""
    from app.models import Ajuste

    if ai.tope_alcanzado():
        return ModoAsistente.BASICO

    with sesion() as s:
        ajuste = s.get(Ajuste, "modo_asistente")
    valor = ajuste.valor if ajuste else config.modo_asistente
    try:
        return ModoAsistente(valor)
    except ValueError:
        return ModoAsistente.HIBRIDO
