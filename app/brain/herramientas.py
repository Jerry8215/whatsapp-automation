"""
Lo que el asistente puede *hacer*, además de conversar.

Un chatbot que solo redacta bonito no sirve en un consultorio: el paciente
pregunta «¿tendrás algo el jueves por la tarde?» y necesita una respuesta
con la agenda real, no una frase amable.

Acá viven las acciones que el modelo puede pedir —consultar disponibilidad,
agendar, cancelar, derivar— y que ejecuta este módulo contra el sistema de
verdad. El modelo decide *cuándo*; el código decide *qué pasa*.

Tres reglas de diseño:

  * **El modelo nunca escribe en la base directamente.** Pide una acción y
    acá se valida. Si pide agendar un horario que no existe, el proveedor de
    agenda lo rechaza igual que rechazaría a un paciente: no hay forma de
    que una alucinación se convierta en una cita.
  * **Las herramientas devuelven datos, no frases.** El texto lo redacta el
    modelo, que para eso está. Así la misma disponibilidad se cuenta
    distinto según cómo venga preguntando el paciente.
  * **Nada clínico.** Ninguna herramienta acepta ni devuelve síntomas,
    diagnósticos ni estudios.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

from app.tiempo import fecha_legible

log = logging.getLogger(__name__)

#: Cuántos horarios se le muestran al modelo. Suficientes para que pueda
#: elegir los que encajan con lo que pidió el paciente («por la tarde»,
#: «después del jueves») sin ahogarlo en opciones.
MAX_HORARIOS = 8


@dataclass
class Contexto:
    """Con quién estamos hablando. Lo arma el router, no el modelo."""

    paciente_id: int
    conversacion_id: int
    telefono: str


@dataclass
class Efecto:
    """
    Lo que pasó al ejecutar las herramientas, para que el router actúe.

    El modelo no puede escalar ni marcar una conversión por su cuenta: pide
    la acción, y el router —que es quien manda— la aplica.
    """

    derivar: str = ""
    cita_creada: int | None = None
    sede_agendada: int | None = None
    horarios_ofrecidos: list[str] = field(default_factory=list)


# ======================================================================
#  Lo que ve el modelo
# ======================================================================

ESQUEMA = [
    {
        "type": "function",
        "function": {
            "name": "consultar_disponibilidad",
            "description": (
                "Consulta los horarios REALMENTE disponibles de una sede. "
                "Úsala siempre antes de mencionar cualquier horario: nunca "
                "inventes ni supongas disponibilidad. Devuelve una lista de "
                "horarios con su identificador exacto."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sede_id": {
                        "type": "integer",
                        "description": "El id de la sede, según la lista de sedes que tienes.",
                    },
                    "dias": {
                        "type": "integer",
                        "description": "Cuántos días hacia adelante mirar. Por defecto 14.",
                    },
                },
                "required": ["sede_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agendar_cita",
            "description": (
                "Reserva la cita en firme. Úsala solo cuando el paciente ya "
                "eligió un horario concreto de los que le ofreciste. El valor "
                "de `inicio` debe ser EXACTAMENTE el que devolvió "
                "consultar_disponibilidad."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sede_id": {"type": "integer"},
                    "inicio": {
                        "type": "string",
                        "description": "El identificador exacto del horario elegido.",
                    },
                    "tipo": {
                        "type": "string",
                        "enum": ["valoracion", "control", "postoperatorio"],
                        "description": "Tipo administrativo de la cita. Por defecto valoracion.",
                    },
                },
                "required": ["sede_id", "inicio"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancelar_cita",
            "description": (
                "Cancela la próxima cita del paciente. Úsala solo cuando lo "
                "pida con claridad. Si quiere cambiarla de horario, primero "
                "consulta disponibilidad y agenda la nueva."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "derivar_a_persona",
            "description": (
                "Pasa la conversación al equipo del consultorio. Úsala cuando "
                "el paciente lo pida, cuando se moleste, cuando necesite algo "
                "que no puedes resolver, o cuando la conversación se trabe. "
                "Ante la duda, deriva: es preferible que una persona pierda "
                "treinta segundos a dejar mal atendido al paciente."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "motivo": {
                        "type": "string",
                        "description": "En una línea, para que el consultorio sepa qué pasa.",
                    }
                },
                "required": ["motivo"],
            },
        },
    },
]


# ======================================================================
#  Ejecución
# ======================================================================

async def ejecutar(nombre: str, argumentos: str, ctx: Contexto, efecto: Efecto) -> str:
    """
    Corre una herramienta y devuelve el resultado como JSON para el modelo.

    Nunca levanta: un fallo se le informa al modelo como un dato más, y él
    decide cómo seguir. Que se caiga una herramienta no puede dejar al
    paciente sin respuesta.
    """
    try:
        datos = json.loads(argumentos or "{}")
    except json.JSONDecodeError:
        datos = {}

    try:
        if nombre == "consultar_disponibilidad":
            return await _disponibilidad(datos, efecto)
        if nombre == "agendar_cita":
            return await _agendar(datos, ctx, efecto)
        if nombre == "cancelar_cita":
            return await _cancelar(ctx)
        if nombre == "derivar_a_persona":
            efecto.derivar = str(datos.get("motivo") or "El asistente pidió ayuda humana.")
            return _json({"ok": True, "derivada": True})
    except Exception:
        log.exception("Falló la herramienta %s", nombre)
        return _json({
            "ok": False,
            "error": "No se pudo completar la operación. Deriva al consultorio.",
        })

    return _json({"ok": False, "error": f"Herramienta desconocida: {nombre}"})


async def _disponibilidad(datos: dict, efecto: Efecto) -> str:
    from app.agenda.franjas import hay_franjas
    from app.agenda.service import ofrecer_horarios, origen
    from app.db import sesion
    from app.models import Sede

    sede_id = int(datos.get("sede_id") or 0)
    dias = min(int(datos.get("dias") or 14), 60)

    with sesion() as s:
        sede = s.get(Sede, sede_id)

    if not sede or not sede.activa:
        return _json({
            "ok": False,
            "error": "Esa sede no existe o no está activa. Ofrece solo las sedes de tu lista.",
        })

    # Sin franjas reservadas el asistente no ve la agenda de Doctoralia y no
    # puede prometer nada. Se le dice al modelo, y él se lo explica al
    # paciente con sus palabras.
    if origen() == "franjas" and not hay_franjas(sede_id):
        return _json({
            "ok": True,
            "puede_agendar": False,
            "motivo": (
                "Esta sede todavía no tiene horarios habilitados para WhatsApp. "
                "Toma los datos del paciente y qué días le acomodan, y avisa "
                "que el consultorio le confirma el horario en breve. "
                "NO prometas ningún horario concreto."
            ),
        })

    huecos = await ofrecer_horarios(sede_id, dias=dias, cantidad=MAX_HORARIOS)

    if not huecos:
        return _json({
            "ok": True,
            "puede_agendar": False,
            "motivo": (
                "No hay horarios libres en ese rango. Ofrece mirar más "
                "adelante o deriva al consultorio."
            ),
        })

    efecto.horarios_ofrecidos = [h.inicio.isoformat() for h in huecos]

    return _json({
        "ok": True,
        "puede_agendar": True,
        "sede": sede.nombre,
        "horarios": [
            {"inicio": h.inicio.isoformat(), "legible": fecha_legible(h.inicio)}
            for h in huecos
        ],
    })


async def _agendar(datos: dict, ctx: Contexto, efecto: Efecto) -> str:
    from app.agenda.base import CupoYaOcupado
    from app.agenda.service import agendar, ofrecer_horarios
    from app.db import sesion
    from app.models import Sede

    sede_id = int(datos.get("sede_id") or 0)
    crudo = str(datos.get("inicio") or "")

    try:
        inicio = datetime.fromisoformat(crudo.replace("Z", ""))
    except ValueError:
        return _json({
            "ok": False,
            "error": (
                "Ese horario no tiene un formato válido. Vuelve a consultar "
                "disponibilidad y usa el identificador tal cual te lo devuelve."
            ),
        })

    try:
        cita = await agendar(
            paciente_id=ctx.paciente_id,
            sede_id=sede_id,
            inicio=inicio,
            tipo=str(datos.get("tipo") or "valoracion"),
        )
    except CupoYaOcupado:
        # Pudo ocuparlo otro paciente mientras elegía — o el modelo pidió un
        # horario que no existe. En los dos casos la respuesta correcta es la
        # misma: ofrecerle alternativas reales, nunca un error.
        alternativas = await ofrecer_horarios(sede_id, cantidad=MAX_HORARIOS)
        return _json({
            "ok": False,
            "motivo": "ocupado",
            "mensaje": "Ese horario ya no está disponible. Ofrece estas alternativas.",
            "horarios": [
                {"inicio": h.inicio.isoformat(), "legible": fecha_legible(h.inicio)}
                for h in alternativas
            ],
        })
    except ValueError as e:
        return _json({"ok": False, "error": str(e)})

    efecto.cita_creada = cita.id
    efecto.sede_agendada = sede_id

    with sesion() as s:
        sede = s.get(Sede, sede_id)

    return _json({
        "ok": True,
        "cuando": fecha_legible(cita.inicio),
        "sede": sede.nombre if sede else "",
        "direccion": sede.direccion if sede else "",
        "mapa": sede.mapa_url if sede else "",
        "referencias": sede.referencias if sede else "",
        "recordatorio": "Se le enviará un recordatorio 24 horas antes.",
        "instruccion": (
            "Confírmasela al paciente con fecha, hora y la dirección completa "
            "de esa sede."
        ),
    })


async def _cancelar(ctx: Contexto) -> str:
    from app.agenda.service import cancelar
    from app.recordatorios import _proxima_cita

    cita = _proxima_cita(ctx.telefono)
    if not cita:
        return _json({
            "ok": False,
            "error": "No tiene ninguna cita próxima registrada a su nombre.",
        })

    await cancelar(cita.id, por="paciente")
    return _json({
        "ok": True,
        "cancelada": fecha_legible(cita.inicio),
        "instruccion": (
            "Confirma la cancelación y ofrécele reagendar cuando quiera, sin "
            "presionarlo."
        ),
    })


def _json(datos: dict) -> str:
    return json.dumps(datos, ensure_ascii=False, default=str)
