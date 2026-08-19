"""
La capa que conversa.

Lo que se prueba acá no es que el modelo escriba bonito —eso no se puede
verificar automáticamente— sino todo lo que lo rodea, que es lo que puede
lastimar a un paciente:

  * que la barrera clínica siga corriendo ANTES que la IA, siempre;
  * que una alucinación no se convierta en una cita;
  * que si OpenAI se cae, el paciente reciba respuesta igual;
  * que el gasto quede contado aunque la conversación falle a la mitad;
  * y que no le conteste dos veces lo mismo con las mismas palabras.

No se llama a OpenAI en ningún momento: se sustituye el cliente por uno
guionado, para poder provocar exactamente los casos que importan.
"""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlmodel import select

from app.db import sesion
from app.models import (
    Ajuste,
    Cita,
    Conversacion,
    EstadoConversacion,
    Mensaje,
    Paciente,
    Remitente,
    Sede,
)
from app.whatsapp.parser import MensajeEntrante


# ----------------------------------------------------------------------
#  Un OpenAI de mentira
# ----------------------------------------------------------------------

class _Uso:
    prompt_tokens = 120
    completion_tokens = 60


def _mensaje(texto=None, herramientas=None):
    llamadas = None
    if herramientas:
        llamadas = [
            SimpleNamespace(
                id=f"call_{i}",
                type="function",
                function=SimpleNamespace(name=n, arguments=json.dumps(a)),
            )
            for i, (n, a) in enumerate(herramientas)
        ]
    return SimpleNamespace(content=texto, tool_calls=llamadas)


def _respuesta(mensaje):
    return SimpleNamespace(choices=[SimpleNamespace(message=mensaje)], usage=_Uso())


@pytest.fixture
def openai_falso(monkeypatch):
    """
    Devuelve un guion que la prueba llena con lo que debe «contestar» el
    modelo, y el registro de lo que se le pidió.
    """
    estado = {"guion": [], "peticiones": [], "explota": False}

    class Cliente:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._crear)
            )

        async def _crear(self, **kwargs):
            estado["peticiones"].append(kwargs)
            if estado["explota"]:
                raise RuntimeError("OpenAI no responde")
            return _respuesta(estado["guion"].pop(0))

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", Cliente)
    monkeypatch.setattr("app.config.config.openai_api_key", "sk-de-prueba", raising=False)
    return estado


@pytest.fixture
def modo_ia():
    """El sistema en modo híbrido, que es como va a producción."""
    with sesion() as s:
        ajuste = s.get(Ajuste, "modo_asistente")
        previo = ajuste.valor if ajuste else None
        if ajuste:
            ajuste.valor = "hibrido"
        else:
            s.add(Ajuste(clave="modo_asistente", valor="hibrido"))
        s.commit()
    yield
    with sesion() as s:
        ajuste = s.get(Ajuste, "modo_asistente")
        if ajuste:
            if previo is None:
                s.delete(ajuste)
            else:
                ajuste.valor = previo
            s.commit()


@pytest.fixture
def sede_con_franjas():
    """Una sede que puede agendar de verdad, para las pruebas de agenda."""
    with sesion() as s:
        sede = s.exec(select(Sede).where(Sede.activa).order_by(Sede.orden)).first()  # type: ignore[arg-type]
        previo = sede.franjas_json
        sede.franjas_json = json.dumps([
            {"dia": 0, "desde": "09:00", "hasta": "14:00"},
            {"dia": 2, "desde": "09:00", "hasta": "14:00"},
            {"dia": 4, "desde": "09:00", "hasta": "14:00"},
        ])
        s.add(sede)
        s.commit()
        s.refresh(sede)
        sede_id = sede.id
    yield sede_id
    with sesion() as s:
        sede = s.get(Sede, sede_id)
        sede.franjas_json = previo
        s.add(sede)
        s.commit()


@pytest.fixture
def modo_total():
    """
    Modo IA, donde el modelo contesta siempre.

    Se usa para probar la capa de IA en aislamiento: en híbrido lo previsto
    lo resuelven los flujos —que es lo correcto y lo que ahorra— y eso
    haría que estas pruebas no llegaran nunca al modelo.
    """
    with sesion() as s:
        ajuste = s.get(Ajuste, "modo_asistente")
        previo = ajuste.valor if ajuste else None
        if ajuste:
            ajuste.valor = "ia"
        else:
            s.add(Ajuste(clave="modo_asistente", valor="ia"))
        s.commit()
    yield
    with sesion() as s:
        ajuste = s.get(Ajuste, "modo_asistente")
        if ajuste:
            if previo is None:
                s.delete(ajuste)
            else:
                ajuste.valor = previo
            s.commit()


