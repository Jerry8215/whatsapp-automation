"""
Flujos determinísticos — el «modo básico».

Resuelven sin costo lo que representa la mayor parte del volumen de un
consultorio: horarios, ubicación, precios, indicaciones y agendamiento.

En modo híbrido esto atiende todo lo que la clasificación reconoce con
confianza, y solo lo demás llega a la IA.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime

from sqlmodel import select

from app.db import sesion
from app.models import (
    Conversacion,
    Intencion,
    Paciente,
    RespuestaFrecuente,
    Sede,
)

from app.tiempo import DIAS, MESES, a_local, ahora_local
from app.tiempo import fecha_legible as _fecha_legible


@dataclass
class Salida:
    """Lo que el flujo decide responder."""

    texto: str = ""
    botones: list[tuple[str, str]] = field(default_factory=list)
    opciones: list[tuple[str, str, str]] = field(default_factory=list)
    paso: str = ""
    contexto: dict = field(default_factory=dict)
    resuelto: bool = True     # False → que lo intente la IA

    @property
    def vacio(self) -> bool:
        return not self.texto and not self.botones and not self.opciones


SIN_RESOLVER = Salida(resuelto=False)


# ----------------------------------------------------------------------
#  Variación
# ----------------------------------------------------------------------

def variar(opciones: list[str], conversacion: Conversacion | None = None) -> str:
    """
    Elige una redacción distinta cada vez, dentro de la misma conversación.

    En modo básico las respuestas son fijas, y eso se nota enseguida: el
    paciente que pregunta dos veces recibe el mismo párrafo palabra por
    palabra y entiende que le contesta una máquina. No se puede improvisar
    sin IA, pero sí tener varias formas de decir lo mismo.

    La elección no es al azar: depende de cuántas veces ya se respondió en
    esta conversación. Así es estable —la misma conversación se comporta
    igual si se reprocesa un mensaje— y aun así no se repite.
    """
    if not opciones:
        return ""
    if conversacion is None or conversacion.id is None:
        return opciones[0]

    from app.db import sesion as _sesion
    from app.models import Mensaje, Remitente

    with _sesion() as s:
        dichos = len(list(s.exec(
            select(Mensaje).where(
                Mensaje.conversacion_id == conversacion.id,
                Mensaje.remitente == Remitente.BOT,
            )
        ).all()))

    return opciones[dichos % len(opciones)]


# ----------------------------------------------------------------------
#  Formato
# ----------------------------------------------------------------------

def fecha_legible(dt: datetime) -> str:
    """Recibe UTC (lo que hay en la base) y devuelve hora del consultorio."""
    return _fecha_legible(dt)


def _saludo_por_hora(momento: datetime | None = None) -> str:
    # La hora del consultorio, no la del servidor: si el servidor está en
    # Europa, saludaría «buenas tardes» a las siete de la mañana.
    h = (a_local(momento) if momento else ahora_local()).hour
    if h < 12:
        return "Buenos días"
    if h < 19:
        return "Buenas tardes"
    return "Buenas noches"


# ----------------------------------------------------------------------
#  Contenido del consultorio
# ----------------------------------------------------------------------

def respuesta_guardada(
    intencion: Intencion, texto: str = "", sede_id: int | None = None
) -> str:
    """
    Texto cargado por el consultorio desde el panel, si aplica.

    Las respuestas frecuentes tienen **disparadores** —las palabras que las
    activan— y hasta acá se ignoraban: se devolvía siempre la primera
    cargada para esa intención. Con dos respuestas de información, a quien
    preguntaba «¿qué opera el doctor?» se le contestaba qué documentos
    llevar. Contestar cualquier cosa es peor que no contestar, porque el
    paciente cree que le respondieron.

    Ahora gana la que más disparadores coincida. Si ninguna coincide y no
    hay una general —sin disparadores—, se devuelve vacío y el flujo sigue
    su camino.
    """
    from app.brain.safety import normalizar

    with sesion() as s:
        candidatas = list(s.exec(
            select(RespuestaFrecuente).where(
                RespuestaFrecuente.intencion == intencion,
                RespuestaFrecuente.activa,  # type: ignore[arg-type]
            )
        ).all())

    if not candidatas:
        return ""

    if sede_id:
        candidatas = [c for c in candidatas if c.sede_id in (sede_id, None)] or candidatas

    t = normalizar(texto)
    mejor, mejor_puntaje = None, 0

    for c in candidatas:
        claves = [normalizar(d) for d in (c.disparadores or "").split(",") if d.strip()]
        if not claves:
            continue
        puntaje = sum(1 for clave in claves if clave and clave in t)
        # Desempate por sede: la específica manda sobre la general.
        if puntaje and (puntaje > mejor_puntaje or
                        (puntaje == mejor_puntaje and c.sede_id is not None)):
            mejor, mejor_puntaje = c, puntaje

    if mejor:
        return mejor.respuesta

    # Ninguna coincidió. Solo sirve una que no tenga disparadores, porque
    # esa está pensada como respuesta general de esa intención.
    for c in candidatas:
        if not (c.disparadores or "").strip():
            return c.respuesta
    return ""


def sedes_activas() -> list[Sede]:
    with sesion() as s:
        return list(s.exec(
            select(Sede).where(Sede.activa).order_by(Sede.orden)  # type: ignore[arg-type]
        ).all())


def contexto_para_ia() -> str:
    """
    Datos reales del consultorio que se le pasan al modelo.

    El identificador de cada sede va incluido a propósito: es lo que el
    modelo necesita para consultar disponibilidad y agendar con las
    herramientas. Sin él tendría que adivinarlo.
    """
    lineas: list[str] = []
    for sede in sedes_activas():
        lineas.append(f"— {sede.nombre}  (sede_id: {sede.id})")
        lineas.append(f"  Dirección: {sede.direccion}")
        if sede.referencias:
            lineas.append(f"  Referencias: {sede.referencias}")
        if sede.horarios:
            lineas.append(f"  Horarios: {sede.horarios}")
        if sede.precio_valoracion:
            lineas.append(f"  Valoración: ${sede.precio_valoracion:,.0f} MXN")
        if sede.convenios:
            lineas.append(f"  Convenios: {sede.convenios}")

    with sesion() as s:
        frecuentes = list(s.exec(
            select(RespuestaFrecuente).where(RespuestaFrecuente.activa)  # type: ignore[arg-type]
        ).all())
    if frecuentes:
        lineas.append("\nRespuestas oficiales del consultorio:")
        for f in frecuentes:
            lineas.append(f"  [{f.intencion.value}] {f.respuesta}")

    if not lineas:
        # Puede pasar antes de que el consultorio cargue su contenido. El
        # modelo tiene que saberlo para no inventar precios ni direcciones.
        return (
            "(Todavía no hay información del consultorio cargada. No inventes "
            "precios, horarios ni direcciones: dilo con naturalidad y deriva "
            "al consultorio.)"
        )

    return "\n".join(lineas)


def contexto_paciente(paciente: Paciente) -> str:
    partes: list[str] = []

    if not paciente.es_conocido:
        partes.append("El paciente escribe por primera vez. No conoces su nombre.")
    else:
        partes.append(f"El paciente se llama {paciente.nombre}.")
        if paciente.ciudad:
            partes.append(f"Ciudad: {paciente.ciudad}.")
        if paciente.sede_preferida_id:
            with sesion() as s:
                sede = s.get(Sede, paciente.sede_preferida_id)
            if sede:
                partes.append(f"La última vez se atendió en {sede.nombre}.")

    # Su próxima cita, si tiene. Sin esto el asistente no sabe responder algo
    # tan básico como «¿a qué hora es mi cita?», que es de lo primero que
    # pregunta un paciente ya agendado.
    cita = proxima_cita(paciente)
    if cita:
        partes.append(
            f"TIENE UNA CITA AGENDADA: {fecha_legible(cita['inicio'])} en "
            f"{cita['sede']}, {cita['direccion']}. Si pregunta por su cita, "
            f"dale ese dato. No inventes ningún otro horario."
        )
    else:
        partes.append("No tiene ninguna cita agendada en este momento.")

    return " ".join(partes)


def proxima_cita(paciente: Paciente) -> dict | None:
    """La próxima cita del paciente, con lo necesario para contársela."""
    from app.models import Cita, EstadoCita

    with sesion() as s:
        cita = s.exec(
            select(Cita)
            .where(
                Cita.paciente_id == paciente.id,
                Cita.inicio >= datetime.utcnow(),
                Cita.estado.in_([  # type: ignore[attr-defined]
                    EstadoCita.SOLICITADA, EstadoCita.AGENDADA, EstadoCita.CONFIRMADA,
                ]),
            )
            .order_by(Cita.inicio)  # type: ignore[arg-type]
        ).first()
        if not cita:
            return None
        sede = s.get(Sede, cita.sede_id)

    return {
        "id": cita.id,
        "inicio": cita.inicio,
        "estado": cita.estado.value,
        "sede": sede.nombre if sede else "",
        "direccion": sede.direccion if sede else "",
        "mapa": sede.mapa_url if sede else "",
        "referencias": sede.referencias if sede else "",
    }


# ----------------------------------------------------------------------
#  Flujos por intención
# ----------------------------------------------------------------------

def atender(
    *,
    intencion: Intencion,
    texto: str,
    paciente: Paciente,
    conversacion: Conversacion,
    abierto: bool = True,
) -> Salida:
    """
    Punto de entrada. Devuelve SIN_RESOLVER cuando no hay flujo capaz de
    atender el caso: ahí decide el router si llama a la IA.
    """
    # Si veníamos a mitad de un agendamiento, seguimos ahí.
    if conversacion.paso.startswith("cita:"):
        return _paso_de_cita(texto, paciente, conversacion)

    # «¿A qué hora es mi cita?» — se responde antes de clasificar porque las
    # reglas de intención no la reconocen y terminaba en «no le entendí».
    # Para un paciente ya agendado es de lo primero que pregunta.
    if pregunta_por_su_cita(texto):
        return _su_cita(paciente)

    match intencion:
        case Intencion.SALUDO:
            return _saludo(paciente, abierto, conversacion)
        case Intencion.CITA:
            return _iniciar_cita(paciente, conversacion)
        case Intencion.COSTOS:
            return _costos(conversacion, texto)
        case Intencion.UBICACION:
            return _ubicacion(paciente)
        case Intencion.INFORMACION:
            return _informacion(conversacion, texto)
        case Intencion.CONFIRMAR:
            return _confirmar(paciente, conversacion)
        case Intencion.CANCELAR:
            return _cancelar()
        case _:
            return SIN_RESOLVER


def es_recurrente(paciente: Paciente) -> bool:
    """
    ¿Este paciente ya tuvo trato con el consultorio?

    Ojo: tener su nombre NO alcanza. WhatsApp nos entrega el nombre del
    perfil desde el primer mensaje, así que confundir «sé cómo se llama»
    con «ya lo conozco» hace que a un paciente nuevo se lo salude como si
    fuera de la casa — y se pierde justo la presentación que genera
    confianza en el primer contacto.
    """
    with sesion() as s:
        from app.models import Cita

        if s.exec(select(Cita).where(Cita.paciente_id == paciente.id)).first():
            return True
        previas = list(s.exec(
            select(Conversacion).where(Conversacion.paciente_id == paciente.id)
        ).all())
        # La actual no cuenta.
        return len(previas) > 1


def _saludo(
    paciente: Paciente, abierto: bool = True, conversacion: Conversacion | None = None
) -> Salida:
    saludo = _saludo_por_hora()

    # Fuera de horario se avisa, pero sin cerrarle la puerta: el asistente
    # igual puede resolver dudas y agendar. Decir «estamos cerrados» y nada
    # más haría que el paciente se vaya.
    # Fuera de horario NO se abre anunciando que está cerrado. El paciente
    # que escribe a las once de la noche no necesita que le digan que nadie
    # lo va a atender: necesita que lo atiendan. El asistente puede resolver
    # dudas y agendar igual, así que se ofrece eso y punto.
    #
    # Dónde sí importa el horario: cuando hay que prometer que una persona
    # va a contestar. Eso lo maneja la barrera clínica y el escalado, que
    # fuera de horario no prometen a nadie.
    cierre = variar([
        "¿En qué le puedo ayudar?",
        "¿Cómo le puedo ayudar?",
        "Dígame en qué le puedo servir.",
    ], conversacion) if abierto else variar([
        "¿En qué le puedo ayudar? Puedo resolverle dudas y agendarle su "
        "cita ahora mismo.",
        "Con gusto le ayudo. Puedo darle informes y apartarle un lugar en "
        "la agenda. ¿Qué necesita?",
    ], conversacion)

    if es_recurrente(paciente) and paciente.nombre:
        nombre = paciente.nombre.split()[0]
        return Salida(
            texto=(
                f"{saludo}, {nombre}. Soy el asistente del consultorio del "
                f"Dr. Padilla.\n\n{cierre}"
            )
        )

    # Primer contacto: la presentación completa.
    return Salida(
        texto=(
            f"{saludo} 👋 Soy el asistente del consultorio del Dr. José "
            f"Guadalupe Padilla, Cirujano General y Laparoscópico.\n\n{cierre}"
        )
    )


def _costos(conversacion: Conversacion | None = None, texto: str = "") -> Salida:
    guardada = respuesta_guardada(Intencion.COSTOS, texto)
    if guardada:
        return Salida(texto=guardada)

    sedes = [s for s in sedes_activas() if s.precio_valoracion]
    if not sedes:
        return SIN_RESOLVER

    precios = {s.precio_valoracion for s in sedes}

    if len(precios) == 1:
        # Mismo precio en todas: se dice una sola vez. Repetirlo por sede
        # suena a lista de tarifas y no a una recepcionista.
        encabezado = (
            f"La consulta de valoración tiene un costo de "
            f"${sedes[0].precio_valoracion:,.0f} pesos."
        )
    else:
        listado = "\n".join(
            f"· {s.nombre}: ${s.precio_valoracion:,.0f} pesos" for s in sedes
        )
        encabezado = f"El costo de la valoración depende de la sede:\n\n{listado}"

    return Salida(texto=(
        f"{encabezado}\n\n"
        f"Sobre una cirugía, el costo lo define el Dr. Padilla después de "
        f"revisarlo, porque depende de sus estudios y del hospital. En la "
        f"valoración se lo entrega por escrito, sin compromiso.\n\n"
        + variar([
            "¿Le agendo una valoración?",
            "¿Quiere que le aparte un lugar para la valoración?",
            "Si gusta, le busco un horario para la valoración.",
        ], conversacion)
    ))


def _ubicacion(paciente: Paciente) -> Salida:
    sedes = sedes_activas()
    if not sedes:
        return SIN_RESOLVER

    if paciente.sede_preferida_id:
        for s in sedes:
            if s.id == paciente.sede_preferida_id:
                sedes = [s]
                break

    if len(sedes) == 1:
        s = sedes[0]
        texto = f"El consultorio está en:\n\n📍 {s.direccion}"
        if s.referencias:
            texto += f"\n{s.referencias}"
        if s.horarios:
            texto += f"\n\nHorarios: {s.horarios}"
        if s.mapa_url:
            texto += f"\n\n{s.mapa_url}"
        return Salida(texto=texto)

    bloques = []
    for s in sedes:
        b = f"📍 *{s.nombre}*\n{s.direccion}"
        if s.horarios:
            b += f"\n{s.horarios}"
        bloques.append(b)
    return Salida(texto=(
        "El Dr. Padilla atiende en estas sedes:\n\n"
        + "\n\n".join(bloques)
        + "\n\n¿En cuál le gustaría atenderse?"
    ))


def _informacion(conversacion: Conversacion | None = None, texto: str = "") -> Salida:
    guardada = respuesta_guardada(Intencion.INFORMACION, texto)
    if guardada:
        return Salida(texto=guardada)

    sedes = sedes_activas()
    if not sedes:
        return SIN_RESOLVER

    horarios = "\n".join(f"· {s.nombre}: {s.horarios}" for s in sedes if s.horarios)
    if not horarios:
        return SIN_RESOLVER
    return Salida(texto=(
        f"Estos son los horarios de atención:\n\n{horarios}\n\n"
        + variar([
            "¿Le agendo una cita?",
            "¿Quiere que le aparte un lugar?",
            "Dígame si le acomoda alguno y se lo aparto.",
        ], conversacion)
    ))


#: «¿A qué hora es mi cita?», en las formas en que la gente lo escribe.
_PREGUNTA_POR_SU_CITA = re.compile(
    r"(?:"
    r"\b(?:a que hora|aque hora|que hora|cuando|que dia|para cuando)\b[^?]{0,25}"
    r"\b(?:mi|la|mis|las)?\s*(?:cita|consulta|turno|valoracion)\b"
    r"|"
    r"\b(?:mi|la)\s*(?:cita|consulta|turno)\b[^?]{0,25}"
    r"\b(?:a que hora|que hora|cuando|que dia|es|era|sigue|quedo)\b"
    r"|"
    r"\bcuando me toca\b"
    r"|"
    r"\b(?:tengo|tenia|traigo) (?:una |mi )?(?:cita|consulta)\b[^?]{0,20}\?"
    r"|"
    r"\b(?:checar|revisar|confirmar|saber|record\w+|recuerd\w+) (?:mi|la) (?:cita|horario)\b"
    r")"
)


def pregunta_por_su_cita(texto: str) -> bool:
    from app.brain.safety import normalizar

    t = normalizar(texto)
    if not t:
        return False
    # «Quiero agendar una cita» no es preguntar por una que ya tiene.
    if re.search(r"\b(?:quiero|quisiera|necesito|puedo|me gustaria) (?:agendar|sacar|hacer|programar|pedir)\b", t):
        return False
    return bool(_PREGUNTA_POR_SU_CITA.search(t))


def _su_cita(paciente: Paciente) -> Salida:
    """
    Le dice cuándo es su cita, con la dirección de SU sede.

    Es información que el sistema ya tiene y que antes no sabía entregar: la
    conversación terminaba en «no le entendí» y de ahí en la bandeja de la
    asistente, por una pregunta que se contesta sola.
    """
    cita = proxima_cita(paciente)

    if not cita:
        return Salida(texto=(
            "No encuentro ninguna cita próxima a su nombre. "
            "¿Quiere que le busque un horario?"
        ))

    texto = (
        f"Su cita es el {fecha_legible(cita['inicio'])}.\n\n"
        f"📍 {cita['sede']}\n{cita['direccion']}"
    )
    if cita["mapa"]:
        texto += f"\n{cita['mapa']}"
    if cita["referencias"]:
        texto += f"\n\n{cita['referencias']}"

    return Salida(
        texto=texto,
        botones=[
            ("confirmar", "Confirmar asistencia"),
            ("reprogramar", "Reprogramar"),
        ],
    )


#: Frases con las que el asistente ofrece agendar. Si la última cosa que
#: dijo termina así, un «sí» significa «sí, agénde­me», no otra cosa.
_OFRECIO_AGENDAR = re.compile(
    r"(?:le agendo|le busco un horario|se lo aparto|le aparto un lugar|"
    r"quiere que le (?:busque|aparte)|le agendo una valoraci|"
    r"agendarle una cita|le acomoda alguno)"
)


def _ultimo_del_bot(conversacion: Conversacion | None) -> str:
    if conversacion is None or conversacion.id is None:
        return ""
    from app.models import Mensaje, Remitente

    with sesion() as s:
        ultimo = s.exec(
            select(Mensaje)
            .where(
                Mensaje.conversacion_id == conversacion.id,
                Mensaje.remitente == Remitente.BOT,
            )
            .order_by(Mensaje.enviado_en.desc())  # type: ignore[attr-defined]
        ).first()
    return ultimo.texto if ultimo else ""


def _confirmar(
    paciente: Paciente | None = None, conversacion: Conversacion | None = None
) -> Salida:
    """
    Qué significa un «sí» suelto.

    Antes significaba siempre «queda confirmada, aquí la esperamos», y eso
    provocaba el peor error posible del sistema: el asistente ofrecía
    agendar, el paciente decía «sí», y se le respondía que su cita estaba
    confirmada **sin haber creado ninguna cita**. El paciente se presentaba
    un día que nadie lo esperaba.

    Un «sí» solo se interpreta con lo que se acaba de decir:

      * si veníamos ofreciendo agendar, arranca el agendamiento;
      * si ya tiene una cita, se le confirma esa, con su fecha;
      * si no hay ni una cosa ni la otra, se pregunta. Nunca se da por
        confirmado algo que no existe.
    """
    from app.brain.safety import normalizar

    ultimo = normalizar(_ultimo_del_bot(conversacion))

    if ultimo and _OFRECIO_AGENDAR.search(ultimo) and paciente and conversacion:
        return _iniciar_cita(paciente, conversacion)

    cita = proxima_cita(paciente) if paciente else None
    if cita:
        _marcar_confirmada(cita["id"])
        return Salida(texto=(
            f"Perfecto, queda confirmada su cita del "
            f"{fecha_legible(cita['inicio'])} en {cita['sede']}. "
            f"Aquí la esperamos. 🙌"
        ))

    return Salida(texto=(
        "Con gusto. ¿Quiere que le busque un horario para su valoración?"
    ))


def _marcar_confirmada(cita_id: int) -> None:
    from app.models import Cita, EstadoCita

    with sesion() as s:
        cita = s.get(Cita, cita_id)
        if cita and cita.estado is EstadoCita.AGENDADA:
            cita.estado = EstadoCita.CONFIRMADA
            cita.confirmada_por_paciente_en = datetime.utcnow()
            s.add(cita)
            s.commit()


def _cancelar() -> Salida:
    return Salida(
        texto=(
            "Claro, con gusto. ¿Prefiere cancelarla por completo o buscamos "
            "otro horario que le acomode?"
        ),
        botones=[("reprogramar", "Buscar otro horario"), ("cancelar", "Cancelar")],
    )


# ----------------------------------------------------------------------
#  Agendamiento
# ----------------------------------------------------------------------

def _iniciar_cita(paciente: Paciente, conversacion: Conversacion) -> Salida:
    """
    Primero la sede, después la fecha. Nunca al revés: ofrecer horarios
    antes de saber a qué consultorio va significa ofrecer huecos que en esa
    dirección no existen.
    """
    sedes = sedes_activas()

    if not sedes:
        return SIN_RESOLVER

    # Una sola sede activa: no tiene sentido preguntar.
    if len(sedes) == 1:
        return Salida(
            texto="Con gusto le agendo. Déjeme revisar la disponibilidad…",
            paso="cita:buscar_horarios",
            contexto={"sede_id": sedes[0].id},
        )

    # Paciente recurrente: se le propone donde se atendió la última vez.
    if paciente.sede_preferida_id:
        for s in sedes:
            if s.id == paciente.sede_preferida_id:
                return Salida(
                    texto=f"Con gusto. ¿Va al consultorio de {s.nombre}, como la última vez?",
                    botones=[
                        (f"sede:{s.id}", "Sí, ahí mismo"),
                        ("sede:otra", "Otra sede"),
                    ],
                    paso="cita:confirmar_sede",
                    contexto={"sede_id": s.id},
                )

    return Salida(
        texto="Con gusto le agendo. ¿En cuál de nuestros consultorios prefiere atenderse?",
        opciones=[
            (f"sede:{s.id}", s.nombre, s.direccion[:70]) for s in sedes
        ],
        paso="cita:elegir_sede",
    )


def _paso_de_cita(texto: str, paciente: Paciente, conversacion: Conversacion) -> Salida:
    """
    Continuación del agendamiento.

    La reserva efectiva la hace el router, que es quien puede esperar a la
    agenda. Acá solo se decide qué sigue.
    """
    try:
        contexto = json.loads(conversacion.contexto or "{}")
    except json.JSONDecodeError:
        contexto = {}

    if conversacion.paso == "cita:elegir_sede":
        sede_id = _sede_elegida(texto)
        if not sede_id:
            return Salida(
                texto="¿Me confirma en cuál de los consultorios prefiere atenderse?",
                opciones=[
                    (f"sede:{s.id}", s.nombre, s.direccion[:70])
                    for s in sedes_activas()
                ],
                paso="cita:elegir_sede",
            )
        return Salida(
            texto="Perfecto, déjeme revisar la disponibilidad…",
            paso="cita:buscar_horarios",
            contexto={**contexto, "sede_id": sede_id},
        )

    if conversacion.paso == "cita:confirmar_sede":
        if _es_afirmativo(texto):
            return Salida(
                texto="Perfecto, déjeme revisar la disponibilidad…",
                paso="cita:buscar_horarios",
                contexto=contexto,
            )
        return Salida(
            texto="Sin problema. ¿En cuál prefiere?",
            opciones=[
                (f"sede:{s.id}", s.nombre, s.direccion[:70]) for s in sedes_activas()
            ],
            paso="cita:elegir_sede",
        )

    if conversacion.paso == "cita:elegir_horario":
        return Salida(paso="cita:reservar", contexto=contexto, resuelto=True)

    return SIN_RESOLVER


def _sede_elegida(texto: str) -> int | None:
    t = texto.strip().lower()
    if t.startswith("sede:"):
        resto = t.removeprefix("sede:")
        if resto.isdigit():
            return int(resto)
        return None
    for s in sedes_activas():
        if s.nombre.lower() in t or t in s.nombre.lower():
            return s.id
    return None


def _es_afirmativo(texto: str) -> bool:
    from app.brain.safety import normalizar

    t = normalizar(texto)
    return any(t.startswith(p) for p in (
        "si", "claro", "correcto", "asi es", "ahi mismo", "por favor",
        "ok", "va", "sale", "de acuerdo", "exacto",
    ))
