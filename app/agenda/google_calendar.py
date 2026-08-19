"""
Plan C — Google Calendar.

**Por qué existe.** Doctoralia confirmó por escrito que no ofrece ninguna
forma de conexión: ni API, ni exportación, ni sincronización. Mientras la
agenda viva ahí, el asistente no puede verla, y por eso se trabaja con
franjas reservadas (`app/agenda/franjas.py`).

Google Calendar sí tiene una API pública y completa. Con este proveedor el
asistente **lee la disponibilidad real y escribe la cita él mismo**: se
acaba la lista de «por cargar a mano», y la agenda del consultorio pasa a
ser una sola de verdad.

    Doctoralia (franjas)  →  el asistente agenda a ciegas dentro de su franja
                             y una persona lo copia después
    Google Calendar       →  el asistente ve todo y escribe él mismo

Queda listo y en pausa, tal como se acordó: el consultorio sigue en
Doctoralia hoy, y el día que decida mudarse cambia el origen de la agenda
desde el panel, sin que nadie toque código.

**Cómo se conecta: cuenta de servicio.** El consultorio comparte su agenda
con un correo técnico y le da permiso de «hacer cambios en los eventos». No
hay que iniciar sesión con la cuenta personal del doctor, ni renovar
permisos cada cierto tiempo, ni depende de que el desarrollador siga
teniendo acceso a nada.

Se habla con la API por HTTP directo, sin las bibliotecas oficiales de
Google: son tres llamadas y traerlas costaría una docena de dependencias en
el servidor.
"""

from __future__ import annotations

import json
import logging
import time as _time
from datetime import datetime, time, timedelta
from pathlib import Path

import httpx
from sqlmodel import select

from app.agenda.base import (
    CupoYaOcupado,
    ErrorAgenda,
    Hueco,
    ProveedorAgenda,
    ResultadoReserva,
)
from app.config import config
from app.db import sesion
from app.models import Cita, EstadoCita, Sede
from app.tiempo import a_local, combinar_local

log = logging.getLogger(__name__)

ALCANCE = "https://www.googleapis.com/auth/calendar"
URL_TOKEN = "https://oauth2.googleapis.com/token"
URL_API = "https://www.googleapis.com/calendar/v3"

HORAS_MINIMAS_ANTICIPACION = 2

#: Se pide el token un poco antes de que venza: si vence en medio de una
#: reserva, el paciente ve un error por treinta segundos de diferencia.
MARGEN_TOKEN_SEG = 120


class ErrorGoogle(ErrorAgenda):
    pass


# ======================================================================
#  Credenciales
# ======================================================================

_token: str = ""
_token_vence: float = 0.0


def credenciales() -> dict:
    """
    La cuenta de servicio, venga como JSON o como ruta a un archivo.

    En Railway se pega el JSON completo en la variable de entorno; en una
    máquina local es más cómodo un archivo. Se aceptan las dos formas
    porque obligar a una sola garantiza que alguien la configure mal.
    """
    crudo = (config.google_cuenta_servicio_json or "").strip()
    if not crudo:
        raise ErrorGoogle("Falta GOOGLE_CUENTA_SERVICIO_JSON")

    if not crudo.startswith("{"):
        archivo = Path(crudo)
        if not archivo.is_file():
            raise ErrorGoogle(f"No existe el archivo de credenciales: {crudo}")
        crudo = archivo.read_text(encoding="utf-8")

    try:
        datos = json.loads(crudo)
    except json.JSONDecodeError as e:
        raise ErrorGoogle(f"Las credenciales de Google no son un JSON válido: {e}")

    for campo in ("client_email", "private_key"):
        if not datos.get(campo):
            raise ErrorGoogle(f"A las credenciales de Google les falta «{campo}»")
    return datos


def correo_de_servicio() -> str:
    """El correo con el que el consultorio debe compartir su agenda."""
    try:
        return credenciales().get("client_email", "")
    except ErrorGoogle:
        return ""