@pytest.fixture
def enviados(monkeypatch):
    salida = []

    async def enviar(destino, texto, *a, **k):
        salida.append(texto)

    monkeypatch.setattr("app.whatsapp.client.enviar_texto", enviar)
    monkeypatch.setattr("app.whatsapp.client.enviar_lista", enviar)
    monkeypatch.setattr("app.whatsapp.client.enviar_botones", enviar)
    return salida


async def _hablar(telefono, texto, wa_id="wamid.ia"):
    from app.brain import router

    await router.procesar_mensaje(MensajeEntrante(
        telefono=telefono, texto=texto, wa_message_id=wa_id,
        nombre_perfil="Paciente Prueba",
    ))


def _conversacion(telefono):
    with sesion() as s:
        p = s.exec(select(Paciente).where(Paciente.telefono == telefono)).first()
        return s.exec(
            select(Conversacion)
            .where(Conversacion.paciente_id == p.id)
            .order_by(Conversacion.ultima_actividad.desc())  # type: ignore[attr-defined]
        ).first()


# ======================================================================
#  Lo que no se negocia
# ======================================================================

@pytest.mark.asyncio
async def test_la_barrera_clinica_corre_antes_que_la_ia(
    openai_falso, modo_ia, enviados, telefono
):
    """
    El invariante del sistema. Un mensaje con síntomas NUNCA debe llegar al
    modelo: se responde con el texto fijo de la barrera y se deriva.
    """
    openai_falso["guion"] = [_mensaje("esto no debería enviarse jamás")]

    await _hablar(telefono, "Tengo un dolor muy fuerte del lado derecho y fiebre")

    assert openai_falso["peticiones"] == [], "la IA vio un mensaje clínico"
    assert _conversacion(telefono).estado is EstadoConversacion.REQUIERE_ATENCION
    assert any("urgencias" in t.lower() for t in enviados)


@pytest.mark.asyncio
async def test_si_openai_se_cae_el_paciente_igual_recibe_respuesta(
    openai_falso, modo_ia, enviados, telefono
):
    """
    La red de seguridad que hace que activar la IA no sea un riesgo: si el
    proveedor falla, contestan los flujos y el paciente no se entera.
    """
    openai_falso["explota"] = True

    await _hablar(telefono, "¿Cuánto cuesta la consulta?")

    assert enviados, "el paciente se quedó sin respuesta"
    assert "900" in enviados[0]


@pytest.mark.asyncio
async def test_sin_clave_configurada_contestan_los_flujos(
    modo_ia, enviados, telefono, monkeypatch
):
    """
    Es exactamente lo que pasaba en producción: sin OPENAI_API_KEY el
    sistema queda en modo básico sin decirlo. Debe seguir atendiendo.
    """
    monkeypatch.setattr("app.config.config.openai_api_key", "", raising=False)

    await _hablar(telefono, "¿Cuánto cuesta la consulta?")

    assert any("900" in t for t in enviados)


# ======================================================================
#  Conversar
# ======================================================================

@pytest.mark.asyncio
async def test_la_ia_contesta_lo_que_las_reglas_no_entienden(
    openai_falso, modo_ia, enviados, telefono
):
    """
    El caso que motivó todo esto: una pregunta que ningún catálogo previó.
    """
    openai_falso["guion"] = [_mensaje(
        "Claro que sí. El Dr. Padilla opera vesícula por laparoscopía, "
        "que es con incisiones pequeñas. ¿Le gustaría que le agende una "
        "valoración para revisarlo?"
    )]

    await _hablar(telefono, "oiga y el doctor hace lo de la vesicula por laparoscopia o abierto?")

    assert "laparoscopía" in enviados[0]

    with sesion() as s:
        mensajes = list(s.exec(
            select(Mensaje).where(Mensaje.remitente == Remitente.BOT,
                                  Mensaje.generado_por_ia)
        ).all())
    assert mensajes, "la respuesta no quedó marcada como generada por IA"


@pytest.mark.asyncio
async def test_el_prompt_lleva_las_restricciones_y_la_fecha(
    openai_falso, modo_ia, enviados, telefono
):
    openai_falso["guion"] = [_mensaje("Con gusto.")]

    await _hablar(telefono, "una pregunta suelta")

    sistema = openai_falso["peticiones"][0]["messages"][0]["content"]
    assert "RESTRICCIONES ABSOLUTAS" in sistema
    assert "NO emitas diagnósticos" in sistema
    assert "Hoy es" in sistema          # para que entienda «el jueves»
    assert "Guadalajara" in sistema
    # Sin el id de cada sede, el modelo no puede consultar la agenda ni
    # agendar: tendría que adivinarlo.
    assert "sede_id:" in sistema


