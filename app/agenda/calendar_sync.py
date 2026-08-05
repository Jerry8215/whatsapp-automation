"""
Plan B — sincronización por calendario.

Se usa si Docplanner no habilita el acceso a la API. Doctoralia exporta
la agenda como feed iCal, y de ahí leemos lo ocupado.

La limitación que hay que tener presente todo el tiempo:

    LOS FEEDS iCal SON DE SOLO LECTURA.

No podemos escribir en Doctoralia. Por eso, con este proveedor:

  * Las citas nacen como SOLICITADA, no como AGENDADA.
  * La asistente las confirma desde el panel con un clic, y ella es quien
    las carga en Doctoralia.
  * Para los turnos del mismo día se exige esa confirmación humana, porque
    el widget del sitio web del consultorio también reserva sobre la misma
    agenda y el feed puede tardar en reflejarlo.

Todo esto desaparece el día que llegue el acceso a la API.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta

import httpx
from icalendar import Calendar
from sqlmodel import select

from app.agenda.base import (
    CupoYaOcupado,
    Hueco,
    ProveedorAgenda,
    ResultadoReserva,
)
from app.config import config
from app.db import sesion
from app.models import Cita, EstadoCita, Sede

log = logging.getLogger(__name__)

TIEMPO_ESPERA = 25.0
CACHE_SEGUNDOS = 120
HORAS_MINIMAS_ANTICIPACION = 2

_cache: dict[str, tuple[datetime, list[tuple[datetime, datetime]]]] = {}


class SincroniaCalendario(ProveedorAgenda):
    escribe_en_doctoralia = False

    # ------------------------------------------------------------------
    #  Lectura del feed
    # ------------------------------------------------------------------

    async def _eventos(self, url: str) -> list[tuple[datetime, datetime]]:
        if not url:
            return []

        guardado = _cache.get(url)
        if guardado and (datetime.utcnow() - guardado[0]).total_seconds() < CACHE_SEGUNDOS:
            return guardado[1]

        try:
            async with httpx.AsyncClient(timeout=TIEMPO_ESPERA, follow_redirects=True) as c:
                r = await c.get(url)
            r.raise_for_status()
            eventos = _leer_ical(r.content)
        except Exception:
            log.exception("No se pudo leer el calendario %s", url)
            # Ante un fallo de red se devuelve lo último conocido. Es
            # preferible a asumir que la agenda está vacía y sobrevender.
            return guardado[1] if guardado else []

        _cache[url] = (datetime.utcnow(), eventos)
        return eventos

    async def _ocupado_sede(
        self, sede: Sede, desde: datetime, hasta: datetime
    ) -> list[Hueco]:
        eventos = await self._eventos(sede.ical_url)
        ocupados = [
            Hueco(inicio=i, fin=f, sede_id=sede.id or 0)
            for i, f in eventos
            if i < hasta and desde < f
        ]

        # Sumamos lo que este sistema ya reservó y todavía no aparece en
        # el feed. Sin esto se podría vender dos veces el mismo horario.
        with sesion() as s:
            propias = s.exec(
                select(Cita).where(
                    Cita.sede_id == sede.id,
                    Cita.inicio < hasta,
                    Cita.fin > desde,
                    Cita.estado.in_([  # type: ignore[attr-defined]
                        EstadoCita.SOLICITADA,
                        EstadoCita.AGENDADA,
                        EstadoCita.CONFIRMADA,
                    ]),
                )
            ).all()
        ocupados += [
            Hueco(inicio=c.inicio, fin=c.fin, sede_id=c.sede_id, externo_id=str(c.id))
            for c in propias
        ]
        return ocupados

    # ------------------------------------------------------------------
    #  Interfaz
    # ------------------------------------------------------------------

    async def huecos(self, sede_id: int, desde: datetime, hasta: datetime) -> list[Hueco]:
        with sesion() as s:
            sede = s.get(Sede, sede_id)
        if not sede or not sede.activa:
            return []

        ocupados = await self._ocupado_sede(sede, desde, hasta)
        ocupados += await self._ocupado_otras_sedes(sede_id, desde, hasta)

        minimo = datetime.utcnow() + timedelta(hours=HORAS_MINIMAS_ANTICIPACION)
        libres: list[Hueco] = []

        for inicio, fin in _rejilla(sede, desde, hasta):
            if inicio < minimo:
                continue
            if any(o.se_solapa_con(inicio, fin) for o in ocupados):
                continue
            libres.append(Hueco(inicio=inicio, fin=fin, sede_id=sede_id))

        return libres

    async def _ocupado_otras_sedes(
        self, sede_id: int, desde: datetime, hasta: datetime
    ) -> list[Hueco]:
        """
        El doctor no puede estar en dos consultorios a la vez, y necesita
        tiempo para trasladarse. Cada cita en otra sede bloquea aquí su
        horario más el margen de traslado, a ambos lados.
        """
        margen = timedelta(minutes=config.minutos_traslado_entre_sedes)
        with sesion() as s:
            otras = s.exec(select(Sede).where(Sede.id != sede_id, Sede.activa)).all()

        bloqueos: list[Hueco] = []
        for otra in otras:
            for h in await self._ocupado_sede(otra, desde - margen, hasta + margen):
                bloqueos.append(Hueco(
                    inicio=h.inicio - margen,
                    fin=h.fin + margen,
                    sede_id=sede_id,
                ))
        return bloqueos

    async def ocupado(self, desde: datetime, hasta: datetime) -> list[Hueco]:
        with sesion() as s:
            sedes = s.exec(select(Sede)).all()
        salida: list[Hueco] = []
        for sede in sedes:
            salida += await self._ocupado_sede(sede, desde, hasta)
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
        # Re-verificación en el instante de confirmar, no cuando se
        # ofrecieron las opciones.
        libres = await self.huecos(sede_id, inicio - timedelta(minutes=1), fin + timedelta(minutes=1))
        if not any(h.inicio == inicio for h in libres):
            raise CupoYaOcupado("El horario se ocupó mientras el paciente elegía")

        # Turnos del mismo día: los valida una persona antes de darlos por
        # firmes, porque el feed puede no reflejar todavía una reserva
        # hecha desde el sitio web.
        mismo_dia = inicio.date() == datetime.utcnow().date()

        return ResultadoReserva(
            ok=True,
            externo_id="",
            requiere_confirmacion_humana=mismo_dia,
            motivo=(
                "Turno del mismo día: requiere que la asistente lo confirme en "
                "Doctoralia." if mismo_dia else
                "Plan B: la asistente debe cargarlo en Doctoralia."
            ),
        )

    async def cancelar(self, externo_id: str) -> bool:
        # No se puede escribir en Doctoralia. La cita se marca cancelada de
        # este lado y la asistente la retira allá desde el panel.
        return True

    async def reprogramar(
        self, externo_id: str, inicio: datetime, fin: datetime
    ) -> ResultadoReserva:
        return ResultadoReserva(
            ok=True,
            externo_id=externo_id,
            requiere_confirmacion_humana=True,
            motivo="Plan B: la asistente debe moverla en Doctoralia.",
        )


# ----------------------------------------------------------------------
#  Auxiliares
# ----------------------------------------------------------------------

def _leer_ical(contenido: bytes) -> list[tuple[datetime, datetime]]:
    eventos: list[tuple[datetime, datetime]] = []
    cal = Calendar.from_ical(contenido)
    for comp in cal.walk("VEVENT"):
        ini = comp.get("dtstart")
        fin = comp.get("dtend")
        if not ini or not fin:
            continue
        i, f = ini.dt, fin.dt
        if isinstance(i, date) and not isinstance(i, datetime):
            i = datetime.combine(i, time.min)
        if isinstance(f, date) and not isinstance(f, datetime):
            f = datetime.combine(f, time.min)
        eventos.append((i.replace(tzinfo=None), f.replace(tzinfo=None)))
    return eventos


def _rejilla(
    sede: Sede, desde: datetime, hasta: datetime
) -> list[tuple[datetime, datetime]]:
    """Todos los espacios teóricos de la sede según su horario publicado."""
    try:
        bloques = json.loads(sede.horario_json or "[]")
    except json.JSONDecodeError:
        log.error("horario_json inválido en la sede %s", sede.id)
        return []

    duracion = timedelta(minutes=sede.duracion_cita_min or 30)
    salida: list[tuple[datetime, datetime]] = []
    dia = desde.date()

    while dia <= hasta.date():
        for b in bloques:
            if b.get("dia") != dia.weekday():
                continue
            abre = datetime.combine(dia, time.fromisoformat(b["desde"]))
            cierra = datetime.combine(dia, time.fromisoformat(b["hasta"]))
            t = abre
            while t + duracion <= cierra:
                if desde <= t <= hasta:
                    salida.append((t, t + duracion))
                t += duracion
        dia += timedelta(days=1)

    return salida