async def token_de_acceso() -> str:
    """Token vigente, pidiendo uno nuevo solo cuando hace falta."""
    global _token, _token_vence

    if _token and _time.monotonic() < _token_vence:
        return _token

    datos = credenciales()
    ahora = int(_time.time())
    afirmacion = {
        "iss": datos["client_email"],
        "scope": ALCANCE,
        "aud": URL_TOKEN,
        "iat": ahora,
        "exp": ahora + 3600,
    }

    from jose import jwt

    firmada = jwt.encode(afirmacion, datos["private_key"], algorithm="RS256")

    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.post(URL_TOKEN, data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": firmada,
        })
    if r.status_code != 200:
        raise ErrorGoogle(f"Google rechazó las credenciales ({r.status_code}): {r.text[:200]}")

    cuerpo = r.json()
    _token = cuerpo["access_token"]
    _token_vence = _time.monotonic() + cuerpo.get("expires_in", 3600) - MARGEN_TOKEN_SEG
    return _token


def olvidar_token() -> None:
    """Para las pruebas y para cuando cambien las credenciales."""
    global _token, _token_vence
    _token, _token_vence = "", 0.0


async def _llamar(metodo: str, ruta: str, **kwargs) -> dict:
    encabezados = {"Authorization": f"Bearer {await token_de_acceso()}"}
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.request(metodo, f"{URL_API}{ruta}", headers=encabezados, **kwargs)

    if r.status_code == 404:
        raise ErrorGoogle(
            "Google no encuentra la agenda. Reviśe que esté compartida con "
            f"{correo_de_servicio()} y que el identificador sea correcto."
        )
    if r.status_code == 403:
        raise ErrorGoogle(
            f"Google no autoriza la operación. La agenda debe estar compartida "
            f"con {correo_de_servicio()} con permiso para «hacer cambios en los eventos»."
        )
    if r.status_code >= 400:
        raise ErrorGoogle(f"Google respondió {r.status_code}: {r.text[:200]}")

    return r.json() if r.content else {}


# ======================================================================
#  El proveedor
# ======================================================================

