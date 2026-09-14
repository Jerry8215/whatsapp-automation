"""
El número al que se le responde a un paciente mexicano.

En la primera prueba real, el Dr. Padilla le escribió al número de prueba,
el asistente armó la respuesta y Meta la rechazó con el error 131030:
«número no incluido en la lista de autorizados».

La causa: Meta entrega los celulares mexicanos como `521` más diez
dígitos, pero para enviar espera `52` más diez dígitos, porque México
eliminó el prefijo «1» de móvil en 2020. Responder al mismo número que
llegó falla siempre.
"""

import pytest

from app.whatsapp import client


@pytest.mark.parametrize("entrada,esperado", [
    ("5216391227780", "526391227780"),     # así llega por el webhook
    ("5213312345678", "523312345678"),     # Guadalajara
    ("+52 1 639 122 7780", "526391227780"),
])
def test_el_celular_mexicano_pierde_el_uno_al_enviar(entrada, esperado):
    assert client.destinatario(entrada) == esperado


@pytest.mark.parametrize("numero", [
    "526391227780",     # ya viene en el formato correcto
    "15551635914",      # Estados Unidos, el número de prueba de Meta
    "34612345678",      # España
    "5491123456789",    # Argentina: se deja intacto a propósito
])
def test_los_demas_numeros_no_se_tocan(numero):
    """
    Solo se corrige México, que es lo que se comprobó. Aplicar la misma
    regla a otro país sin haberlo verificado podría romper números que hoy
    funcionan.
    """
    assert client.destinatario(numero) == numero


@pytest.mark.asyncio
async def test_toda_respuesta_sale_con_el_numero_corregido(monkeypatch):
    """
    La corrección vive en el único punto por donde pasan todos los envíos:
    texto, botones, listas, plantillas y recordatorios.
    """
    enviados = []

    class Respuesta:
        status_code = 200
        text = "{}"

        def json(self):
            return {"messages": [{"id": "wamid.prueba"}]}

    class Cliente:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, json=None):
            enviados.append(json)
            return Respuesta()

    monkeypatch.setattr(client.config, "wa_token", "token-de-prueba", raising=False)
    monkeypatch.setattr(client.config, "wa_phone_number_id", "123", raising=False)
    monkeypatch.setattr(client.httpx, "AsyncClient", Cliente)

    await client.enviar_texto("5216391227780", "hola")
    await client.enviar_botones("5216391227780", "¿confirma?", [("si", "Sí")])
    await client.enviar_lista("5216391227780", "elija", "Ver", [("a", "A", "")])

    assert [e["to"] for e in enviados] == ["526391227780"] * 3


def test_el_paciente_se_guarda_con_el_numero_tal_como_llego():
    """
    El número se corrige al enviar, no al guardar. Meta identifica al
    paciente con `521…` en cada mensaje: si se guardara corregido, su
    próxima conversación crearía un paciente duplicado.
    """
    from app.whatsapp.parser import extraer

    carga = {"entry": [{"changes": [{"value": {
        "messaging_product": "whatsapp",
        "contacts": [{"wa_id": "5216391227780", "profile": {"name": "Dr. Padilla"}}],
        "messages": [{"from": "5216391227780", "id": "wamid.x", "timestamp": "1",
                      "type": "text", "text": {"body": "Hola"}}],
    }}]}]}
    mensajes, _ = extraer(carga)
    assert mensajes[0].telefono == "5216391227780"
