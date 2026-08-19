"""
Registrar en el panel una cita que entró por Doctoralia.

Es la pieza que hace que el asistente deje de ser ciego.

Hasta acá el sistema solo conocía las citas que él mismo había agendado.
Una cita tomada por Doctoralia —que son la mayoría— no existía para él: no
podía confirmarla, no podía mandarle el recordatorio de 24 horas, y el
paciente que escribía por ella terminaba derivado a una persona.

Con esto, la asistente la carga en segundos y el asistente la trata como
cualquier otra.
"""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.db import sesion
from app.main import aplicacion
from app.models import Ajuste, Cita, EstadoCita, Paciente, RolUsuario, Sede, Usuario
from app.security import cifrar_clave
from app.tiempo import a_local

CLAVE = "clave-registro-7788"


@pytest.fixture(scope="module", autouse=True)
def usuario_registro():
    with sesion() as s:
        if not s.exec(select(Usuario).where(Usuario.correo == "reg@prueba.local")).first():
            s.add(Usuario(nombre="Lucía Márquez", correo="reg@prueba.local",
                          hash_clave=cifrar_clave(CLAVE), rol=RolUsuario.ASISTENTE))
            s.commit()


@pytest.fixture
def asistente():
    with TestClient(aplicacion) as c:
        r = c.post("/panel/api/login", json={"correo": "reg@prueba.local", "clave": CLAVE})
        assert r.status_code == 200
        yield c


@pytest.fixture
def sede_id():
    with sesion() as s:
        return s.exec(select(Sede).where(Sede.activa).order_by(Sede.orden)).first().id  # type: ignore[arg-type]