class AgendaGoogle(ProveedorAgenda):
    """
    Lectura y escritura reales sobre Google Calendar.

    A diferencia de las franjas, acá el asistente ve toda la agenda y
    escribe él mismo. No queda ningún paso manual pendiente.
    """

    escribe_en_la_agenda = True

    # ------------------------------------------------------------------

    async def huecos(self, sede_id: int, desde: datetime, hasta: datetime) -> list[Hueco]:
        with sesion() as s:
            sede = s.get(Sede, sede_id)
        if not sede or not sede.activa:
            return []

        ocupados = await self._ocupado_en(calendario_de(sede), desde, hasta)
        # Lo que este sistema agendó y Google todavía no refleja (el feed
        # puede tardar unos segundos en propagar un evento recién creado).
        ocupados += _citas_locales(sede_id, desde, hasta)
        ocupados += await self._otras_sedes(sede_id, desde, hasta)

        minimo = datetime.utcnow() + timedelta(hours=HORAS_MINIMAS_ANTICIPACION)
        libres: list[Hueco] = []

        for inicio, fin in _rejilla_de_atencion(sede, desde, hasta):
            if inicio < minimo:
                continue
            if any(o.se_solapa_con(inicio, fin) for o in ocupados):
                continue
            libres.append(Hueco(inicio=inicio, fin=fin, sede_id=sede_id))

        return libres

    async def _ocupado_en(
        self, calendario: str, desde: datetime, hasta: datetime
    ) -> list[Hueco]:
        """Lo ocupado según Google, con `freeBusy`.

        Se usa `freeBusy` y no el listado de eventos a propósito: devuelve
        solo los rangos ocupados, sin títulos ni invitados. No hay ninguna
        razón para que este sistema vea de qué es cada cita del doctor.
        """
        if not calendario:
            return []

        cuerpo = {
            "timeMin": _iso(desde),
            "timeMax": _iso(hasta),
            "items": [{"id": calendario}],
        }
        datos = await _llamar("POST", "/freeBusy", json=cuerpo)

        calendarios = datos.get("calendars", {})
        entrada = calendarios.get(calendario, {})
        if entrada.get("errors"):
            raise ErrorGoogle(
                f"Google no pudo leer la agenda «{calendario}»: {entrada['errors']}"
            )

        return [
            Hueco(
                inicio=_desde_iso(b["start"]),
                fin=_desde_iso(b["end"]),
                sede_id=0,
            )
            for b in entrada.get("busy", [])
        ]

    async def _otras_sedes(
        self, sede_id: int, desde: datetime, hasta: datetime
    ) -> list[Hueco]:
        """
        El doctor no puede estar en dos consultorios a la vez, y necesita
        tiempo para trasladarse.

        Si todas las sedes comparten la misma agenda de Google —lo habitual—
        `freeBusy` ya devolvió esas citas. El margen de traslado, no: hay que
        agregarlo.
        """
        margen = timedelta(minutes=config.minutos_traslado_entre_sedes)
        if not margen:
            return []

        with sesion() as s:
            propia = s.get(Sede, sede_id)
            otras = list(s.exec(
                select(Sede).where(Sede.id != sede_id, Sede.activa)  # type: ignore[arg-type]
            ).all())

        calendario_propio = calendario_de(propia) if propia else ""
        bloqueos: list[Hueco] = []

        for otra in otras:
            ocupados = _citas_locales(otra.id, desde - margen, hasta + margen)  # type: ignore[arg-type]

            # Solo se consulta a Google si esa sede usa OTRA agenda; si
            # comparten la misma, ya vino en la consulta anterior.
            calendario = calendario_de(otra)
            if calendario and calendario != calendario_propio:
                ocupados += await self._ocupado_en(calendario, desde - margen, hasta + margen)

            for h in ocupados:
                bloqueos.append(Hueco(
                    inicio=h.inicio - margen,
                    fin=h.fin + margen,
                    sede_id=sede_id,
                ))
        return bloqueos

    async def ocupado(self, desde: datetime, hasta: datetime) -> list[Hueco]:
        with sesion() as s:
            sedes = list(s.exec(select(Sede)).all())

        vistos: set[str] = set()
        salida: list[Hueco] = []
        for sede in sedes:
            calendario = calendario_de(sede)
            if calendario and calendario not in vistos:
                vistos.add(calendario)
                salida += await self._ocupado_en(calendario, desde, hasta)
            salida += _citas_locales(sede.id, desde, hasta)  # type: ignore[arg-type]
        return salida

    async def reservar(
        self,
        *,
        sede_id: int,
        inicio: datetime,
        fin: datetime,
        nombre_paciente: str,
        telefono: str,
        motivo: str = "",
    ) -> ResultadoReserva:
        # Re-verificación en el instante de confirmar, no al ofrecer: el
        # hueco pudo ocuparse mientras el paciente elegía.
        libres = await self.huecos(
            sede_id, inicio - timedelta(minutes=1), fin + timedelta(minutes=1)
        )
        if not any(h.inicio == inicio for h in libres):
            raise CupoYaOcupado("El horario se ocupó mientras el paciente elegía")

        with sesion() as s:
            sede = s.get(Sede, sede_id)
        if not sede:
            raise ErrorGoogle("Sede inexistente")

        calendario = calendario_de(sede)
        if not calendario:
            raise ErrorGoogle(
                f"La sede «{sede.nombre}» no tiene agenda de Google configurada"
            )

        creado = await _llamar(
            "POST", f"/calendars/{_ruta(calendario)}/events",
            json=_cuerpo_evento(
                sede=sede, inicio=inicio, fin=fin,
                nombre_paciente=nombre_paciente, telefono=telefono,
                motivo=motivo, origen="asistente-whatsapp",
            ),
        )

        return ResultadoReserva(
            ok=True,
            externo_id=creado.get("id", ""),
            requiere_confirmacion_humana=False,
            motivo="Escrita directamente en Google Calendar.",
        )

    async def cancelar(self, externo_id: str) -> bool:
        if not externo_id:
            return True
        calendario = _calendario_del_evento(externo_id)
        try:
            await _llamar("DELETE", f"/calendars/{_ruta(calendario)}/events/{externo_id}")
            return True
        except ErrorGoogle:
            # Que el evento ya no esté no es un fallo: el objetivo era que
            # no ocupara lugar, y no lo ocupa.
            log.warning("No se pudo borrar el evento %s de Google", externo_id)
            return False

    async def reprogramar(
        self, externo_id: str, inicio: datetime, fin: datetime
    ) -> ResultadoReserva:
        if not externo_id:
            return ResultadoReserva(ok=False, motivo="La cita no tiene evento en Google")

        calendario = _calendario_del_evento(externo_id)
        await _llamar(
            "PATCH",
            f"/calendars/{_ruta(calendario)}/events/{externo_id}",
            json={
                "start": {"dateTime": _iso(inicio), "timeZone": "UTC"},
                "end": {"dateTime": _iso(fin), "timeZone": "UTC"},
            },
        )
        return ResultadoReserva(
            ok=True, externo_id=externo_id, requiere_confirmacion_humana=False
        )


