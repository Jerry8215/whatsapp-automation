"""
Pruebas del webhook.

Es la puerta de entrada desde internet, y la única defensa es la firma. Sin
ella, cualquiera que conozca la URL podría inyectar mensajes falsos y hacer
que el asistente agende citas o responda en nombre del consultorio.

También se verifica que SIEMPRE se responda 200 rápido: si Meta no recibe
respuesta a tiempo reintenta, y el paciente termina recibiendo la misma
respuesta varias veces.
"""

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.config import config
from app.main import aplicacion


@pytest.fixture
def cliente():
    with TestClient(aplicacion) as c:
        yield c


def firmar(cuerpo: bytes, secreto: str) -> str:
    return "sha256=" + hmac.new(
        secreto.encode(), cuerpo, hashlib.sha256
    ).hexdigest()


CARGA = {
    "entry": [{
        "changes": [{
            "value": {
                "contacts": [{"wa_id": "5213311112222", "profile": {"name": "Ana"}}],
                "messages": [{
                    "id": "wamid.PRUEBA",
                    "from": "5213311112222",
                    "type": "text",
                    "timestamp": "1700000000",
                    "text": {"body": "Hola"},
                }],
            }
        }]
    }]
}


# ----------------------------------------------------------------------
#  Verificación inicial de Meta
# ----------------------------------------------------------------------

def test_meta_puede_verificar_el_webhook(cliente):
    r = cliente.get("/webhook", params={
        "hub.mode": "subscribe",
        "hub.verify_token": config.wa_verify_token,
        "hub.challenge": "12345",
    })
    assert r.status_code == 200
    assert r.text == "12345", "Debe devolver el desafío tal cual"


def test_un_token_de_verificacion_incorrecto_se_rechaza(cliente):
    r = cliente.get("/webhook", params={
        "hub.mode": "subscribe",
        "hub.verify_token": "no-es-el-token",
        "hub.challenge": "12345",
    })
    assert r.status_code == 403


def test_sin_token_no_se_verifica(cliente):
    assert cliente.get("/webhook", params={"hub.mode": "subscribe"}).status_code == 403


# ----------------------------------------------------------------------
#  Firma
# ----------------------------------------------------------------------

def test_sin_firma_se_rechaza(cliente, monkeypatch):
    monkeypatch.setattr(config, "wa_app_secret", "secreto-de-prueba")
    r = cliente.post("/webhook", json=CARGA)
    assert r.status_code == 403, "Aceptó una carga sin firmar"


def test_una_firma_invalida_se_rechaza(cliente, monkeypatch):
    monkeypatch.setattr(config, "wa_app_secret", "secreto-de-prueba")
    cuerpo = json.dumps(CARGA).encode()
    r = cliente.post(
        "/webhook", content=cuerpo,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": firmar(cuerpo, "otro-secreto"),
        },
    )
    assert r.status_code == 403, "Aceptó una firma hecha con otro secreto"


def test_una_firma_valida_se_acepta(cliente, monkeypatch):
    monkeypatch.setattr(config, "wa_app_secret", "secreto-de-prueba")
    cuerpo = json.dumps(CARGA).encode()
    r = cliente.post(
        "/webhook", content=cuerpo,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": firmar(cuerpo, "secreto-de-prueba"),
        },
    )
    assert r.status_code == 200


def test_un_cuerpo_alterado_invalida_la_firma(cliente, monkeypatch):
    """El ataque real: firma legítima capturada, contenido cambiado."""
    monkeypatch.setattr(config, "wa_app_secret", "secreto-de-prueba")
    original = json.dumps(CARGA).encode()
    firma = firmar(original, "secreto-de-prueba")

    alterado = json.dumps({
        **CARGA,
        "entry": [{"changes": [{"value": {"messages": [{
            "id": "wamid.FALSO", "from": "5219999999999", "type": "text",
            "text": {"body": "Confirmo la cita"},
        }]}}]}],
    }).encode()

    r = cliente.post(
        "/webhook", content=alterado,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": firma},
    )
    assert r.status_code == 403, "Aceptó un cuerpo alterado con firma vieja"


# ----------------------------------------------------------------------
#  Respuesta a Meta
# ----------------------------------------------------------------------

def test_una_carga_ilegible_igual_responde_200(cliente, monkeypatch):
    """
    Si devolviéramos error, Meta reintenta y el paciente recibe la misma
    respuesta varias veces.
    """
    monkeypatch.setattr(config, "wa_app_secret", "")
    r = cliente.post(
        "/webhook", content=b"esto no es json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200


def test_una_carga_vacia_responde_200(cliente, monkeypatch):
    monkeypatch.setattr(config, "wa_app_secret", "")
    assert cliente.post("/webhook", json={"entry": []}).status_code == 200


def test_un_acuse_de_entrega_responde_200(cliente, monkeypatch):
    monkeypatch.setattr(config, "wa_app_secret", "")
    r = cliente.post("/webhook", json={"entry": [{"changes": [{"value": {
        "statuses": [{"id": "wamid.X", "status": "delivered",
                      "recipient_id": "5213311112222"}]
    }}]}]})
    assert r.status_code == 200