@pytest.mark.asyncio
async def test_la_segunda_vez_que_preguntan_lo_mismo_contesta_la_ia(
    openai_falso, modo_ia, enviados, telefono
):
    """
    El síntoma exacto que reportó el consultorio.

    La primera pregunta por el precio la contesta un flujo, gratis. Que la
    vuelva a preguntar significa que esa respuesta no le sirvió, así que la
    segunda la toma la IA — y se le pasa lo que ya se dijo para que no lo
    repita textual.
    """
    openai_falso["guion"] = [
        _mensaje("Son 900 pesos la valoración, e incluye la revisión completa "
                 "con el doctor. ¿Le busco un horario?")
    ]

    await _hablar(telefono, "¿Cuánto cuesta la consulta?", wa_id="wamid.rep.1")
    assert openai_falso["peticiones"] == [], "se pagó por una pregunta prevista"
    primera = enviados[-1]

    await _hablar(telefono, "y cuanto sale entonces?", wa_id="wamid.rep.2")

    assert openai_falso["peticiones"], "la repetición no llegó a la IA"
    sistema = openai_falso["peticiones"][0]["messages"][0]["content"]
    assert "YA DIJISTE ESTO" in sistema
    assert enviados[-1] != primera


@pytest.mark.asyncio
async def test_lo_previsto_se_contesta_gratis(
    openai_falso, modo_ia, enviados, telefono
):
    """
    El ahorro que se le prometió al consultorio: saludo, precio, ubicación y
    horarios los resuelven los flujos sin llamar al modelo.
    """
    await _hablar(telefono, "Hola, buenos días", wa_id="wamid.gratis.1")
    await _hablar(telefono, "¿Dónde están ubicados?", wa_id="wamid.gratis.2")

    assert openai_falso["peticiones"] == []
    assert len(enviados) >= 2


@pytest.mark.asyncio
async def test_el_historial_viaja_para_que_haya_memoria(
    openai_falso, modo_total, enviados, telefono
):
    openai_falso["guion"] = [_mensaje("Mucho gusto, Ana."), _mensaje("Claro que sí.")]

    await _hablar(telefono, "me llamo Ana", wa_id="wamid.mem.1")
    await _hablar(telefono, "oiga y eso lo cubre mi aseguradora?", wa_id="wamid.mem.2")

    mensajes = openai_falso["peticiones"][1]["messages"]
    contenidos = " ".join(str(m.get("content") or "") for m in mensajes)
    assert "me llamo Ana" in contenidos


# ======================================================================
#  Herramientas: que además de hablar, haga
# ======================================================================

@pytest.mark.asyncio
async def test_consulta_la_agenda_real_antes_de_ofrecer_horarios(
    openai_falso, modo_total, enviados, telefono, sede_con_franjas
):
    openai_falso["guion"] = [
        _mensaje(herramientas=[("consultar_disponibilidad", {"sede_id": sede_con_franjas})]),
        _mensaje("Tengo lugar el martes a las 10. ¿Le acomoda?"),
    ]

    await _hablar(telefono, "hay chance esta semana?")

    herramienta = [m for m in openai_falso["peticiones"][1]["messages"]
                   if m.get("role") == "tool"][0]
    datos = json.loads(herramienta["content"])
    assert datos["ok"] and datos["puede_agendar"]
    assert datos["horarios"], "no se le pasó ningún horario real al modelo"


@pytest.mark.asyncio
async def test_agenda_de_verdad_cuando_el_paciente_elige(
    openai_falso, modo_total, enviados, telefono, sede_con_franjas
):
    from app.agenda.service import ofrecer_horarios

    huecos = await ofrecer_horarios(sede_con_franjas, cantidad=1)
    elegido = huecos[0].inicio.isoformat()

    openai_falso["guion"] = [
        _mensaje(herramientas=[("agendar_cita", {
            "sede_id": sede_con_franjas, "inicio": elegido})]),
        _mensaje("Listo, su cita quedó para esa fecha."),
    ]

    await _hablar(telefono, "si, el martes a las 10 me viene bien")

    with sesion() as s:
        paciente = s.exec(select(Paciente).where(Paciente.telefono == telefono)).first()
        citas = list(s.exec(select(Cita).where(Cita.paciente_id == paciente.id)).all())

    assert len(citas) == 1
    assert _conversacion(telefono).convirtio is True


