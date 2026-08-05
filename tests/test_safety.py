"""
Pruebas de la barrera clínica.

Estas son las pruebas que no se pueden romper. Si una falla, el sistema
no sale a producción: significa que un mensaje clínico podría llegar a
responderse automáticamente.
"""

import pytest

from app.brain.safety import Accion, Categoria, evaluar, normalizar


# ------------------------------------------------------------------
#  Signos de alarma → urgencias
# ------------------------------------------------------------------

@pytest.mark.parametrize(
    "mensaje",
    [
        "Tengo un dolor muy fuerte del lado derecho",
        "me duele muchisimo la panza desde anoche",
        "Traigo 39 de fiebre y no se me quita",
        "Tengo fiebre alta y escalofríos",
        "no puedo respirar bien",
        "Me falta el aire",
        "tengo dolor en el pecho",
        "estoy sangrando y no para",
        "Vomité sangre en la madrugada",
        "no paro de vomitar desde ayer",
        "Se me puso la piel amarilla",
        "tengo los ojos amarillos",
        "La herida se abrió",
        "sale pus de la herida",
        "la herida está muy roja y caliente",
        "no puedo pasar gases ni evacuar",
        "Tengo el abdomen duro",
        "me desmayé en la mañana",
    ],
)
def test_signos_de_alarma_mandan_a_urgencias(mensaje):
    v = evaluar(mensaje)
    assert v.accion is Accion.URGENCIAS, f"NO detectó alarma en: {mensaje!r}"
    assert v.categoria is Categoria.SIGNO_ALARMA
    assert "urgencias" in v.respuesta.lower()
    assert v.bloquea_ia


def test_la_respuesta_de_urgencias_nunca_tranquiliza():
    v = evaluar("tengo un dolor muy fuerte y fiebre alta")
    r = normalizar(v.respuesta)
    for frase in ("no es nada", "no se preocupe", "seguramente", "probablemente",
                  "es normal", "no es grave", "tranquila", "tranquilo"):
        assert frase not in r, f"La respuesta contiene «{frase}»"


# ------------------------------------------------------------------
#  Síntomas y opinión clínica → derivar
# ------------------------------------------------------------------

@pytest.mark.parametrize(
    "mensaje",
    [
        "Hola, me duele el estómago desde hace días",
        "tengo una bolita en la ingle",
        "me salió una bola en el abdomen",
        "se me inflamó la herida",
        "Tengo náuseas y acidez",
        "¿es normal que se vea rosada?",
        "¿usted qué opina?",
        "¿cree que sea grave?",
        "¿qué me recomienda?",
    ],
)
def test_sintomas_y_opiniones_se_derivan(mensaje):
    v = evaluar(mensaje)
    assert v.accion in (Accion.DERIVAR, Accion.URGENCIAS), f"No derivó: {mensaje!r}"
    assert v.bloquea_ia


# ------------------------------------------------------------------
#  Medicamentos → derivar
# ------------------------------------------------------------------

@pytest.mark.parametrize(
    "mensaje",
    [
        "¿Qué me puedo tomar para el dolor?",
        "que medicamento me recomienda",
        "¿puedo tomar ibuprofeno?",
        "¿cuánta dosis debo tomar?",
        "cada cuantas horas me tomo la pastilla",
        "¿dejo de tomar el antibiótico?",
    ],
)
def test_medicamentos_se_derivan(mensaje):
    v = evaluar(mensaje)
    assert v.accion is Accion.DERIVAR
    assert v.categoria in (Categoria.MEDICAMENTO, Categoria.SINTOMAS)


def test_la_respuesta_de_medicamento_no_sugiere_ninguno():
    v = evaluar("¿qué me puedo tomar para el dolor?")
    r = normalizar(v.respuesta)
    for farmaco in ("paracetamol", "ibuprofeno", "naproxeno", "ketorolaco",
                    "aspirina", "omeprazol", "metamizol", "mg"):
        assert farmaco not in r


