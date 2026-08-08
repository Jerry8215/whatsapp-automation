"""
Pruebas del simulador.

En producción crea pacientes, conversaciones y citas reales, así que no
puede quedar abierto a cualquiera que adivine la URL.
"""

import os

import pytest
from fastapi.testclient import TestClient

from app.main import aplicacion


@pytest.fixture
def cliente():
    with TestClient(aplicacion) as c:
        yield c


def test_en_desarrollo_es_de_acceso_libre(cliente):
    """Para poder probar el asistente sin fricción mientras se construye."""
    assert cliente.get("/simulador").status_code == 200


def test_el_mensaje_pasa_por_el_circuito_real(cliente, telefono):
    r = cliente.post("/simulador/mensaje", json={
        "telefono": telefono, "texto": "Tengo un dolor muy fuerte y fiebre alta"})
    assert r.status_code == 200

    d = r.json()
    texto = " ".join(m["texto"] for m in d["mensajes"]).lower()
    assert "urgencias" in texto, "No aplicó la barrera clínica"
    assert d["estado"]["motivo"] == "posible_urgencia"


def test_reiniciar_borra_el_paciente_de_prueba(cliente, telefono):
    cliente.post("/simulador/mensaje", json={"telefono": telefono, "texto": "Hola"})
    assert cliente.post("/simulador/reiniciar", json={"telefono": telefono}).status_code == 200
    assert cliente.get("/simulador/historial", params={"telefono": telefono}).json()["mensajes"] == []
