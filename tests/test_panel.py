"""
Pruebas del panel.

Lo que más importa acá es el control de acceso: sin sesión no se ve nada,
una asistente no puede tocar la configuración, y todo lo que modifica algo
queda en el registro de auditoría.
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.db import sesion
from app.main import aplicacion
from app.models import (
    Conversacion,
    EstadoConversacion,
    Paciente,
    RegistroAuditoria,
    RolUsuario,
    Sede,
    Usuario,
)
from app.security import cifrar_clave

CLAVE_DOCTOR = "clave-del-doctor-9182"
CLAVE_ASISTENTE = "clave-de-la-asistente-7261"


@pytest.fixture(scope="module", autouse=True)
def usuarios_de_prueba():
    with sesion() as s:
        if not s.exec(select(Usuario).where(Usuario.correo == "doctor@prueba.local")).first():
            s.add(Usuario(
                nombre="José Guadalupe Padilla",
                correo="doctor@prueba.local",
                hash_clave=cifrar_clave(CLAVE_DOCTOR),
                rol=RolUsuario.ADMIN,
            ))
            s.add(Usuario(
                nombre="Lucía Márquez",
                correo="asistente@prueba.local",
                hash_clave=cifrar_clave(CLAVE_ASISTENTE),
                rol=RolUsuario.ASISTENTE,
            ))
            s.commit()


@pytest.fixture
def cliente():
    with TestClient(aplicacion) as c:
        yield c


def entrar(cliente, correo: str, clave: str):
    return cliente.post("/panel/api/login", json={"correo": correo, "clave": clave})


@pytest.fixture
def doctor(cliente):
    assert entrar(cliente, "doctor@prueba.local", CLAVE_DOCTOR).status_code == 200
    return cliente


@pytest.fixture
def asistente(cliente):
    assert entrar(cliente, "asistente@prueba.local", CLAVE_ASISTENTE).status_code == 200
    return cliente


# ----------------------------------------------------------------------
#  Acceso
# ----------------------------------------------------------------------

@pytest.mark.parametrize("ruta", [
    "/panel/api/yo",
    "/panel/api/resumen",
    "/panel/api/conversaciones",
    "/panel/api/pacientes",
    "/panel/api/config",
])
def test_sin_sesion_no_se_ve_nada(cliente, ruta):
    assert cliente.get(ruta).status_code == 401


def test_clave_incorrecta_no_entra(cliente):
    r = entrar(cliente, "doctor@prueba.local", "no-es-la-clave")
    assert r.status_code == 401
    assert "incorrect" in r.json()["detail"].lower()


def test_correo_inexistente_no_entra(cliente):
    assert entrar(cliente, "nadie@prueba.local", "loquesea").status_code == 401


def test_la_cookie_de_sesion_no_es_accesible_por_javascript(cliente):
    r = entrar(cliente, "doctor@prueba.local", CLAVE_DOCTOR)
    cabecera = r.headers.get("set-cookie", "").lower()
    assert "httponly" in cabecera


def test_entrar_devuelve_el_rol(doctor):
    d = doctor.get("/panel/api/yo").json()
    assert d["rol"] == "admin"
    assert d["iniciales"] == "JG"


def test_cerrar_sesion_invalida_el_acceso(doctor):
    assert doctor.post("/panel/api/logout").status_code == 200
    assert doctor.get("/panel/api/yo").status_code == 401


# ----------------------------------------------------------------------
#  Permisos por rol
# ----------------------------------------------------------------------

def test_la_asistente_no_cambia_el_modo(asistente):
    r = asistente.put("/panel/api/modo", json={"modo": "ia"})
    assert r.status_code == 403


def test_la_asistente_no_activa_ni_desactiva_sedes(asistente):
    with sesion() as s:
        sede = s.exec(select(Sede)).first()
    r = asistente.patch(f"/panel/api/sedes/{sede.id}", json={"activa": False})
    assert r.status_code == 403


def test_la_asistente_no_ve_la_auditoria(asistente):
    assert asistente.get("/panel/api/auditoria").status_code == 403


def test_el_doctor_si_cambia_el_modo(doctor):
    assert doctor.put("/panel/api/modo", json={"modo": "basico"}).json()["modo"] == "basico"
    assert doctor.get("/panel/api/config").json()["modo"] == "basico"


def test_modo_desconocido_se_rechaza(doctor):
    assert doctor.put("/panel/api/modo", json={"modo": "turbo"}).status_code == 400


# ----------------------------------------------------------------------
#  Información de contacto
# ----------------------------------------------------------------------

def test_la_lista_de_pacientes_trae_el_contacto(doctor):
    with sesion() as s:
        s.add(Paciente(
            telefono="5213311112222",
            nombre="Ana López",
            ciudad="Zapopan",
            fuente="google",
        ))
        s.commit()

    lista = doctor.get("/panel/api/pacientes").json()
    ana = next((p for p in lista if p["telefono"] == "5213311112222"), None)
    assert ana is not None
    assert ana["nombre"] == "Ana López"
    assert ana["ciudad"] == "Zapopan"
    assert ana["fuente"] == "google"
    assert ana["whatsapp_url"] == "https://wa.me/5213311112222"


def test_se_puede_buscar_por_telefono(doctor):
    with sesion() as s:
        s.add(Paciente(telefono="5213399998888", nombre="Roberto Méndez"))
        s.commit()

    lista = doctor.get("/panel/api/pacientes?buscar=99998888").json()
    assert len(lista) == 1
    assert lista[0]["nombre"] == "Roberto Méndez"


def test_la_ficha_de_la_conversacion_trae_el_contacto(doctor):
    with sesion() as s:
        p = Paciente(telefono="5213344445555", nombre="Teresa Ruiz", ciudad="Guadalajara")
        s.add(p)
        s.commit()
        s.refresh(p)
        c = Conversacion(paciente_id=p.id)
        s.add(c)
        s.commit()
        s.refresh(c)
        conv_id = c.id

    d = doctor.get(f"/panel/api/conversaciones/{conv_id}").json()
    assert d["paciente"]["nombre"] == "Teresa Ruiz"
    assert d["paciente"]["telefono"] == "5213344445555"
    assert d["paciente"]["ciudad"] == "Guadalajara"
    assert d["paciente"]["whatsapp_url"].endswith("5213344445555")


def test_conversacion_inexistente_da_404(doctor):
    assert doctor.get("/panel/api/conversaciones/999999").status_code == 404


# ----------------------------------------------------------------------
#  Toma de control
# ----------------------------------------------------------------------

@pytest.fixture
def conversacion_id():
    import uuid

    with sesion() as s:
        # Teléfono distinto por prueba: la columna es única y el fixture
        # corre una vez por cada una.
        p = Paciente(telefono="52133" + uuid.uuid4().hex[:8], nombre="Jorge Aguilar")
        s.add(p)
        s.commit()
        s.refresh(p)
        c = Conversacion(paciente_id=p.id, estado=EstadoConversacion.REQUIERE_ATENCION)
        s.add(c)
        s.commit()
        s.refresh(c)
        return c.id


def test_tomar_y_devolver_el_control(doctor, conversacion_id):
    assert doctor.post(f"/panel/api/conversaciones/{conversacion_id}/tomar").json()["estado"] == "humano"

    with sesion() as s:
        c = s.get(Conversacion, conversacion_id)
        assert c.estado is EstadoConversacion.HUMANO
        assert c.tomada_por_id is not None
        assert c.tomada_en is not None

    assert doctor.post(f"/panel/api/conversaciones/{conversacion_id}/devolver").json()["estado"] == "bot"

    with sesion() as s:
        c = s.get(Conversacion, conversacion_id)
        assert c.estado is EstadoConversacion.BOT
        assert c.tomada_por_id is None
        assert c.motivo_escalado is None


def test_responder_toma_el_control_automaticamente(doctor, conversacion_id):
    r = doctor.post(
        f"/panel/api/conversaciones/{conversacion_id}/mensajes",
        json={"texto": "Buenos días, en un momento la atendemos."},
    )
    assert r.status_code == 200

    with sesion() as s:
        c = s.get(Conversacion, conversacion_id)
        assert c.estado is EstadoConversacion.HUMANO


def test_no_se_envian_mensajes_vacios(doctor, conversacion_id):
    r = doctor.post(
        f"/panel/api/conversaciones/{conversacion_id}/mensajes",
        json={"texto": "   "},
    )
    assert r.status_code == 400


def test_el_mensaje_enviado_queda_atribuido_a_quien_lo_escribio(doctor, conversacion_id):
    doctor.post(
        f"/panel/api/conversaciones/{conversacion_id}/mensajes",
        json={"texto": "Le confirmo su cita del jueves."},
    )
    d = doctor.get(f"/panel/api/conversaciones/{conversacion_id}").json()
    humanos = [m for m in d["mensajes"] if m["quien"] == "humano"]
    assert humanos and humanos[-1]["texto"] == "Le confirmo su cita del jueves."


# ----------------------------------------------------------------------
#  Auditoría
# ----------------------------------------------------------------------

def test_tomar_el_control_queda_auditado(doctor, conversacion_id):
    doctor.post(f"/panel/api/conversaciones/{conversacion_id}/tomar")

    with sesion() as s:
        registro = s.exec(
            select(RegistroAuditoria)
            .where(
                RegistroAuditoria.accion == "conversacion.tomada",
                RegistroAuditoria.entidad_id == conversacion_id,
            )
        ).first()
    assert registro is not None
    assert registro.actor == "doctor@prueba.local"


def test_desactivar_una_sede_queda_auditado(doctor):
    with sesion() as s:
        sede = s.exec(select(Sede).where(Sede.activa)).first()
        sede_id, nombre = sede.id, sede.nombre

    doctor.patch(f"/panel/api/sedes/{sede_id}", json={"activa": False})

    with sesion() as s:
        registro = s.exec(
            select(RegistroAuditoria)
            .where(RegistroAuditoria.accion == "sede.cambiada")
            .order_by(RegistroAuditoria.id.desc())  # type: ignore[attr-defined]
        ).first()
        assert registro and nombre in registro.detalle and "inactiva" in registro.detalle
        # se deja como estaba
        s.get(Sede, sede_id).activa = True
        s.commit()

    doctor.patch(f"/panel/api/sedes/{sede_id}", json={"activa": True})


# ----------------------------------------------------------------------
#  Resumen y páginas
# ----------------------------------------------------------------------

def test_el_resumen_responde_con_las_metricas(doctor):
    d = doctor.get("/panel/api/resumen").json()
    for clave in ("requieren_atencion", "conversaciones_hoy", "citas_hoy",
                  "conversion", "respuesta_promedio_s", "urgencias",
                  "serie", "fuentes", "proximas_citas"):
        assert clave in d
    assert len(d["serie"]) == 7


def test_la_config_no_expone_secretos(doctor):
    crudo = doctor.get("/panel/api/config").text.lower()
    for secreto in ("api_key", "token", "secreto", "hash_clave", "sk-"):
        assert secreto not in crudo


def test_el_panel_se_sirve_en_cualquier_ruta_suya(cliente):
    """Un aviso enlaza a /panel/conversaciones/12 y debe abrir, no dar 404."""
    for ruta in ("/panel", "/panel/conversaciones/12", "/panel/pacientes"):
        r = cliente.get(ruta)
        assert r.status_code == 200
        assert "Consultorio Dr. Padilla" in r.text


def test_la_raiz_lleva_al_panel(cliente):
    r = cliente.get("/", follow_redirects=False)
    assert r.status_code in (307, 302)
    assert r.headers["location"] == "/panel"
