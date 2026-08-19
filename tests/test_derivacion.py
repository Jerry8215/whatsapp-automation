"""
Derivación a otro profesional.

El caso: la asistente lleva la agenda del doctor y la de su esposa desde el
mismo número. Al separarlas, los pacientes que ya tienen este número
guardado van a seguir escribiendo acá para pedirle cita a ella.

Los dos errores que estas pruebas existen para impedir:

  * **Agendar con el médico equivocado.** «Quiero cita con la doctora»
    clasifica como CITA; sin la derivación, el asistente empezaría a
    ofrecerle horarios del Dr. Padilla y el paciente se enteraría el día de
    la consulta.
  * **Desviar a quien no había que desviar.** Mencionar a la doctora al
    pasar no es pedirle cita. Un paciente mandado a otro número por error es
    un paciente perdido.
"""

import pytest
from sqlmodel import select

from app.brain import derivacion
from app.db import sesion
from app.models import Profesional


@pytest.fixture
def doctora():
    with sesion() as s:
        p = Profesional(
            nombre="Ana Ramírez",
            titulo="Dra.",
            especialidad="Nutrición",
            deriva=True,
            telefono_whatsapp="+523310002000",
            palabras_clave="doctora, su esposa, nutriologa",
            activo=True,
            orden=2,
        )
        s.add(p)
        s.commit()
        s.refresh(p)
        creada = p.id
    yield creada
    with sesion() as s:
        fila = s.get(Profesional, creada)
        if fila:
            s.delete(fila)
            s.commit()


@pytest.fixture(autouse=True)
def sin_profesionales_colgados():
    yield
    with sesion() as s:
        for p in s.exec(select(Profesional).where(Profesional.deriva)).all():  # type: ignore[arg-type]
            s.delete(p)
        s.commit()


# ----------------------------------------------------------------------
#  Reconocimiento
# ----------------------------------------------------------------------

def test_sin_nadie_cargado_no_deriva_nunca():
    """El caso normal del consultorio hoy: un solo profesional."""
    assert derivacion.detectar("quiero cita con la doctora") is None


@pytest.mark.parametrize("mensaje", [
    "quiero una cita con la doctora",
    "Buenas, ¿la doctora tiene espacio esta semana?",
    "me pasa el numero de la dra Ramirez?",
    "cuanto cobra la consulta con su esposa?",
    "¿a qué hora atiende la nutriologa?",
    "quisiera agendar con Ramirez",
])
def test_reconoce_que_buscan_a_la_otra_profesional(doctora, mensaje):
    d = derivacion.detectar(mensaje)
    assert d is not None, mensaje
    assert d.telefono == "+523310002000"
    assert "Ana Ramírez" in d.nombre


def test_el_apellido_se_reconoce_aunque_no_este_como_palabra_clave():
    with sesion() as s:
        s.add(Profesional(
            nombre="Beatriz Solano", titulo="Dra.", deriva=True,
            telefono_whatsapp="+523311112222", palabras_clave="", activo=True,
        ))
        s.commit()

    assert derivacion.detectar("quiero cita con Solano") is not None


@pytest.mark.parametrize("mensaje", [
    "la doctora me recomendó operarme",
    "mi esposa me acompaña a la consulta",
])
def test_mencionarla_al_pasar_no_desvia_al_paciente(doctora, mensaje):
    """
    Estos mensajes son para el Dr. Padilla. Mandarlos a otro número sería
    perder al paciente por una coincidencia de palabras.
    """
    assert derivacion.detectar(mensaje) is None


def test_una_clave_corta_no_coincide_dentro_de_otra_palabra():
    """
    Sin comparar por palabra completa, la clave «ana» coincidiría dentro de
    «mañana» y media agenda terminaría derivada.
    """
    with sesion() as s:
        s.add(Profesional(
            nombre="Ana Ruiz", titulo="Dra.", deriva=True,
            telefono_whatsapp="+523313334444", palabras_clave="ana", activo=True,
        ))
        s.commit()

    assert derivacion.detectar("quiero una cita para mañana") is None
    assert derivacion.detectar("quiero cita con Ana") is not None


def test_un_profesional_desactivado_no_deriva(doctora):
    with sesion() as s:
        p = s.get(Profesional, doctora)
        p.activo = False
        s.add(p)
        s.commit()

    assert derivacion.detectar("quiero cita con la doctora") is None


def test_el_principal_nunca_deriva():
    """
    Derivar al titular del número sería contestarle a un paciente que ya
    escribió al número correcto que se vaya a ese mismo número.
    """
    with sesion() as s:
        s.add(Profesional(
            nombre="José Guadalupe Padilla", titulo="Dr.",
            principal=True, deriva=False, activo=True,
        ))
        s.commit()

    assert derivacion.detectar("quiero cita con Padilla") is None


