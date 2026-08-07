"""
Flujos determinísticos — el «modo básico».

Resuelven sin costo lo que representa la mayor parte del volumen de un
consultorio: horarios, ubicación, precios, indicaciones y agendamiento.

En modo híbrido esto atiende todo lo que la clasificación reconoce con
confianza, y solo lo demás llega a la IA.
"""

from __future__ import annotations

import json
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

def respuesta_guardada(intencion: Intencion, sede_id: int | None = None) -> str:
    """Texto cargado por el consultorio desde el panel, si existe."""
    with sesion() as s:
        consulta = select(RespuestaFrecuente).where(
            RespuestaFrecuente.intencion == intencion,
            RespuestaFrecuente.activa,  # type: ignore[arg-type]
        )
        candidatas = list(s.exec(consulta).all())

    if not candidatas:
        return ""
    if sede_id:
        for c in candidatas:
            if c.sede_id == sede_id:
                return c.respuesta
    for c in candidatas:
        if c.sede_id is None:
            return c.respuesta
    return candidatas[0].respuesta


def sedes_activas() -> list[Sede]:
    with sesion() as s:
        return list(s.exec(
            select(Sede).where(Sede.activa).order_by(Sede.orden)  # type: ignore[arg-type]
        ).all())


def contexto_para_ia() -> str:
    """Datos reales del consultorio que se le pasan al modelo."""
    lineas: list[str] = []
    for sede in sedes_activas():
        lineas.append(f"— {sede.nombre}")
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

    return "\n".join(lineas) or "(sin información cargada todavía)"


def contexto_paciente(paciente: Paciente) -> str:
    if not paciente.es_conocido:
        return "El paciente escribe por primera vez. No conoces su nombre."
    partes = [f"El paciente se llama {paciente.nombre}."]
    if paciente.ciudad:
        partes.append(f"Ciudad: {paciente.ciudad}.")
    if paciente.sede_preferida_id:
        with sesion() as s:
            sede = s.get(Sede, paciente.sede_preferida_id)
        if sede:
            partes.append(f"La última vez se atendió en {sede.nombre}.")
    return " ".join(partes)


# ----------------------------------------------------------------------
#  Flujos por intención
# ----------------------------------------------------------------------

def atender(
    *,
    intencion: Intencion,
    texto: str,
    paciente: Paciente,
    conversacion: Conversacion,
) -> Salida:
    """
    Punto de entrada. Devuelve SIN_RESOLVER cuando no hay flujo capaz de
    atender el caso: ahí decide el router si llama a la IA.
    """
    # Si veníamos a mitad de un agendamiento, seguimos ahí.
    if conversacion.paso.startswith("cita:"):
        return _paso_de_cita(texto, paciente, conversacion)

    match intencion:
        case Intencion.SALUDO:
            return _saludo(paciente)
        case Intencion.CITA:
            return _iniciar_cita(paciente, conversacion)
        case Intencion.COSTOS:
            return _costos()
        case Intencion.UBICACION:
            return _ubicacion(paciente)
        case Intencion.INFORMACION:
            return _informacion()
        case Intencion.CONFIRMAR:
            return _confirmar()
        case Intencion.CANCELAR:
            return _cancelar()
        case _:
            return SIN_RESOLVER


def _saludo(paciente: Paciente) -> Salida:
    saludo = _saludo_por_hora()
    if paciente.es_conocido:
        nombre = paciente.nombre.split()[0]
        return Salida(
            texto=(
                f"{saludo}, {nombre}. Soy el asistente del consultorio del "
                f"Dr. Padilla. ¿En qué le puedo ayudar?"
            )
        )
    return Salida(
        texto=(
            f"{saludo} 👋 Soy el asistente del consultorio del Dr. José "
            f"Guadalupe Padilla, Cirujano General y Laparoscópico.\n\n"
            f"¿En qué le puedo ayudar?"
        )
    )


def _costos() -> Salida:
    guardada = respuesta_guardada(Intencion.COSTOS)
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
        f"¿Le agendo una valoración?"
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


def _informacion() -> Salida:
    guardada = respuesta_guardada(Intencion.INFORMACION)
    if guardada:
        return Salida(texto=guardada)

    sedes = sedes_activas()
    if not sedes:
        return SIN_RESOLVER

    horarios = "\n".join(f"· {s.nombre}: {s.horarios}" for s in sedes if s.horarios)
    if not horarios:
        return SIN_RESOLVER
    return Salida(texto=f"Estos son los horarios de atención:\n\n{horarios}\n\n¿Le agendo una cita?")


def _confirmar() -> Salida:
    return Salida(texto="Perfecto, queda confirmada. Aquí la esperamos. 🙌")


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