# ======================================================================
#  Auxiliares
# ======================================================================

def _cuerpo_evento(
    *,
    sede: Sede,
    inicio: datetime,
    fin: datetime,
    nombre_paciente: str,
    telefono: str,
    motivo: str,
    origen: str,
) -> dict:
    """
    El evento tal como se escribe en Google.

    Nada clínico: nombre, teléfono, sede y el motivo administrativo. La
    agenda de Google puede estar compartida con otras personas del
    consultorio, así que acá la regla pesa más que en ningún otro lado.

    `origen` deja registrado quién creó la cita —el asistente o una
    persona—, que es lo que después permite distinguirlas.
    """
    de_donde = (
        "Cita agendada por WhatsApp." if origen == "asistente-whatsapp"
        else "Cita registrada desde el panel del consultorio."
    )
    return {
        "summary": f"{nombre_paciente} — {motivo or 'valoración'}",
        "description": f"{de_donde}\nTeléfono: {telefono}\nSede: {sede.nombre}",
        "location": sede.direccion or sede.nombre,
        "start": {"dateTime": _iso(inicio), "timeZone": "UTC"},
        "end": {"dateTime": _iso(fin), "timeZone": "UTC"},
        "extendedProperties": {"private": {"origen": origen, "telefono": telefono}},
    }


async def registrar_evento(
    *,
    sede: Sede,
    inicio: datetime,
    fin: datetime,
    nombre_paciente: str,
    telefono: str,
    motivo: str = "",
) -> str:
    """
    Escribe en Google una cita que ya existe en otro lado.

    Es lo que usa el panel cuando la asistente carga una cita que entró por
    Doctoralia o por teléfono. A diferencia de `reservar`, **no verifica
    disponibilidad**: acá no se está pidiendo un lugar, se está registrando
    algo que ya ocurrió. Si el consultorio decidió sobreponer dos citas,
    ese es su criterio y el sistema no lo discute.
    """
    calendario = calendario_de(sede)
    if not calendario:
        raise ErrorGoogle(f"La sede «{sede.nombre}» no tiene agenda de Google configurada")

    creado = await _llamar(
        "POST", f"/calendars/{_ruta(calendario)}/events",
        json=_cuerpo_evento(
            sede=sede, inicio=inicio, fin=fin,
            nombre_paciente=nombre_paciente, telefono=telefono,
            motivo=motivo, origen="panel",
        ),
    )
    return creado.get("id", "")


def calendario_de(sede: Sede | None) -> str:
    """
    Qué agenda usa una sede.

    Lo normal es que las tres compartan la misma —es un solo doctor—, así
    que la de la sede es opcional y se cae a la general.
    """
    if sede and sede.calendario_google_id:
        return sede.calendario_google_id
    return config.google_calendario_id


def _calendario_del_evento(externo_id: str) -> str:
    """La agenda donde vive un evento ya creado."""
    with sesion() as s:
        cita = s.exec(select(Cita).where(Cita.externo_id == externo_id)).first()
        sede = s.get(Sede, cita.sede_id) if cita else None
    return calendario_de(sede)


