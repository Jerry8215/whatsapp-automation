"""
Plan C — Google Calendar.

Es el camino que queda listo y en pausa: Doctoralia no admite ninguna
conexión, y el día que el consultorio decida mudar la agenda, este proveedor
hace lo que las franjas no pueden — ver la disponibilidad real y escribir la
cita él mismo.

Lo que se verifica acá:

  * que no se ofrezca un horario que en Google está ocupado;
  * que la cita se re-verifique en el instante de confirmar, no al ofrecer;
  * que en el evento de Google **no viaje nada clínico**;
  * que cambiar de origen sea un interruptor y no una reescritura;
  * y que, con Google activo, no quede ninguna cita «por cargar a mano».

No se llama a Google de verdad en ningún momento: se sustituye la capa HTTP.
"""

import json
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from app.agenda import google_calendar as gcal
from app.agenda.base import CupoYaOcupado
from app.db import sesion
from app.models import Ajuste, Sede

CREDENCIALES = json.dumps({
    "type": "service_account",
    "client_email": "asistente@consultorio.iam.gserviceaccount.com",
    "private_key": "-----BEGIN PRIVATE KEY-----\nfalsa\n-----END PRIVATE KEY-----\n",
})


@pytest.fixture
def google(monkeypatch):
    """Credenciales de mentira y la capa HTTP sustituida."""
    from app.config import config

    monkeypatch.setattr(config, "google_cuenta_servicio_json", CREDENCIALES, raising=False)
    monkeypatch.setattr(config, "google_calendario_id", "consultorio@gmail.com", raising=False)
    gcal.olvidar_token()

    async def token_falso():
        return "token-de-prueba"

    monkeypatch.setattr(gcal, "token_de_acceso", token_falso)
    return config


@pytest.fixture
def llamadas(monkeypatch):
    """Registra lo que se le habría pedido a Google y devuelve lo indicado."""
    registro = {"lista": [], "ocupado": [], "respuesta": {}}

    async def llamar_falso(metodo, ruta, **kwargs):
        registro["lista"].append({"metodo": metodo, "ruta": ruta, **kwargs})
        if ruta == "/freeBusy":
            calendario = kwargs["json"]["items"][0]["id"]
            return {"calendars": {calendario: {"busy": registro["ocupado"]}}}
        return registro["respuesta"]

    monkeypatch.setattr(gcal, "_llamar", llamar_falso)
    return registro


def _sede_principal() -> Sede:
    with sesion() as s:
        return s.exec(select(Sede).where(Sede.activa).order_by(Sede.orden)).first()  # type: ignore[arg-type]


def _proximo_lunes_a_las_diez() -> datetime:
    """
    Un lunes futuro a las 10:00 locales, en UTC.

    La sede de las pruebas atiende lunes, miércoles y viernes de 9 a 14.
    """
    from app.tiempo import a_local, combinar_local

    from datetime import time

    hoy = a_local(datetime.utcnow()).date()
    dia = hoy + timedelta(days=1)
    while dia.weekday() != 0 or (dia - hoy).days < 3:
        dia += timedelta(days=1)
    return combinar_local(dia, time(10, 0))


# ----------------------------------------------------------------------
#  Credenciales
# ----------------------------------------------------------------------

def test_sin_credenciales_lo_dice_claro(monkeypatch):
    from app.config import config

    monkeypatch.setattr(config, "google_cuenta_servicio_json", "", raising=False)
    with pytest.raises(gcal.ErrorGoogle, match="GOOGLE_CUENTA_SERVICIO_JSON"):
        gcal.credenciales()


def test_credenciales_incompletas_se_detectan_al_arrancar(monkeypatch):
    """
    Un JSON al que le falta la clave privada falla igual, pero mucho más
    tarde y con un error de Google indescifrable. Mejor acá.
    """
    from app.config import config

    monkeypatch.setattr(
        config, "google_cuenta_servicio_json",
        json.dumps({"client_email": "x@y.z"}), raising=False,
    )
    with pytest.raises(gcal.ErrorGoogle, match="private_key"):
        gcal.credenciales()


def test_las_credenciales_pueden_venir_de_un_archivo(monkeypatch, tmp_path):
    """En el servidor se pega el JSON; en una máquina local es un archivo."""
    from app.config import config

    archivo = tmp_path / "cuenta.json"
    archivo.write_text(CREDENCIALES, encoding="utf-8")
    monkeypatch.setattr(config, "google_cuenta_servicio_json", str(archivo), raising=False)

    assert gcal.credenciales()["client_email"].endswith("gserviceaccount.com")


def test_el_correo_de_servicio_es_lo_que_hay_que_compartir(google):
    assert gcal.correo_de_servicio() == "asistente@consultorio.iam.gserviceaccount.com"


