"""
Migraciones de esquema.

`SQLModel.metadata.create_all` crea las tablas que faltan, pero **no agrega
columnas a una tabla que ya existe**. En una base recién creada eso no se
nota; en la del consultorio, con conversaciones y citas dentro, significa
que una columna nueva simplemente no aparece y todo falla al leerla.

Esto lo resuelve con lo mínimo indispensable: mira qué columnas hay y
agrega las que falten. Es idempotente —se ejecuta en cada arranque y no
hace nada si ya está todo— y no borra ni reescribe datos nunca.

No pretende ser Alembic. Cuando el proyecto necesite renombrar columnas o
migrar datos, hay que traer una herramienta de verdad. Para agregar
columnas opcionales, esto alcanza y no agrega una dependencia.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from app.db import motor

log = logging.getLogger(__name__)

#: tabla → columna → definición SQL. Todas deben ser opcionales o traer un
#: valor por defecto: se están agregando sobre filas que ya existen.
COLUMNAS_NUEVAS: dict[str, dict[str, str]] = {
    "sede": {
        "calendario_google_id": "VARCHAR DEFAULT ''",
    },
    "cita": {
        "profesional_id": "INTEGER",
    },
    "paciente": {
        "baja_en": "TIMESTAMP",
    },
}


def aplicar() -> None:
    inspector = inspect(motor)
    tablas = set(inspector.get_table_names())

    for tabla, columnas in COLUMNAS_NUEVAS.items():
        if tabla not in tablas:
            continue  # la crea create_all, ya con todo
        existentes = {c["name"] for c in inspector.get_columns(tabla)}
        for columna, definicion in columnas.items():
            if columna in existentes:
                continue
            _agregar(tabla, columna, definicion)


def _agregar(tabla: str, columna: str, definicion: str) -> None:
    sentencia = f'ALTER TABLE "{tabla}" ADD COLUMN "{columna}" {definicion}'
    try:
        with motor.begin() as conexion:
            conexion.execute(text(sentencia))
        log.info("Migración: %s.%s agregada", tabla, columna)
    except Exception:
        # Una carrera entre dos instancias arrancando a la vez puede hacer
        # que la segunda encuentre la columna ya creada. No es un error.
        log.exception("No se pudo agregar %s.%s", tabla, columna)