@pytest.mark.asyncio
async def test_una_alucinacion_no_se_convierte_en_cita(
    openai_falso, modo_total, enviados, telefono, sede_con_franjas
):
    """
    La prueba más importante de este archivo.

    Si el modelo se inventa un horario —un domingo a las tres de la mañana—
    el proveedor de agenda lo rechaza igual que rechazaría a un paciente. No
    hay forma de que una alucinación termine en la agenda del doctor.
    """
    inventado = (datetime.utcnow() + timedelta(days=3)).replace(
        hour=3, minute=0, second=0, microsecond=0
    ).isoformat()

    openai_falso["guion"] = [
        _mensaje(herramientas=[("agendar_cita", {
            "sede_id": sede_con_franjas, "inicio": inventado})]),
        _mensaje("Ese horario ya no está. Le ofrezco otro."),
    ]

    await _hablar(telefono, "agendame el domingo a las 3 de la mañana")

    with sesion() as s:
        paciente = s.exec(select(Paciente).where(Paciente.telefono == telefono)).first()
        citas = list(s.exec(select(Cita).where(Cita.paciente_id == paciente.id)).all())

    assert citas == [], "se agendó un horario inventado"

    herramienta = [m for m in openai_falso["peticiones"][1]["messages"]
                   if m.get("role") == "tool"][0]
    assert json.loads(herramienta["content"])["ok"] is False


@pytest.mark.asyncio
async def test_sin_franjas_no_promete_ningun_horario(
    openai_falso, modo_total, enviados, telefono
):
    """
    Sin franjas el asistente no ve la agenda. Prometer a ciegas sería peor
    que no prometer: se le dice al modelo y él lo explica con sus palabras.
    """
    with sesion() as s:
        sede = s.exec(select(Sede).where(Sede.activa)).first()
        sede_id = sede.id
        previo = sede.franjas_json
        sede.franjas_json = "[]"      # esta prueba define su propio escenario
        s.add(sede)
        s.commit()

    openai_falso["guion"] = [
        _mensaje(herramientas=[("consultar_disponibilidad", {"sede_id": sede_id})]),
        _mensaje("Déjeme confirmarlo con el consultorio y le aviso."),
    ]

    await _hablar(telefono, "para cuando hay lugar?")

    herramienta = [m for m in openai_falso["peticiones"][1]["messages"]
                   if m.get("role") == "tool"][0]
    datos = json.loads(herramienta["content"])

    with sesion() as s:
        sede = s.get(Sede, sede_id)
        sede.franjas_json = previo
        s.add(sede)
        s.commit()

    assert datos["puede_agendar"] is False
    assert "NO prometas" in datos["motivo"]


@pytest.mark.asyncio
async def test_la_ia_puede_pedir_que_atienda_una_persona(
    openai_falso, modo_total, enviados, telefono
):
    openai_falso["guion"] = [
        _mensaje(herramientas=[("derivar_a_persona", {
            "motivo": "El paciente está molesto por la espera."})]),
        _mensaje("Con gusto la comunico con el consultorio."),
    ]

    await _hablar(telefono, "llevo tres dias esperando que me contesten, esto es una falta de respeto")

    conversacion = _conversacion(telefono)
    assert conversacion.estado is EstadoConversacion.REQUIERE_ATENCION
    assert enviados, "no se le contestó al paciente antes de derivar"


@pytest.mark.asyncio
async def test_el_modelo_no_escribe_solo_en_la_base(
    openai_falso, modo_total, enviados, telefono, sede_con_franjas
):
    """
    Derivar y convertir los aplica el router. El modelo pide; el código
    decide. Si pide derivar, la conversación queda marcada por el sistema y
    con el motivo que dio, no con lo que el modelo diga que hizo.
    """
    openai_falso["guion"] = [
        _mensaje(herramientas=[("derivar_a_persona", {"motivo": "Pidió factura."})]),
        _mensaje("Lo paso con el consultorio."),
    ]

    await _hablar(telefono, "necesito mi factura del mes pasado")

    with sesion() as s:
        from app.models import RegistroAuditoria

        registros = [r for r in s.exec(select(RegistroAuditoria)).all()
                     if r.accion == "conversacion.escalada"]
    assert any("factura" in (r.detalle or "").lower() for r in registros)


# ======================================================================
#  Costo
# ======================================================================

@pytest.mark.asyncio
async def test_el_gasto_se_cuenta_sumando_todas_las_rondas(
    openai_falso, modo_total, enviados, telefono, sede_con_franjas
):
    from app.brain.ai import consumo_del_mes

    antes = consumo_del_mes().costo_usd

    openai_falso["guion"] = [
        _mensaje(herramientas=[("consultar_disponibilidad", {"sede_id": sede_con_franjas})]),
        _mensaje("Tengo estos horarios."),
    ]

    await _hablar(telefono, "cuando hay lugar?")

    assert consumo_del_mes().costo_usd > antes


@pytest.mark.asyncio
async def test_con_el_tope_alcanzado_no_se_llama_a_openai(
    openai_falso, modo_ia, enviados, telefono, monkeypatch
):
    """El tope es duro: nunca hay cargos sorpresa."""
    monkeypatch.setattr("app.brain.ai.tope_alcanzado", lambda: True)

    await _hablar(telefono, "¿Cuánto cuesta la consulta?")

    assert openai_falso["peticiones"] == []
    assert enviados, "el paciente se quedó sin respuesta"
