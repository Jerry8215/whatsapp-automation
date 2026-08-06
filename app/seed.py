"""
Datos iniciales.  `python -m app.seed`

Las sedes, precios y horarios de aquí son PROVISIONALES: quedan a la
espera del contenido real del consultorio (punto 3 de lo pedido al Dr.
Padilla). Sirven para poder probar el circuito completo contra el número
de prueba de Meta mientras tanto.
"""

from __future__ import annotations

import json

from sqlmodel import select

from app.db import crear_tablas, sesion
from app.models import (
    Ajuste,
    Intencion,
    RespuestaFrecuente,
    RolUsuario,
    Sede,
    Usuario,
)
from app.security import cifrar_clave

L, M, X, J, V = 0, 1, 2, 3, 4


SEDES = [
    dict(
        nombre="Torre Médica Providencia",
        direccion="(pendiente de confirmar con el consultorio)",
        referencias="",
        horarios="Lunes, miércoles y viernes de 9:00 a 14:00",
        horario_json=json.dumps([
            {"dia": L, "desde": "09:00", "hasta": "14:00"},
            {"dia": X, "desde": "09:00", "hasta": "14:00"},
            {"dia": V, "desde": "09:00", "hasta": "14:00"},
        ]),
        duracion_cita_min=30,
        # Precio provisional. Lo confirma el consultorio (punto 3 del pedido).
        precio_valoracion=900,
        activa=True,
        orden=1,
    ),
    dict(
        nombre="Hospital Puerta de Hierro",
        direccion="(pendiente de confirmar con el consultorio)",
        horarios="Martes y jueves de 16:00 a 20:00",
        precio_valoracion=900,
        horario_json=json.dumps([
            {"dia": M, "desde": "16:00", "hasta": "20:00"},
            {"dia": J, "desde": "16:00", "hasta": "20:00"},
        ]),
        duracion_cita_min=30,
        activa=True,
        orden=2,
    ),
    dict(
        nombre="Tercera sede",
        direccion="(pendiente de confirmar con el consultorio)",
        horarios="",
        horario_json="[]",
        # Inactiva a propósito: no se ofrece hasta que el consultorio la active.
        activa=False,
        orden=3,
    ),
]


FRECUENTES = [
    (Intencion.INFORMACION,
     "documentos,llevar,traer,papeles,requisitos",
     "Para su valoración le pedimos traer una identificación oficial y "
     "cualquier estudio que ya tenga (ultrasonidos, análisis, tomografías), "
     "impresos o en su teléfono."),
    (Intencion.INFORMACION,
     "especialidad,que hace,que opera,cirugias",
     "El Dr. Padilla es Cirujano General y Laparoscópico. Atiende "
     "padecimientos de vesícula, hernias, apéndice y cirugía abdominal en "
     "general."),
]


def sembrar() -> None:
    crear_tablas()

    with sesion() as s:
        if not s.exec(select(Sede)).first():
            for datos in SEDES:
                s.add(Sede(**datos))
            print(f"  · {len(SEDES)} sedes creadas (datos provisionales)")

        if not s.exec(select(Usuario)).first():
            s.add(Usuario(
                nombre="Dr. José Guadalupe Padilla",
                correo="doctor@consultorio.local",
                hash_clave=cifrar_clave("cambiar-en-el-primer-acceso"),
                rol=RolUsuario.ADMIN,
            ))
            s.add(Usuario(
                nombre="Asistente",
                correo="asistente@consultorio.local",
                hash_clave=cifrar_clave("cambiar-en-el-primer-acceso"),
                rol=RolUsuario.ASISTENTE,
            ))
            print("  · 2 usuarios creados — CAMBIAR LAS CLAVES ANTES DE PRODUCCIÓN")

        if not s.exec(select(RespuestaFrecuente)).first():
            for intencion, disparadores, respuesta in FRECUENTES:
                s.add(RespuestaFrecuente(
                    intencion=intencion,
                    disparadores=disparadores,
                    respuesta=respuesta,
                ))
            print(f"  · {len(FRECUENTES)} respuestas frecuentes cargadas")

        if not s.get(Ajuste, "modo_asistente"):
            s.add(Ajuste(clave="modo_asistente", valor="hibrido"))

        s.commit()

    print("\nListo. Recordar: las sedes, precios y horarios son provisionales")
    print("hasta que llegue el contenido real del consultorio.")


if __name__ == "__main__":
    sembrar()