# ----------------------------------------------------------------------
#  Disponibilidad
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ofrece_el_horario_completo_de_atencion(google, llamadas):
    """
    La ganancia de mudarse: con Google el asistente ya no está limitado a
    las franjas que le reservaron, ve toda la agenda.
    """
    sede = _sede_principal()
    lunes = _proximo_lunes_a_las_diez()

    huecos = await gcal.AgendaGoogle().huecos(
        sede.id, lunes - timedelta(hours=2), lunes + timedelta(hours=3)
    )

    assert huecos
    assert any(h.inicio == lunes for h in huecos)


@pytest.mark.asyncio
async def test_no_ofrece_un_horario_que_google_marca_ocupado(google, llamadas):
    sede = _sede_principal()
    lunes = _proximo_lunes_a_las_diez()

    llamadas["ocupado"] = [{
        "start": lunes.replace(microsecond=0).isoformat() + "Z",
        "end": (lunes + timedelta(minutes=30)).replace(microsecond=0).isoformat() + "Z",
    }]

    huecos = await gcal.AgendaGoogle().huecos(
        sede.id, lunes - timedelta(hours=2), lunes + timedelta(hours=3)
    )

    assert not any(h.inicio == lunes for h in huecos)
    assert huecos, "el resto del día debe seguir disponible"


@pytest.mark.asyncio
async def test_se_pregunta_por_lo_ocupado_sin_pedir_el_detalle(google, llamadas):
    """
    Se usa `freeBusy` y no el listado de eventos: devuelve los rangos
    ocupados y nada más. No hay ninguna razón para que este sistema vea de
    qué es cada cita del doctor.
    """
    sede = _sede_principal()
    lunes = _proximo_lunes_a_las_diez()

    await gcal.AgendaGoogle().huecos(sede.id, lunes, lunes + timedelta(hours=2))

    rutas = [c["ruta"] for c in llamadas["lista"]]
    assert "/freeBusy" in rutas
    assert not any("/events" in r for r in rutas)


# ----------------------------------------------------------------------
#  Reservar
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reservar_escribe_el_evento_en_google(google, llamadas):
    sede = _sede_principal()
    lunes = _proximo_lunes_a_las_diez()
    llamadas["respuesta"] = {"id": "evento-123"}

    resultado = await gcal.AgendaGoogle().reservar(
        sede_id=sede.id,
        inicio=lunes,
        fin=lunes + timedelta(minutes=30),
        nombre_paciente="Ana López",
        telefono="5213330001111",
        motivo="valoracion",
    )

    assert resultado.ok
    assert resultado.externo_id == "evento-123"
    # No queda nada pendiente para una persona: es la diferencia con franjas.
    assert resultado.requiere_confirmacion_humana is False

    creacion = [c for c in llamadas["lista"] if c["metodo"] == "POST" and "/events" in c["ruta"]]
    assert len(creacion) == 1
    assert creacion[0]["json"]["extendedProperties"]["private"]["origen"] == "asistente-whatsapp"


@pytest.mark.asyncio
async def test_en_el_evento_de_google_no_viaja_nada_clinico(google, llamadas):
    """
    Google Calendar es un servicio de terceros y el evento puede verlo
    cualquiera con quien se comparta la agenda. Va lo administrativo y nada
    más: es la misma regla que rige el resto del sistema.
    """
    sede = _sede_principal()
    lunes = _proximo_lunes_a_las_diez()
    llamadas["respuesta"] = {"id": "evento-456"}

    await gcal.AgendaGoogle().reservar(
        sede_id=sede.id, inicio=lunes, fin=lunes + timedelta(minutes=30),
        nombre_paciente="Ana López", telefono="5213330001111", motivo="valoracion",
    )

    evento = [c for c in llamadas["lista"] if "/events" in c["ruta"]][0]["json"]
    texto = json.dumps(evento, ensure_ascii=False).lower()

    for palabra in ("dolor", "diagnostico", "sintoma", "vesicula", "estudio", "foto"):
        assert palabra not in texto


@pytest.mark.asyncio
async def test_si_el_hueco_se_ocupo_mientras_elegia_no_se_pisa(google, llamadas):
    """
    Se re-verifica al confirmar, no al ofrecer. Quien llama atrapa esto y le
    ofrece alternativas al paciente; nunca un error.
    """
    sede = _sede_principal()
    lunes = _proximo_lunes_a_las_diez()

    llamadas["ocupado"] = [{
        "start": lunes.replace(microsecond=0).isoformat() + "Z",
        "end": (lunes + timedelta(minutes=30)).replace(microsecond=0).isoformat() + "Z",
    }]

    with pytest.raises(CupoYaOcupado):
        await gcal.AgendaGoogle().reservar(
            sede_id=sede.id, inicio=lunes, fin=lunes + timedelta(minutes=30),
            nombre_paciente="Ana López", telefono="5213330001111",
        )

    assert not any("/events" in c["ruta"] for c in llamadas["lista"])