def test_la_intencion_de_cita_alcanza_como_contexto(doctora):
    """
    «La doctora» a secas, cuando la clasificación ya dijo que es una cita.
    """
    assert derivacion.detectar("la doctora", intencion_de_cita=True) is not None
    assert derivacion.detectar("la doctora", intencion_de_cita=False) is None


# ----------------------------------------------------------------------
#  El mensaje
# ----------------------------------------------------------------------

def test_el_mensaje_dice_el_numero_y_de_quien_es_este(doctora):
    d = derivacion.detectar("quiero cita con la doctora")
    assert "+523310002000" in d.texto
    assert "Padilla" in d.texto        # con quién está hablando
    assert "Ana Ramírez" in d.texto    # a quién buscaba
    assert not derivacion.configuracion_incompleta(d)


def test_sin_numero_cargado_no_se_inventa_nada():
    """
    Media configuración es peor que ninguna: se reconoce a quién busca pero
    no hay número que darle, así que tiene que atenderlo una persona.
    """
    with sesion() as s:
        s.add(Profesional(
            nombre="Ana Ramírez", titulo="Dra.", deriva=True,
            telefono_whatsapp="", palabras_clave="doctora", activo=True,
        ))
        s.commit()

    d = derivacion.detectar("quiero cita con la doctora")
    assert derivacion.configuracion_incompleta(d)
    assert "otra vía" in d.texto
    assert "📱" not in d.texto


def test_se_puede_escribir_un_mensaje_propio():
    with sesion() as s:
        s.add(Profesional(
            nombre="Ana Ramírez", titulo="Dra.", deriva=True,
            telefono_whatsapp="+523310002000", palabras_clave="doctora",
            mensaje_derivacion="La Dra. Ramírez atiende al 33 1000 2000.",
            activo=True,
        ))
        s.commit()

    assert derivacion.detectar("cita con la doctora").texto == (
        "La Dra. Ramírez atiende al 33 1000 2000."
    )


# ----------------------------------------------------------------------
#  En el circuito completo
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_el_asistente_pasa_el_numero_y_no_agenda(doctora, telefono, monkeypatch):
    """
    La prueba que de verdad importa: el mensaje entra por el circuito
    completo y sale con el número correcto, sin haber empezado a agendar.
    """
    from app.brain import router
    from app.models import Cita, Conversacion, Paciente
    from app.whatsapp.parser import MensajeEntrante

    enviados = []

    async def enviar_falso(destino, texto, *a, **k):
        enviados.append(texto)

    monkeypatch.setattr("app.whatsapp.client.enviar_texto", enviar_falso)

    await router.procesar_mensaje(MensajeEntrante(
        telefono=telefono,
        texto="Hola, quiero agendar una cita con la doctora",
        wa_message_id="wamid.derivacion.1",
        nombre_perfil="Paciente Prueba",
    ))

    assert any("+523310002000" in t for t in enviados), enviados

    with sesion() as s:
        paciente = s.exec(select(Paciente).where(Paciente.telefono == telefono)).first()
        conversacion = s.exec(
            select(Conversacion).where(Conversacion.paciente_id == paciente.id)
        ).first()
        citas = s.exec(select(Cita).where(Cita.paciente_id == paciente.id)).all()

    # Ni cita creada, ni agendamiento a medias esperando una respuesta que
    # el paciente ya no va a dar.
    assert citas == []
    assert conversacion.paso == ""
    assert conversacion.motivo_perdida == "Buscaba a Dra. Ana Ramírez"


@pytest.mark.asyncio
async def test_pedir_cita_con_el_doctor_sigue_funcionando_igual(doctora, telefono, monkeypatch):
    """
    La derivación no puede romper el camino normal: el 90% de los mensajes
    son para el Dr. Padilla.
    """
    from app.brain import router
    from app.whatsapp.parser import MensajeEntrante

    enviados = []

    async def enviar_falso(destino, texto, *a, **k):
        enviados.append(texto)

    monkeypatch.setattr("app.whatsapp.client.enviar_texto", enviar_falso)
    monkeypatch.setattr("app.whatsapp.client.enviar_lista",
                        lambda d, t, b, o: enviados.append(t))

    await router.procesar_mensaje(MensajeEntrante(
        telefono=telefono,
        texto="Quiero agendar una cita",
        wa_message_id="wamid.derivacion.2",
        nombre_perfil="Paciente Prueba",
    ))

    assert not any("+523310002000" in t for t in enviados), enviados
