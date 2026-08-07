"""
Configuración de las pruebas.

Se fija el entorno ANTES de importar nada de `app`, porque la
configuración se resuelve al importar el módulo.
"""

import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="consultorio-test-"))

os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'prueba.db').as_posix()}"
os.environ["ENTORNO"] = "desarrollo"
os.environ["MODO_ASISTENTE"] = "basico"      # sin llamadas a OpenAI
os.environ["OPENAI_API_KEY"] = ""
os.environ["WA_TOKEN"] = ""                  # los envíos quedan simulados
os.environ["WA_PHONE_NUMBER_ID"] = ""
os.environ["AGENDA_PROVEEDOR"] = "franjas"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["SMTP_HOST"] = ""

import pytest  # noqa: E402

from app.db import crear_tablas, sesion  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def base_de_datos():
    crear_tablas()
    _sembrar_minimo()
    yield


def _sembrar_minimo() -> None:
    import json

    from sqlmodel import select

    from app.models import Sede

    with sesion() as s:
        if s.exec(select(Sede)).first():
            return
        s.add(Sede(
            nombre="Torre Médica Providencia",
            direccion="Av. Pablo Neruda 3265, Providencia",
            referencias="Estacionamiento en el sótano",
            horarios="Lunes, miércoles y viernes de 9:00 a 14:00",
            horario_json=json.dumps([
                {"dia": 0, "desde": "09:00", "hasta": "14:00"},
                {"dia": 2, "desde": "09:00", "hasta": "14:00"},
                {"dia": 4, "desde": "09:00", "hasta": "14:00"},
            ]),
            precio_valoracion=900,
            duracion_cita_min=30,
            activa=True,
            orden=1,
        ))
        s.add(Sede(
            nombre="Hospital Puerta de Hierro",
            direccion="Av. Empresarios 150, Puerta de Hierro",
            horarios="Martes y jueves de 16:00 a 20:00",
            horario_json=json.dumps([
                {"dia": 1, "desde": "16:00", "hasta": "20:00"},
                {"dia": 3, "desde": "16:00", "hasta": "20:00"},
            ]),
            precio_valoracion=1000,
            duracion_cita_min=30,
            activa=True,
            orden=2,
        ))
        s.add(Sede(
            nombre="Tercera sede",
            direccion="(sin publicar)",
            horario_json="[]",
            activa=False,      # no debe ofrecerse nunca
            orden=3,
        ))
        s.commit()


@pytest.fixture
def telefono():
    """Un número distinto por prueba, para no cruzar conversaciones."""
    import uuid

    return "521333" + uuid.uuid4().hex[:7]
