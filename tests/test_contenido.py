"""
Pruebas de la edición de contenido, la agenda y el cambio de contraseña.

Lo importante acá es la validación de horarios y franjas: si se guardara un
bloque inválido, el asistente dejaría de ofrecer turnos y nadie entendería
por qué. Es un fallo silencioso, del peor tipo.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.db import sesion
from app.main import aplicacion
from app.models import RolUsuario, Sede, Usuario
from app.panel.contenido import validar_bloques
from app.security import cifrar_clave

CLAVE_DOCTOR = "clave-doctor-contenido-31"
CLAVE_ASIST = "clave-asistente-contenido-42"


@pytest.fixture(scope="module", autouse=True)
def usuarios():
    with sesion() as s:
        if not s.exec(select(Usuario).where(Usuario.correo == "doc2@prueba.local")).first():
            s.add(Usuario(nombre="Doctor Dos", correo="doc2@prueba.local",
                          hash_clave=cifrar_clave(CLAVE_DOCTOR), rol=RolUsuario.ADMIN))
            s.add(Usuario(nombre="Asistente Dos", correo="asis2@prueba.local",
                          hash_clave=cifrar_clave(CLAVE_ASIST), rol=RolUsuario.ASISTENTE))
            s.commit()


@pytest.fixture
def doctor():
    with TestClient(aplicacion) as c:
        c.post("/panel/api/login", json={"correo": "doc2@prueba.local", "clave": CLAVE_DOCTOR})
        yield c


@pytest.fixture
def asistente():
    with TestClient(aplicacion) as c:
        c.post("/panel/api/login", json={"correo": "asis2@prueba.local", "clave": CLAVE_ASIST})
        yield c


@pytest.fixture
def sede_id():
    with sesion() as s:
        return s.exec(select(Sede)).first().id


# ----------------------------------------------------------------------
#  Validación de horarios y franjas
# ----------------------------------------------------------------------

@pytest.mark.parametrize("bloques", [
    [],
    [{"dia": 0, "desde": "09:00", "hasta": "14:00"}],
    [{"dia": 1, "desde": "10:00", "hasta": "12:00"},
     {"dia": 3, "desde": "16:00", "hasta": "20:00"}],
    [{"dia": 6, "desde": "00:00", "hasta": "23:59"}],
])
def test_los_bloques_correctos_pasan(bloques):
    assert validar_bloques(bloques) == ""


@pytest.mark.parametrize("bloques,pista", [
    ([{"dia": 7, "desde": "09:00", "hasta": "14:00"}], "día"),
    ([{"dia": -1, "desde": "09:00", "hasta": "14:00"}], "día"),
    ([{"dia": "lunes", "desde": "09:00", "hasta": "14:00"}], "día"),
    ([{"dia": 0, "desde": "25:00", "hasta": "26:00"}], "hora"),
    ([{"dia": 0, "desde": "nueve", "hasta": "14:00"}], "hora"),
    ([{"dia": 0, "desde": "09:00"}], "hora"),
    ([{"dia": 0, "desde": "14:00", "hasta": "09:00"}], "antes de empezar"),
    ([{"dia": 0, "desde": "10:00", "hasta": "10:00"}], "antes de empezar"),
    (["no soy un objeto"], "no es válido"),
    ("{no es json", "formato"),
])
def test_los_bloques_invalidos_se_rechazan(bloques, pista):
    error = validar_bloques(bloques)
    assert error, f"Aceptó algo inválido: {bloques}"
    assert pista in error, f"El mensaje no orienta: {error!r}"


def test_un_horario_invalido_no_se_guarda(doctor, sede_id):
    """
    Es el caso peligroso: si se guardara, el asistente dejaría de ofrecer
    turnos y sería un fallo silencioso.
    """
    with sesion() as s:
        antes = s.get(Sede, sede_id).horario_json

    r = doctor.put(f"/panel/api/sedes/{sede_id}", json={
        "horario_json": [{"dia": 9, "desde": "09:00", "hasta": "14:00"}]
    })
    assert r.status_code == 400

    with sesion() as s:
        assert s.get(Sede, sede_id).horario_json == antes, "Guardó pese al error"


# ----------------------------------------------------------------------
#  Edición de sedes
# ----------------------------------------------------------------------

def test_el_doctor_edita_precio_y_direccion(doctor, sede_id):
    r = doctor.put(f"/panel/api/sedes/{sede_id}", json={
        "direccion": "Av. Pablo Neruda 3265, Providencia",
        "precio_valoracion": 1100,
    })
    assert r.status_code == 200

    with sesion() as s:
        sede = s.get(Sede, sede_id)
        assert sede.precio_valoracion == 1100
        assert "Pablo Neruda" in sede.direccion


def test_las_franjas_se_guardan_como_json(doctor, sede_id):
    r = doctor.put(f"/panel/api/sedes/{sede_id}", json={
        "franjas_json": [{"dia": 1, "desde": "10:00", "hasta": "12:00"}]
    })
    assert r.status_code == 200

    with sesion() as s:
        guardado = json.loads(s.get(Sede, sede_id).franjas_json)
    assert guardado == [{"dia": 1, "desde": "10:00", "hasta": "12:00"}]


def test_la_asistente_no_edita_las_sedes(asistente, sede_id):
    assert asistente.put(
        f"/panel/api/sedes/{sede_id}", json={"precio_valoracion": 1}
    ).status_code == 403


def test_no_se_pueden_cambiar_campos_ajenos(doctor, sede_id):
    """Solo se aceptan los campos declarados editables."""
    doctor.put(f"/panel/api/sedes/{sede_id}", json={"id": 9999, "doctoralia_recurso_id": "x"})
    with sesion() as s:
        sede = s.get(Sede, sede_id)
        assert sede.id == sede_id
        assert sede.doctoralia_recurso_id != "x"


def test_la_sede_marca_si_le_faltan_datos(doctor):
    sedes = doctor.get("/panel/api/sedes").json()
    assert sedes
    for s in sedes:
        assert "completa" in s
        assert isinstance(s["horario"], list)
        assert isinstance(s["franjas"], list)


# ----------------------------------------------------------------------
#  Respuestas frecuentes
# ----------------------------------------------------------------------

def test_ciclo_completo_de_una_respuesta(doctor):
    creada = doctor.post("/panel/api/respuestas", json={
        "intencion": "informacion",
        "respuesta": "Traiga identificación oficial y sus estudios previos.",
        "disparadores": "documentos,llevar",
    })
    assert creada.status_code == 200
    rid = creada.json()["id"]

    assert doctor.put(f"/panel/api/respuestas/{rid}", json={
        "respuesta": "Traiga una identificación y sus estudios."
    }).status_code == 200

    listado = doctor.get("/panel/api/respuestas").json()
    assert any(r["id"] == rid and "identificación y" in r["respuesta"] for r in listado)

    assert doctor.delete(f"/panel/api/respuestas/{rid}").status_code == 200
    assert all(r["id"] != rid for r in doctor.get("/panel/api/respuestas").json())


def test_no_se_guarda_una_respuesta_vacia(doctor):
    assert doctor.post("/panel/api/respuestas", json={
        "intencion": "informacion", "respuesta": "   "
    }).status_code == 400


def test_la_asistente_no_borra_respuestas(asistente, doctor):
    rid = doctor.post("/panel/api/respuestas", json={
        "intencion": "informacion", "respuesta": "Una respuesta cualquiera."
    }).json()["id"]

    assert asistente.delete(f"/panel/api/respuestas/{rid}").status_code == 403
    doctor.delete(f"/panel/api/respuestas/{rid}")


# ----------------------------------------------------------------------
#  Contraseña
# ----------------------------------------------------------------------

def test_no_se_cambia_la_clave_sin_saber_la_actual(doctor):
    assert doctor.post("/panel/api/cambiar-clave", json={
        "actual": "no-es-la-mia", "nueva": "una-clave-larga-nueva"
    }).status_code == 401


def test_la_clave_nueva_no_puede_ser_corta(doctor):
    r = doctor.post("/panel/api/cambiar-clave", json={
        "actual": CLAVE_DOCTOR, "nueva": "corta"
    })
    assert r.status_code == 400
    assert "10 caracteres" in r.json()["detail"]


def test_la_clave_nueva_no_puede_ser_la_misma(doctor):
    assert doctor.post("/panel/api/cambiar-clave", json={
        "actual": CLAVE_DOCTOR, "nueva": CLAVE_DOCTOR
    }).status_code == 400


def test_se_cambia_la_clave_y_la_nueva_funciona():
    inicial = "clave-inicial-para-cambiar-77"
    final = "clave-definitiva-del-doctor-88"

    with sesion() as s:
        u = Usuario(nombre="Prueba Clave", correo="clave@prueba.local",
                    hash_clave=cifrar_clave(inicial), rol=RolUsuario.ASISTENTE)
        s.add(u)
        s.commit()

    with TestClient(aplicacion) as c:
        assert c.post("/panel/api/login", json={
            "correo": "clave@prueba.local", "clave": inicial}).status_code == 200
        assert c.post("/panel/api/cambiar-clave", json={
            "actual": inicial, "nueva": final}).status_code == 200

    with TestClient(aplicacion) as c:
        assert c.post("/panel/api/login", json={
            "correo": "clave@prueba.local", "clave": inicial}).status_code == 401
        assert c.post("/panel/api/login", json={
            "correo": "clave@prueba.local", "clave": final}).status_code == 200


# ----------------------------------------------------------------------
#  Agenda
# ----------------------------------------------------------------------

def test_el_listado_de_citas_responde(doctor):
    r = doctor.get("/panel/api/citas")
    assert r.status_code == 200
    for c in r.json():
        for clave in ("paciente", "telefono", "cuando", "sede", "estado", "cargada"):
            assert clave in c


def test_la_lista_de_por_cargar_responde(doctor):
    r = doctor.get("/panel/api/por-cargar")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_sin_sesion_no_se_ve_el_contenido():
    with TestClient(aplicacion) as c:
        for ruta in ("/panel/api/sedes", "/panel/api/respuestas",
                     "/panel/api/citas", "/panel/api/por-cargar"):
            assert c.get(ruta).status_code == 401


def test_se_puede_renombrar_una_sede(doctor):
    """
    Los nombres que crea el `seed` son inventados. El consultorio tiene que
    poder poner los suyos sin pedirle nada al desarrollador.
    """
    with sesion() as s:
        sede = s.exec(select(Sede)).first()
        sede_id, original = sede.id, sede.nombre

    r = doctor.put(f"/panel/api/sedes/{sede_id}", json={"nombre": "Consultorio Centro"})
    assert r.status_code == 200
    assert "nombre" in r.json()["cambios"]

    with sesion() as s:
        assert s.get(Sede, sede_id).nombre == "Consultorio Centro"
        s.get(Sede, sede_id).nombre = original
        s.commit()
