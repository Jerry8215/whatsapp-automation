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


def test_con_whatsapp_configurado_no_envia_nada_a_meta(cliente, telefono, monkeypatch):
    """
    Producción tiene credenciales de WhatsApp. Antes, el simulador intentaba
    mandar cada respuesta de verdad al número de prueba, Meta la rechazaba y
    la respuesta se perdía: el consultorio veía su pregunta sin contestar.
    """
    import httpx

    monkeypatch.setattr("app.config.config.wa_token", "EAA-de-prueba", raising=False)
    monkeypatch.setattr("app.config.config.wa_phone_number_id", "123", raising=False)

    salidas = []

    async def post(self, *a, **k):
        salidas.append(k.get("json"))
        raise AssertionError("el simulador intentó enviar por WhatsApp")

    monkeypatch.setattr(httpx.AsyncClient, "post", post)

    r = cliente.post("/simulador/mensaje", json={
        "telefono": telefono, "texto": "¿Cuánto cuesta la consulta?"})

    assert salidas == []
    bot = [m for m in r.json()["mensajes"] if m["quien"] != "paciente"]
    assert bot, "la respuesta no quedó registrada"


@pytest.mark.asyncio
async def test_fuera_del_simulador_se_envia_normalmente(monkeypatch):
    """La marca no puede quedar pegada: los pacientes reales deben recibir."""
    from app.whatsapp import client

    with client.simulacion():
        assert (await client.enviar_texto("5213300000000", "x")) == {"simulado": True}

    monkeypatch.setattr("app.config.config.wa_token", "EAA-de-prueba", raising=False)
    monkeypatch.setattr("app.config.config.wa_phone_number_id", "123", raising=False)

    enviados = []

    class Resp:
        status_code = 200
        text = "{}"

        def json(self):
            return {"messages": [{"id": "wamid.1"}]}

    async def post(self, url, **k):
        enviados.append(k["json"]["to"])
        return Resp()

    import httpx

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    await client.enviar_texto("5213300000000", "hola")
    assert enviados == ["523300000000"]
