"""
Datos de demostración.  `python -m app.demo`

Mete conversaciones por el circuito real —barrera clínica, clasificación,
escalado y flujos— para que el panel se pueda mostrar con contenido en
lugar de vacío.

SOLO PARA DESARROLLO Y DEMOSTRACIÓN. Los pacientes son inventados. No
ejecutar contra la base de producción.
"""

from __future__ import annotations

import asyncio
import sys

from sqlmodel import select

from app.config import config
from app.db import crear_tablas, sesion
from app.models import Conversacion, Mensaje, Paciente
from app.whatsapp.parser import MensajeEntrante

# (teléfono, nombre, [mensajes del paciente])
GUIONES: list[tuple[str, str, list[str]]] = [
    (
        "5213314289077", "Ana López",
        [
            "Buenos días, tengo dolor muy fuerte del lado derecho desde anoche "
            "y traigo 39 de fiebre",
        ],
    ),
    (
        "5213322104455", "Roberto Méndez",
        [
            "Hola, buenos días",
            "Quiero hablar con el doctor Padilla antes de agendar la cirugía",
        ],
    ),
    (
        "5213319027714", "Teresa Ruiz",
        [
            "Buenas tardes",
            "Ya van tres veces que me cambian la cita, no me parece",
        ],
    ),
    (
        "5213333881206", "M. Fernanda Salas",
        [
            "Hola, los encontré en Doctoralia",
            "Quisiera agendar una cita",
        ],
    ),
    (
        "5213317556390", "Jorge Aguilar",
        [
            "Buen día, los vi en Google",
            "¿Cuánto cuesta la consulta?",
        ],
    ),
    (
        "5213320448831", "Claudia Ibarra",
        [
            "Hola",
            "¿Es normal que la herida se vea un poco rosada?",
        ],
    ),
    (
        "5213311662078", "Luis Ramírez",
        [
            "Buenos días",
            "¿Dónde está el consultorio?",
        ],
    ),
    (
        "5213328715540", "Sofía Delgado",
        [
            "Buenas tardes, ¿qué horarios manejan?",
        ],
    ),
    (
        "5213345612390", "Ernesto Vidal",
        [
            "Hola, me recomendó un conocido",
            "Necesito una factura de mi consulta del mes pasado",
        ],
    ),
]


async def sembrar_demo() -> None:
    from app.brain.router import procesar_mensaje

    crear_tablas()

    for telefono, nombre, mensajes in GUIONES:
        for i, texto in enumerate(mensajes):
            await procesar_mensaje(MensajeEntrante(
                wa_message_id=f"demo.{telefono}.{i}",
                telefono=telefono,
                nombre_perfil=nombre,
                texto=texto,
            ))
            await asyncio.sleep(0.02)

    with sesion() as s:
        pacientes = len(s.exec(select(Paciente)).all())
        convs = list(s.exec(select(Conversacion)).all())
        mensajes = len(s.exec(select(Mensaje)).all())

    atencion = sum(1 for c in convs if c.estado.value == "atencion")

    print(f"\n  {pacientes} pacientes · {len(convs)} conversaciones · {mensajes} mensajes")
    print(f"  {atencion} requieren atención de una persona\n")
    print("  Abrir el panel:  http://localhost:8000/panel")
    print("  Usuario:         doctor@consultorio.local")
    print("  Contraseña:      cambiar-en-el-primer-acceso\n")


if __name__ == "__main__":
    if config.entorno == "produccion":
        sys.exit("No se ejecuta contra producción.")
    asyncio.run(sembrar_demo())
