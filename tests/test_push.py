"""
Pruebas de los avisos push y de la app instalable.

Lo que se verifica acá no es que Google entregue el aviso —eso no se puede
probar sin salir a internet— sino lo que sí depende de nosotros:

  * que el panel se pueda instalar en el celular (manifiesto, íconos y
    service worker servidos donde el navegador los busca);
  * que una suscripción no se duplique ni quede accesible sin sesión;
  * que un endpoint muerto se limpie solo, en vez de reintentarse siempre;
  * y que un fallo del push NUNCA impida que salga el aviso por Telegram o
    por correo. El push es el canal cómodo, no el confiable.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.db import sesion
from app.main import aplicacion
from app.models import RolUsuario, SuscripcionPush, Usuario
from app.security import cifrar_clave

CLAVE = "clave-push-de-prueba-4417"

SUSCRIPCION = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/ABC123",
    "p256dh": "BFakeClavePublicaDePrueba0000000000000000000000000",
    "auth": "claveAuthDePrueba00",
    "agente": "Mozilla/5.0 (iPhone)",
}


@pytest.fixture(scope="module", autouse=True)
def usuario_push():
    with sesion() as s:
        if not s.exec(select(Usuario).where(Usuario.correo == "push@prueba.local")).first():
            s.add(Usuario(
                nombre="Lucía Márquez",
                correo="push@prueba.local",
                hash_clave=cifrar_clave(CLAVE),
                rol=RolUsuario.ADMIN,
            ))
            s.commit()


@pytest.fixture
def cliente():
    with TestClient(aplicacion) as c:
        yield c


@pytest.fixture
def dentro(cliente):
    r = cliente.post("/panel/api/login",
                     json={"correo": "push@prueba.local", "clave": CLAVE})
    assert r.status_code == 200
    return cliente


@pytest.fixture
def con_vapid(monkeypatch):
    """Claves de mentira: alcanzan para todo salvo el envío real."""
    from app.config import config

    monkeypatch.setattr(config, "vapid_clave_publica", "BClavePublicaDePrueba", raising=False)
    monkeypatch.setattr(config, "vapid_clave_privada", "clave-privada-de-prueba", raising=False)
    monkeypatch.setattr(config, "vapid_contacto", "mailto:prueba@consultorio.local", raising=False)
    return config


@pytest.fixture(autouse=True)
def sin_suscripciones():
    """Cada prueba arranca sin suscripciones colgadas de la anterior."""
    yield
    with sesion() as s:
        for fila in s.exec(select(SuscripcionPush)).all():
            s.delete(fila)
        s.commit()


# ----------------------------------------------------------------------
#  La app instalable
# ----------------------------------------------------------------------

def test_el_manifiesto_se_sirve_y_apunta_al_panel(cliente):
    r = cliente.get("/manifest.webmanifest")
    assert r.status_code == 200

    m = json.loads(r.content)
    assert m["start_url"] == "/panel"
    # Sin `standalone` la app se abriría con la barra del navegador, que es
    # exactamente lo que el consultorio pidió evitar.
    assert m["display"] == "standalone"
    # Android exige un ícono maskable, o recorta el nuestro a lo bruto.
    assert any(i.get("purpose") == "maskable" for i in m["icons"])


def test_el_service_worker_se_sirve_desde_la_raiz(cliente):
    """
    Tiene que estar en / y no en /panel/: un service worker solo controla
    lo que cuelga de su propia ruta.
    """
    r = cliente.get("/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert r.headers.get("service-worker-allowed") == "/"
    # Si se cacheara, el panel se quedaría con una versión vieja para siempre.
    assert "no-cache" in r.headers.get("cache-control", "")


def test_el_service_worker_nunca_cachea_la_api():
    """
    Una bandeja vieja mostrada como actual es peor que un error de red: la
    asistente creería que no hay nada pendiente.
    """
    from pathlib import Path

    sw = (Path(__file__).resolve().parent.parent
          / "app" / "panel" / "static" / "sw.js").read_text(encoding="utf-8")
    assert '"/panel/api"' in sw or "'/panel/api'" in sw
    assert "startsWith(\"/panel/api\")" in sw


@pytest.mark.parametrize("ruta", [
    "/iconos/icono-192.png",
    "/iconos/icono-512.png",
    "/iconos/icono-maskable-512.png",
    "/apple-touch-icon.png",
])
def test_los_iconos_existen(cliente, ruta):
    r = cliente.get(ruta)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")


def test_no_se_puede_salir_de_la_carpeta_de_iconos(cliente):
    r = cliente.get("/iconos/..%2F..%2Fconfig.py")
    assert r.status_code == 404


def test_el_panel_declara_el_manifiesto_y_el_icono_de_ios(cliente):
    html = cliente.get("/panel").text
    assert 'rel="manifest"' in html
    assert 'rel="apple-touch-icon"' in html
    assert 'name="apple-mobile-web-app-capable"' in html


# ----------------------------------------------------------------------
#  Suscripciones
# ----------------------------------------------------------------------

@pytest.mark.parametrize("ruta,metodo", [
    ("/panel/api/push/clave", "get"),
    ("/panel/api/push/suscribir", "post"),
    ("/panel/api/push/desuscribir", "post"),
    ("/panel/api/push/prueba", "post"),
])
def test_sin_sesion_no_se_toca_nada(cliente, ruta, metodo):
    r = (cliente.get(ruta) if metodo == "get" else cliente.post(ruta, json={}))
    assert r.status_code == 401


def test_sin_claves_configuradas_el_panel_no_ofrece_la_opcion(dentro):
    r = dentro.get("/panel/api/push/clave")
    assert r.status_code == 200
    assert r.json()["disponible"] is False


def test_sin_claves_configuradas_no_se_acepta_una_suscripcion(dentro):
    r = dentro.post("/panel/api/push/suscribir", json=SUSCRIPCION)
    assert r.status_code == 503


def test_suscribirse_registra_el_aparato(dentro, con_vapid):
    assert dentro.post("/panel/api/push/suscribir", json=SUSCRIPCION).status_code == 200

    info = dentro.get("/panel/api/push/clave").json()
    assert info["disponible"] is True
    assert info["aparatos"] == 1
    assert info["clave_publica"] == con_vapid.vapid_clave_publica


def test_suscribirse_dos_veces_no_duplica_el_aviso(dentro, con_vapid):
    """
    El navegador puede renovar la suscripción y volver a mandarla. Si se
    guardara dos veces, cada aviso llegaría duplicado al mismo teléfono.
    """
    dentro.post("/panel/api/push/suscribir", json=SUSCRIPCION)
    dentro.post("/panel/api/push/suscribir", json=SUSCRIPCION)

    with sesion() as s:
        assert len(s.exec(select(SuscripcionPush)).all()) == 1


def test_desuscribirse_borra_el_aparato(dentro, con_vapid):
    dentro.post("/panel/api/push/suscribir", json=SUSCRIPCION)
    r = dentro.post("/panel/api/push/desuscribir",
                    json={"endpoint": SUSCRIPCION["endpoint"]})
    assert r.json()["ok"] is True
    assert dentro.get("/panel/api/push/clave").json()["aparatos"] == 0


def test_la_activacion_queda_auditada(dentro, con_vapid):
    from app.models import RegistroAuditoria

    dentro.post("/panel/api/push/suscribir", json=SUSCRIPCION)
    with sesion() as s:
        acciones = [r.accion for r in s.exec(select(RegistroAuditoria)).all()]
    assert "push.activado" in acciones


# ----------------------------------------------------------------------
#  Envío
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sin_claves_no_se_intenta_enviar():
    from app.push import avisar_push

    assert await avisar_push(titulo="x", cuerpo="y") == 0


@pytest.mark.asyncio
async def test_el_aviso_sale_a_cada_aparato(con_vapid, monkeypatch):
    from app import push

    for sufijo in ("celular", "compu"):
        push.guardar_suscripcion(
            usuario_id=1, endpoint=f"https://fcm.googleapis.com/{sufijo}",
            p256dh="clave", auth="auth",
        )

    enviados = []
    monkeypatch.setattr(push, "_enviar_una",
                        lambda s, carga: enviados.append((s.endpoint, carga)) or None)

    assert await push.avisar_push(titulo="Requiere atención", cuerpo="Ana López",
                                  conversacion_id=7, urgente=True) == 2

    carga = json.loads(enviados[0][1])
    assert carga["enlace"] == "/panel/conversaciones/7"
    assert carga["urgente"] is True
    # Una etiqueta por conversación: tres mensajes seguidos del mismo
    # paciente actualizan un aviso, no apilan tres.
    assert carga["etiqueta"] == "conv-7"


@pytest.mark.asyncio
async def test_un_endpoint_muerto_se_borra_solo(con_vapid, monkeypatch):
    """
    410 significa que el navegador se desinstaló o revocó el permiso.
    Reintentarlo para siempre llenaría el registro de errores.
    """
    from app import push

    push.guardar_suscripcion(usuario_id=1, endpoint="https://fcm.googleapis.com/muerto",
                             p256dh="clave", auth="auth")
    monkeypatch.setattr(push, "_enviar_una", lambda s, carga: 410)

    assert await push.avisar_push(titulo="x", cuerpo="y") == 0
    with sesion() as s:
        assert s.exec(select(SuscripcionPush)).all() == []


@pytest.mark.asyncio
async def test_un_fallo_pasajero_no_borra_la_suscripcion(con_vapid, monkeypatch):
    from app import push

    push.guardar_suscripcion(usuario_id=1, endpoint="https://fcm.googleapis.com/lento",
                             p256dh="clave", auth="auth")
    monkeypatch.setattr(push, "_enviar_una", lambda s, carga: 500)

    await push.avisar_push(titulo="x", cuerpo="y")
    with sesion() as s:
        assert len(s.exec(select(SuscripcionPush)).all()) == 1


@pytest.mark.asyncio
async def test_si_el_push_falla_el_aviso_igual_sale_por_los_otros_canales(monkeypatch):
    """
    El invariante del módulo de avisos: ningún canal puede tumbar a los
    demás. Un aviso perdido es una conversación que nadie atiende.
    """
    from app import notify

    async def revienta(**kwargs):
        raise RuntimeError("el servicio de push está caído")

    llamados = []

    async def telegram_falso(texto):
        llamados.append("telegram")

    monkeypatch.setattr("app.push.avisar_push", revienta)
    monkeypatch.setattr(notify, "_telegram", telegram_falso)
    monkeypatch.setattr(notify, "_correo", lambda a, c: llamados.append("correo"))

    await notify.avisar(titulo="Requiere atención", cuerpo="Ana López", conversacion_id=3)

    assert llamados == ["telegram", "correo"]