# ------------------------------------------------------------------
#  Estudios → derivar
# ------------------------------------------------------------------

@pytest.mark.parametrize(
    "mensaje",
    [
        "Le mando mi ultrasonido",
        "te envío mis estudios",
        "¿qué dice mi ultrasonido?",
        "¿puede revisar mi tomografía?",
        "¿está bien mi análisis?",
        "que opina de mi estudio",
    ],
)
def test_estudios_se_derivan(mensaje):
    v = evaluar(mensaje)
    assert v.accion is Accion.DERIVAR
    assert v.categoria is Categoria.ESTUDIO


# ------------------------------------------------------------------
#  Pronóstico → derivar
# ------------------------------------------------------------------

@pytest.mark.parametrize(
    "mensaje",
    [
        "¿me voy a curar?",
        "¿voy a quedar bien?",
        "¿es peligrosa la cirugía?",
        "¿hay riesgo de complicaciones?",
        "¿cuánto tiempo voy a estar sin trabajar?",
        "¿me garantiza que sale bien?",
    ],
)
def test_pronostico_se_deriva(mensaje):
    v = evaluar(mensaje)
    assert v.accion is Accion.DERIVAR
    assert v.categoria in (Categoria.PRONOSTICO, Categoria.SINTOMAS)


# ------------------------------------------------------------------
#  Adjuntos → derivar sin abrir
# ------------------------------------------------------------------

@pytest.mark.parametrize("tipo", ["image", "document", "audio", "video", "sticker"])
def test_cualquier_adjunto_se_deriva(tipo):
    v = evaluar("", tipo_adjunto=tipo)
    assert v.accion is Accion.DERIVAR
    assert v.categoria is Categoria.ADJUNTO


def test_el_adjunto_gana_aunque_el_texto_sea_inofensivo():
    v = evaluar("Buenos días, le mando esto", tipo_adjunto="image")
    assert v.categoria is Categoria.ADJUNTO


# ------------------------------------------------------------------
#  Lo administrativo debe pasar sin fricción
# ------------------------------------------------------------------

@pytest.mark.parametrize(
    "mensaje",
    [
        "Hola, buenos días",
        "¿Cuánto cuesta la consulta?",
        "quiero agendar una cita",
        "¿dónde está el consultorio?",
        "¿a qué hora abren?",
        "¿aceptan seguro de gastos médicos?",
        "necesito una factura",
        "¿hay estacionamiento?",
        "Confirmo mi cita del jueves",
        "necesito cancelar mi cita",
        "¿qué documentos llevo?",
        "Gracias, muy amable",
    ],
)
def test_lo_administrativo_no_se_bloquea(mensaje):
    v = evaluar(mensaje)
    assert v.accion is Accion.CONTINUAR, f"Bloqueó de más: {mensaje!r} → {v.coincidencia!r}"
    assert not v.bloquea_ia


# ------------------------------------------------------------------
#  Robustez
# ------------------------------------------------------------------

def test_los_acentos_no_evaden_la_barrera():
    con = evaluar("Tengo dolor muy fuerte")
    sin = evaluar("Tengo dolor muy fuerte".replace("ó", "o"))
    assert con.accion is sin.accion is Accion.URGENCIAS


def test_las_mayusculas_no_evaden_la_barrera():
    assert evaluar("TENGO UN DOLOR MUY FUERTE").accion is Accion.URGENCIAS


def test_mensaje_vacio_no_rompe():
    assert evaluar("").accion is Accion.CONTINUAR
    assert evaluar("   ").accion is Accion.CONTINUAR


def test_la_alarma_gana_sobre_las_demas_categorias():
    """Un mensaje que menciona estudio y alarma debe irse por urgencias."""
    v = evaluar("Le mando mi ultrasonido, pero tengo un dolor muy fuerte y fiebre alta")
    assert v.accion is Accion.URGENCIAS
