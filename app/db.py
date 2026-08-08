"""Motor y sesiones de base de datos."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from app.config import config

if config.url_base_datos.startswith("sqlite"):
    Path("datos").mkdir(exist_ok=True)

_conectar_args = (
    {"check_same_thread": False} if config.url_base_datos.startswith("sqlite") else {}
)

motor = create_engine(
    config.url_base_datos,
    echo=False,
    pool_pre_ping=True,
    connect_args=_conectar_args,
)


def crear_tablas() -> None:
    import app.models  # noqa: F401  (registra los modelos)

    SQLModel.metadata.create_all(motor)


def obtener_sesion() -> Iterator[Session]:
    with Session(motor) as sesion:
        yield sesion


def sesion() -> Session:
    """Sesión suelta, para tareas de fondo y scripts."""
    return Session(motor)