@pytest.mark.asyncio
async def test_cancelar_borra_el_evento(google, llamadas):
    assert await gcal.AgendaGoogle().cancelar("evento-789") is True
    borrado = [c for c in llamadas["lista"] if c["metodo"] == "DELETE"]
    assert borrado and "evento-789" in borrado[0]["ruta"]


@pytest.mark.asyncio
async def test_cancelar_sin_evento_no_es_un_error(google, llamadas):
    """Una cita sin evento en Google ya no ocupa lugar: el objetivo se cumplió."""
    assert await gcal.AgendaGoogle().cancelar("") is True
    assert llamadas["lista"] == []


@pytest.mark.asyncio
async def test_reprogramar_mueve_el_evento(google, llamadas):
    lunes = _proximo_lunes_a_las_diez()
    llamadas["respuesta"] = {"id": "evento-789"}

    r = await gcal.AgendaGoogle().reprogramar(
        "evento-789", lunes + timedelta(hours=1), lunes + timedelta(hours=1, minutes=30)
    )

    assert r.ok
    parche = [c for c in llamadas["lista"] if c["metodo"] == "PATCH"]
    assert parche and "start" in parche[0]["json"]


# ----------------------------------------------------------------------
#  Qué agenda usa cada sede
# ----------------------------------------------------------------------

def test_una_sede_sin_agenda_propia_usa_la_general(google):
    """Lo normal: un solo doctor, una sola agenda para las tres sedes."""
    sede = _sede_principal()
    assert gcal.calendario_de(sede) == "consultorio@gmail.com"


def test_una_sede_puede_tener_su_propia_agenda(google):
    sede = Sede(nombre="X", direccion="Y", calendario_google_id="norte@gmail.com")
    assert gcal.calendario_de(sede) == "norte@gmail.com"


# ----------------------------------------------------------------------
#  El interruptor
# ----------------------------------------------------------------------

@pytest.fixture(autouse=True)
def volver_a_franjas():
    yield
    from app.agenda.service import reiniciar_proveedor

    with sesion() as s:
        ajuste = s.get(Ajuste, "agenda_origen")
        if ajuste:
            s.delete(ajuste)
            s.commit()
    reiniciar_proveedor()


def test_por_defecto_la_agenda_sigue_siendo_la_de_hoy():
    """
    Google queda construido y en pausa. Nadie muda la agenda del consultorio
    por desplegar una versión nueva.
    """
    from app.agenda.franjas import FranjasReservadas
    from app.agenda.service import origen, proveedor

    assert origen() == "franjas"
    assert isinstance(proveedor(), FranjasReservadas)
    assert proveedor().escribe_en_la_agenda is False


def test_cambiar_el_origen_cambia_el_proveedor_sin_reiniciar_nada():
    from app.agenda.service import proveedor, reiniciar_proveedor

    with sesion() as s:
        s.add(Ajuste(clave="agenda_origen", valor="google"))
        s.commit()
    reiniciar_proveedor()

    assert isinstance(proveedor(), gcal.AgendaGoogle)
    assert proveedor().escribe_en_la_agenda is True


@pytest.mark.asyncio
async def test_con_google_no_queda_nada_por_cargar_a_mano(google, llamadas):
    """
    La lista de «por cargar en Doctoralia» existe porque las franjas no
    pueden escribir. Con Google la cita ya está escrita: si siguiera
    apareciendo ahí, la asistente la cargaría dos veces.
    """
    from app.agenda.franjas import citas_por_cargar
    from app.agenda.service import agendar, reiniciar_proveedor
    from app.models import Paciente

    with sesion() as s:
        s.add(Ajuste(clave="agenda_origen", valor="google"))
        paciente = Paciente(telefono="521999000111", nombre="Ana López")
        s.add(paciente)
        s.commit()
        s.refresh(paciente)
        paciente_id = paciente.id
    reiniciar_proveedor()

    sede = _sede_principal()
    lunes = _proximo_lunes_a_las_diez()
    llamadas["respuesta"] = {"id": "evento-agendado"}

    cita = await agendar(paciente_id=paciente_id, sede_id=sede.id, inicio=lunes)

    assert cita.externo_id == "evento-agendado"
    assert cita.cargada_en_doctoralia is True
    assert cita.id not in [c.id for c in citas_por_cargar()]


# ----------------------------------------------------------------------
#  Diagnóstico
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_la_prueba_de_conexion_avisa_si_faltan_credenciales(monkeypatch):
    from app.config import config

    monkeypatch.setattr(config, "google_cuenta_servicio_json", "", raising=False)
    r = await gcal.probar_conexion()

    assert r["ok"] is False
    assert "credenciales" in r["detalle"].lower()


@pytest.mark.asyncio
async def test_la_prueba_de_conexion_revisa_cada_sede(google, llamadas):
    r = await gcal.probar_conexion()

    assert r["ok"] is True
    assert r["correo_servicio"].endswith("gserviceaccount.com")
    assert r["agendas"] and all(a["ok"] for a in r["agendas"])