def _citas_locales(sede_id: int, desde: datetime, hasta: datetime) -> list[Hueco]:
    with sesion() as s:
        citas = list(s.exec(
            select(Cita).where(
                Cita.sede_id == sede_id,
                Cita.inicio < hasta,
                Cita.fin > desde,
                Cita.estado.in_([  # type: ignore[attr-defined]
                    EstadoCita.SOLICITADA, EstadoCita.AGENDADA, EstadoCita.CONFIRMADA,
                ]),
            )
        ).all())
    return [
        Hueco(inicio=c.inicio, fin=c.fin, sede_id=c.sede_id, externo_id=str(c.id))
        for c in citas
    ]


def _rejilla_de_atencion(
    sede: Sede, desde: datetime, hasta: datetime
) -> list[tuple[datetime, datetime]]:
    """
    Los espacios posibles de una sede, en UTC.

    Acá se usa el **horario completo de atención**, no las franjas: con
    Google el asistente ve la agenda entera, así que ya no hace falta
    reservarle un pedazo aparte. Es la ganancia de mudarse.
    """
    try:
        bloques = json.loads(sede.horario_json or "[]")
    except json.JSONDecodeError:
        log.error("horario_json inválido en la sede %s", sede.id)
        return []

    if not bloques:
        return []

    duracion = timedelta(minutes=sede.duracion_cita_min or 30)
    salida: list[tuple[datetime, datetime]] = []

    dia = a_local(desde).date() - timedelta(days=1)
    ultimo = a_local(hasta).date() + timedelta(days=1)

    while dia <= ultimo:
        for b in bloques:
            if b.get("dia") != dia.weekday():
                continue
            abre = combinar_local(dia, time.fromisoformat(b["desde"]))
            cierra = combinar_local(dia, time.fromisoformat(b["hasta"]))
            t = abre
            while t + duracion <= cierra:
                if desde <= t <= hasta:
                    salida.append((t, t + duracion))
                t += duracion
        dia += timedelta(days=1)

    return sorted(salida)


def _iso(dt: datetime) -> str:
    """UTC, como lo quiere Google."""
    return dt.replace(microsecond=0).isoformat() + "Z"


def _desde_iso(texto: str) -> datetime:
    """De lo que devuelve Google a UTC naive, que es como se guarda todo."""
    from datetime import timezone

    dt = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _ruta(calendario: str) -> str:
    from urllib.parse import quote

    return quote(calendario, safe="")


# ======================================================================
#  Diagnóstico
# ======================================================================

async def probar_conexion() -> dict:
    """
    ¿Está lista la conexión con Google?

    Lo usa el panel para que el consultorio pueda comprobarlo **antes** de
    mudar la agenda, y no descubrir el problema con un paciente esperando.
    """
    if not config.google_configurado:
        return {
            "ok": False,
            "detalle": "Todavía no se cargaron las credenciales de Google en el servidor.",
            "correo_servicio": "",
            "agendas": [],
        }

    correo = correo_de_servicio()

    try:
        await token_de_acceso()
    except Exception as e:
        return {"ok": False, "detalle": str(e), "correo_servicio": correo, "agendas": []}

    with sesion() as s:
        sedes = list(s.exec(select(Sede).where(Sede.activa)).all())  # type: ignore[arg-type]

    agendas: list[dict] = []
    todo_bien = True
    proveedor_prueba = AgendaGoogle()
    desde = datetime.utcnow()
    hasta = desde + timedelta(days=1)

    for sede in sedes:
        calendario = calendario_de(sede)
        if not calendario:
            todo_bien = False
            agendas.append({
                "sede": sede.nombre,
                "calendario": "",
                "ok": False,
                "detalle": "Sin agenda de Google asignada",
            })
            continue
        try:
            await proveedor_prueba._ocupado_en(calendario, desde, hasta)
            agendas.append({
                "sede": sede.nombre, "calendario": calendario,
                "ok": True, "detalle": "Lectura y escritura verificadas",
            })
        except Exception as e:
            todo_bien = False
            agendas.append({
                "sede": sede.nombre, "calendario": calendario,
                "ok": False, "detalle": str(e),
            })

    return {
        "ok": todo_bien and bool(agendas),
        "detalle": (
            "Conexión correcta." if todo_bien and agendas
            else "Hay agendas sin configurar o sin compartir."
        ),
        "correo_servicio": correo,
        "agendas": agendas,
    }
