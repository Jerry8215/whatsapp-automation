"""
Panel: profesionales y origen de la agenda.

Las dos cosas que el consultorio administra solo, sin pedirle nada al
desarrollador: a quién deriva el asistente, y de dónde sale la agenda.

Como en el resto del panel, lo que más importa es el control de acceso: la
asistente ve, el doctor cambia.
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.db import sesion
from app.main import aplicacion
from app.models import Ajuste, Profesional, RolUsuario, Usuario
from app.security import cifrar_clave

CLAVE_DOCTOR = "clave-prof-doctor-5521"
CLAVE_ASISTENTE = "clave-prof-asistente-8830"

NUEVA = {
    "nombre": "Ana Ramírez",
    "titulo": "Dra.",
    "especialidad": "Nutrición",
    "telefono_whatsapp": "+52 33 1000 2000",
    "palabras_clave": "doctora, su esposa",
}


@pytest.fixture(scope="module", autouse=True)
def usuarios():
    with sesion() as s:
        if not s.exec(select(Usuario).where(Usuario.correo == "prof-doctor@prueba.local")).first():
            s.add(Usuario(nombre="José Padilla", correo="prof-doctor@prueba.local",
                          hash_clave=cifrar_clave(CLAVE_DOCTOR), rol=RolUsuario.ADMIN))
            s.add(Usuario(nombre="Lucía Márquez", correo="prof-asistente@prueba.local",
                          hash_clave=cifrar_clave(CLAVE_ASISTENTE), rol=RolUsuario.ASISTENTE))
            s.commit()


@pytest.fixture
def cliente():
    with TestClient(aplicacion) as c:
        yield c


def _entrar(cliente, correo, clave):
    r = cliente.post("/panel/api/login", json={"correo": correo, "clave": clave})
    assert r.status_code == 200
    return cliente


@pytest.fixture
def doctor(cliente):
    return _entrar(cliente, "prof-doctor@prueba.local", CLAVE_DOCTOR)


@pytest.fixture
def asistente(cliente):
    return _entrar(cliente, "prof-asistente@prueba.local", CLAVE_ASISTENTE)


@pytest.fixture(autouse=True)
def limpiar():
    yield
    with sesion() as s:
        for p in s.exec(select(Profesional)).all():
            s.delete(p)
        ajuste = s.get(Ajuste, "agenda_origen")
        if ajuste:
            s.delete(ajuste)
        s.commit()
    from app.agenda.service import reiniciar_proveedor

    reiniciar_proveedor()


# ----------------------------------------------------------------------
#  Profesionales
# ----------------------------------------------------------------------

def test_sin_sesion_no_se_ven(cliente):
    assert cliente.get("/panel/api/profesionales").status_code == 401


def test_la_asistente_ve_pero_no_modifica(asistente):
    assert asistente.get("/panel/api/profesionales").status_code == 200
    assert asistente.post("/panel/api/profesionales", json=NUEVA).status_code == 403


def test_el_doctor_agrega_a_la_otra_profesional(doctor):
    r = doctor.post("/panel/api/profesionales", json=NUEVA)
    assert r.status_code == 200

    listado = doctor.get("/panel/api/profesionales").json()
    creada = [p for p in listado if p["nombre"] == "Ana Ramírez"][0]

    assert creada["deriva"] is True
    assert creada["nombre_completo"] == "Dra. Ana Ramírez"
    assert creada["incompleto"] is False


def test_el_numero_se_guarda_sin_espacios(doctor):
    """Un número con espacios no sirve como enlace de WhatsApp."""
    doctor.post("/panel/api/profesionales", json=NUEVA)
    creada = doctor.get("/panel/api/profesionales").json()[0]
    assert creada["telefono_whatsapp"] == "+523310002000"


def test_sin_numero_el_panel_lo_marca_como_incompleto(doctor):
    """
    El asistente reconocería a quién busca el paciente y no tendría qué
    contestarle. Es una configuración a medias y se ve como tal.
    """
    doctor.post("/panel/api/profesionales",
                json={**NUEVA, "telefono_whatsapp": ""})
    creada = doctor.get("/panel/api/profesionales").json()[0]
    assert creada["incompleto"] is True


def test_no_se_puede_crear_sin_nombre(doctor):
    r = doctor.post("/panel/api/profesionales", json={**NUEVA, "nombre": "  "})
    assert r.status_code == 400


def test_desactivar_deja_de_derivar_sin_perder_los_datos(doctor):
    doctor.post("/panel/api/profesionales", json=NUEVA)
    creada = doctor.get("/panel/api/profesionales").json()[0]

    assert doctor.put(f"/panel/api/profesionales/{creada['id']}",
                      json={"activo": False}).status_code == 200

    from app.brain import derivacion

    assert derivacion.detectar("quiero cita con la doctora") is None
    # Los datos siguen: se puede volver a activar con un clic.
    assert doctor.get("/panel/api/profesionales").json()[0]["telefono_whatsapp"]


def test_el_principal_no_puede_derivar_a_su_propio_numero(doctor):
    with sesion() as s:
        p = Profesional(nombre="José Guadalupe Padilla", titulo="Dr.", principal=True)
        s.add(p)
        s.commit()
        s.refresh(p)
        principal = p.id

    r = doctor.put(f"/panel/api/profesionales/{principal}", json={"deriva": True})
    assert r.status_code == 400
    assert "este número" in r.json()["detail"]


def test_al_principal_no_se_lo_puede_borrar(doctor):
    with sesion() as s:
        p = Profesional(nombre="José Guadalupe Padilla", titulo="Dr.", principal=True)
        s.add(p)
        s.commit()
        s.refresh(p)
        principal = p.id

    assert doctor.delete(f"/panel/api/profesionales/{principal}").status_code == 400


def test_los_cambios_quedan_auditados(doctor):
    from app.models import RegistroAuditoria

    doctor.post("/panel/api/profesionales", json=NUEVA)
    with sesion() as s:
        acciones = [r.accion for r in s.exec(select(RegistroAuditoria)).all()]
    assert "profesional.creado" in acciones


# ----------------------------------------------------------------------
#  Origen de la agenda
# ----------------------------------------------------------------------

def test_el_panel_informa_que_google_esta_listo_y_en_pausa(doctor):
    d = doctor.get("/panel/api/config").json()

    assert d["agenda"]["proveedor"] == "franjas"
    assert d["agenda"]["escribe_en_la_agenda"] is False
    assert "google" in d["agenda"]


def test_la_asistente_no_cambia_el_origen(asistente):
    r = asistente.put("/panel/api/agenda/origen", json={"origen": "google"})
    assert r.status_code == 403


def test_no_se_activa_google_sin_credenciales(doctor, monkeypatch):
    """
    Activarlo a ciegas dejaría al asistente sin poder agendar en el acto, y
    el consultorio se enteraría con un paciente esperando.
    """
    from app.config import config

    monkeypatch.setattr(config, "google_cuenta_servicio_json", "", raising=False)

    r = doctor.put("/panel/api/agenda/origen", json={"origen": "google"})
    assert r.status_code == 400
    assert "credenciales" in r.json()["detail"].lower()

    # Y la agenda sigue funcionando como antes.
    assert doctor.get("/panel/api/config").json()["agenda"]["proveedor"] == "franjas"


def test_un_origen_desconocido_se_rechaza(doctor):
    assert doctor.put("/panel/api/agenda/origen",
                      json={"origen": "loquesea"}).status_code == 400


def test_se_puede_activar_google_cuando_la_conexion_responde(doctor, monkeypatch):
    async def prueba_falsa():
        return {"ok": True, "detalle": "Conexión correcta.",
                "correo_servicio": "x@y.iam.gserviceaccount.com", "agendas": []}

    monkeypatch.setattr("app.agenda.google_calendar.probar_conexion", prueba_falsa)
    monkeypatch.setattr("app.config.config.google_cuenta_servicio_json",
                        '{"client_email":"x","private_key":"y"}', raising=False)

    assert doctor.put("/panel/api/agenda/origen",
                      json={"origen": "google"}).status_code == 200
    assert doctor.get("/panel/api/config").json()["agenda"]["proveedor"] == "google"


def test_volver_a_franjas_siempre_se_puede(doctor, monkeypatch):
    """
    La marcha atrás no puede depender de que Google responda: si algo sale
    mal, el consultorio tiene que poder volver al camino conocido.
    """
    with sesion() as s:
        s.add(Ajuste(clave="agenda_origen", valor="google"))
        s.commit()

    assert doctor.put("/panel/api/agenda/origen",
                      json={"origen": "franjas"}).status_code == 200
    assert doctor.get("/panel/api/config").json()["agenda"]["proveedor"] == "franjas"


def test_la_prueba_de_conexion_es_solo_del_doctor(asistente):
    assert asistente.get("/panel/api/agenda/google/prueba").status_code == 403