def _cuando(dias=3, hora=11):
    """Fecha futura, en hora del consultorio — que es como la escribe una persona."""
    d = a_local(datetime.utcnow()) + timedelta(days=dias)
    return d.replace(hour=hora, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")


#: Todos los teléfonos de este archivo empiezan así, para poder limpiar
#: exactamente lo que creó esta prueba y nada más. Borrar por «fuente» se
#: llevaba por delante pacientes de otros archivos.
PREFIJO = "5213391"


@pytest.fixture(autouse=True)
def limpiar():
    yield
    with sesion() as s:
        pacientes = list(s.exec(
            select(Paciente).where(Paciente.telefono.startswith(PREFIJO))  # type: ignore[attr-defined]
        ).all())
        for p in pacientes:
            for c in s.exec(select(Cita).where(Cita.paciente_id == p.id)).all():
                s.delete(c)
        s.commit()
        for p in pacientes:
            s.delete(p)
        ajuste = s.get(Ajuste, "agenda_origen")
        if ajuste:
            s.delete(ajuste)
        s.commit()
    from app.agenda.service import reiniciar_proveedor

    reiniciar_proveedor()


def _ultima_cita() -> Cita | None:
    """La más reciente que registró esta prueba, no la primera que aparezca."""
    with sesion() as s:
        return s.exec(
            select(Cita)
            .where(Cita.creada_por == "reg@prueba.local")
            .order_by(Cita.id.desc())  # type: ignore[attr-defined]
        ).first()


# ----------------------------------------------------------------------

def test_sin_sesion_no_se_registra_nada(sede_id):
    with TestClient(aplicacion) as c:
        assert c.post("/panel/api/citas", json={}).status_code == 401


def test_la_asistente_puede_registrarla(asistente, sede_id):
    """
    Es su tarea diaria, así que no se le exige ser administradora.
    """
    r = asistente.post("/panel/api/citas", json={
        "telefono": "5213391112233", "nombre": "Ana López Registro",
        "sede_id": sede_id, "inicio": _cuando(),
    })
    assert r.status_code == 200

    cita = _ultima_cita()
    assert cita is not None
    assert cita.estado is EstadoCita.AGENDADA


def test_no_aparece_en_la_lista_de_por_cargar(asistente, sede_id):
    """
    Vino de Doctoralia: allá ya está. Mandarla a la lista de pendientes de
    la asistente sería pedirle que cargue lo que acaba de copiar.
    """
    asistente.post("/panel/api/citas", json={
        "telefono": "5213391112244", "nombre": "Ana López Registro",
        "sede_id": sede_id, "inicio": _cuando(),
    })
    pendientes = asistente.get("/panel/api/por-cargar").json()
    assert not any(p["paciente"] == "Ana López Registro" for p in pendientes)


def test_crea_al_paciente_si_no_existia(asistente, sede_id):
    asistente.post("/panel/api/citas", json={
        "telefono": "5213391112255", "nombre": "Ana López Registro",
        "sede_id": sede_id, "inicio": _cuando(),
    })
    with sesion() as s:
        p = s.exec(select(Paciente).where(Paciente.telefono == "5213391112255")).first()
    assert p is not None
    assert p.fuente == "doctoralia"


def test_la_hora_se_guarda_en_utc_y_se_muestra_local(asistente, sede_id):
    """
    Lo que escribe la asistente es hora del consultorio. Si se guardara tal
    cual, al paciente le llegaría el recordatorio con seis horas de
    diferencia.
    """
    cuando = _cuando(dias=4, hora=10)
    asistente.post("/panel/api/citas", json={
        "telefono": "5213391112266", "sede_id": sede_id, "inicio": cuando,
    })

    cita = _ultima_cita()

    # Lo que ve una persona es la hora que escribió; lo guardado es UTC, que
    # en Guadalajara son seis horas distintas.
    assert a_local(cita.inicio).hour == 10
    assert cita.inicio != a_local(cita.inicio)


def test_avisa_si_ya_hay_algo_a_esa_hora(asistente, sede_id):
    cuando = _cuando(dias=5, hora=12)
    asistente.post("/panel/api/citas", json={
        "telefono": "5213391112277", "sede_id": sede_id, "inicio": cuando,
    })

    r = asistente.post("/panel/api/citas", json={
        "telefono": "5213391112288", "sede_id": sede_id, "inicio": cuando,
    })
    assert r.status_code == 409
    assert "ya hay una cita" in r.json()["detail"].lower()


def test_se_puede_registrar_igual_si_el_consultorio_lo_decide(asistente, sede_id):
    """
    El sistema avisa, no manda. Un consultorio puede sobreponer dos citas a
    propósito y no es asunto del software discutirlo.
    """
    cuando = _cuando(dias=6, hora=13)
    asistente.post("/panel/api/citas", json={
        "telefono": "5213391112299", "sede_id": sede_id, "inicio": cuando,
    })
    r = asistente.post("/panel/api/citas", json={
        "telefono": "5213391113300", "sede_id": sede_id, "inicio": cuando,
        "forzar": True,
    })
    assert r.status_code == 200


@pytest.mark.parametrize("cuerpo", [
    {"telefono": "", "inicio": "2026-09-01T10:00"},
    {"telefono": "5213391110000", "inicio": "no es una fecha"},
])
def test_datos_invalidos_se_rechazan(asistente, sede_id, cuerpo):
    r = asistente.post("/panel/api/citas", json={**cuerpo, "sede_id": sede_id})
    assert r.status_code == 400


def test_una_sede_inexistente_se_rechaza(asistente):
    r = asistente.post("/panel/api/citas", json={
        "telefono": "5213391114400", "sede_id": 99999, "inicio": _cuando(),
    })
    assert r.status_code == 404


def test_queda_auditada(asistente, sede_id):
    from app.models import RegistroAuditoria

    asistente.post("/panel/api/citas", json={
        "telefono": "5213391115500", "nombre": "Ana López Registro",
        "sede_id": sede_id, "inicio": _cuando(),
    })
    with sesion() as s:
        acciones = [r.accion for r in s.exec(select(RegistroAuditoria)).all()]
    assert "cita.registrada" in acciones


# ----------------------------------------------------------------------
#  Con Google como agenda
# ----------------------------------------------------------------------

def test_con_google_activo_la_cita_se_escribe_tambien_en_google(
    asistente, sede_id, monkeypatch
):
    """
    Es el punto del camino 2: una sola agenda. Si la cita quedara solo en el
    panel, la agenda del doctor seguiría incompleta.
    """
    escritas = []

    async def registrar_falso(**kwargs):
        escritas.append(kwargs)
        return "evento-doctoralia-1"

    monkeypatch.setattr("app.agenda.google_calendar.registrar_evento", registrar_falso)
    monkeypatch.setattr("app.config.config.google_cuenta_servicio_json",
                        '{"client_email":"x","private_key":"y"}', raising=False)

    with sesion() as s:
        s.add(Ajuste(clave="agenda_origen", valor="google"))
        s.commit()
    from app.agenda.service import reiniciar_proveedor

    reiniciar_proveedor()

    r = asistente.post("/panel/api/citas", json={
        "telefono": "5213391116600", "nombre": "Ana López Registro",
        "sede_id": sede_id, "inicio": _cuando(dias=7),
    })

    assert r.status_code == 200
    assert r.json()["en_google"] is True
    assert len(escritas) == 1

    assert _ultima_cita().externo_id == "evento-doctoralia-1"


def test_si_google_falla_no_se_guarda_una_cita_a_medias(
    asistente, sede_id, monkeypatch
):
    """
    Guardarla solo en el panel dejaría al consultorio creyendo que está en
    su agenda de Google cuando no está. Mejor fallar de frente.
    """
    async def revienta(**kwargs):
        raise RuntimeError("Google no responde")

    monkeypatch.setattr("app.agenda.google_calendar.registrar_evento", revienta)
    monkeypatch.setattr("app.config.config.google_cuenta_servicio_json",
                        '{"client_email":"x","private_key":"y"}', raising=False)

    with sesion() as s:
        s.add(Ajuste(clave="agenda_origen", valor="google"))
        s.commit()
    from app.agenda.service import reiniciar_proveedor

    reiniciar_proveedor()

    r = asistente.post("/panel/api/citas", json={
        "telefono": "5213391117700", "sede_id": sede_id, "inicio": _cuando(dias=8),
    })

    assert r.status_code == 502
    assert _ultima_cita() is None


# ----------------------------------------------------------------------
#  Lo que esto habilita
# ----------------------------------------------------------------------

def test_una_cita_de_doctoralia_ya_recibe_recordatorio(asistente, sede_id):
    """
    La razón de ser de todo esto. Antes, el recordatorio de 24 horas solo
    le llegaba a los pacientes de WhatsApp, que son la minoría.
    """
    import asyncio

    from app.agenda.service import citas_para_recordar
    from app.tiempo import a_local as _a_local

    en_23_horas = _a_local(datetime.utcnow() + timedelta(hours=23))
    # `forzar` porque acá no se está probando la detección de choques: otra
    # prueba puede haber dejado algo a esa misma hora y el 409 haría fallar
    # esto por un motivo que no tiene nada que ver.
    r = asistente.post("/panel/api/citas", json={
        "telefono": "5213391118800", "nombre": "Ana López Registro", "sede_id": sede_id,
        "inicio": en_23_horas.strftime("%Y-%m-%dT%H:%M"), "forzar": True,
    })
    assert r.status_code == 200, r.text

    pendientes = asyncio.run(citas_para_recordar())
    assert any(c.creada_por == "reg@prueba.local" for c in pendientes)
