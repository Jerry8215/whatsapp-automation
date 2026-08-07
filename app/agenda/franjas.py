"""
Franjas reservadas — el proveedor de agenda que se usa en producción.

**Por qué existe.** El 7 de agosto de 2026 Doctoralia confirmó por escrito
(caso MX-03213156) que no ofrece API pública, no admite integración externa
y tampoco permite exportar ni sincronizar la agenda. El asistente no puede
ver la disponibilidad real de ninguna manera.

Eso deja un problema sin solución técnica: si el asistente agenda a ciegas
sobre la agenda compartida, tarde o temprano choca con una cita tomada desde
el sitio web, desde Doctoralia o por la propia asistente.

**La solución es de diseño, no de código.** El consultorio bloquea ciertas
franjas en Doctoralia y las destina exclusivamente a WhatsApp. Ningún otro
canal puede tomarlas. Dentro de esas franjas, este sistema es la única
fuente de verdad, y por lo tanto el choque es imposible por construcción —
no se detecta, no puede ocurrir.

    Doctoralia          →  todo el horario MENOS las franjas
    Sitio web (widget)  →  todo el horario MENOS las franjas
    Asistente WhatsApp  →  únicamente las franjas

Fuera de las franjas el asistente no promete nada: toma el pedido como
solicitud y lo confirma una persona (ver `hay_franjas` y el router).

Cuando la cita queda agendada, la asistente la carga en Doctoralia desde el
panel. Es un paso manual de segundos, no la doble gestión de agendas que se
quería evitar.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, time, timedelta

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
from app.tiempo import a_local, combinar_local

log = logging.getLogger(__name__)

HORAS_MINIMAS_ANTICIPACION = 2


class FranjasReservadas(ProveedorAgenda):
    #: No se escribe en Doctoralia: no hay forma. La asistente carga la cita.
    escribe_en_doctoralia = False

    # ------------------------------------------------------------------

    async def huecos(self, sede_id: int, desde: datetime, hasta: datetime) -> list[Hueco]:
        with sesion() as s:
            sede = s.get(Sede, sede_id)
        if not sede or not sede.activa:
            return []

        ocupados = self._ocupado_sede(sede_id, desde, hasta)
        ocupados += self._ocupado_otras_sedes(sede_id, desde, hasta)

        minimo = datetime.utcnow() + timedelta(hours=HORAS_MINIMAS_ANTICIPACION)
        libres: list[Hueco] = []

        for inicio, fin in _rejilla_de_franjas(sede, desde, hasta):
            if inicio < minimo:
                continue
            if any(o.se_solapa_con(inicio, fin) for o in ocupados):
                continue
            libres.append(Hueco(inicio=inicio, fin=fin, sede_id=sede_id))

        return libres

    def _ocupado_sede(self, sede_id: int, desde: datetime, hasta: datetime) -> list[Hueco]:
        """
        Lo que este sistema ya agendó.

        Es todo lo que hay que mirar: dentro de las franjas, nadie más
        puede haber tomado nada.
        """
        with sesion() as s:
            citas = list(s.exec(
                select(Cita).where(
                    Cita.sede_id == sede_id,
                    Cita.inicio < hasta,
                    Cita.fin > desde,
                    Cita.estado.in_([  # type: ignore[attr-defined]
                        EstadoCita.SOLICITADA, EstadoCita.AGENDADA,
                        EstadoCita.CONFIRMADA,
                    ]),
                )
            ).all())
        return [
            Hueco(inicio=c.inicio, fin=c.fin, sede_id=c.sede_id, externo_id=str(c.id))
            for c in citas
        ]

    def _ocupado_otras_sedes(
        self, sede_id: int, desde: datetime, hasta: datetime
    ) -> list[Hueco]:
        """
        El doctor no puede estar en dos consultorios a la vez, y necesita
        tiempo para trasladarse entre ellos.
        """
        margen = timedelta(minutes=config.minutos_traslado_entre_sedes)
        with sesion() as s:
            otras = [
                x.id for x in s.exec(
                    select(Sede).where(Sede.id != sede_id, Sede.activa)  # type: ignore[arg-type]
                ).all()
            ]

        bloqueos: list[Hueco] = []
        for otra_id in otras:
            for h in self._ocupado_sede(otra_id, desde - margen, hasta + margen):  # type: ignore[arg-type]
                bloqueos.append(Hueco(
                    inicio=h.inicio - margen,
                    fin=h.fin + margen,
                    sede_id=sede_id,
                ))
        return bloqueos

    async def ocupado(self, desde: datetime, hasta: datetime) -> list[Hueco]:
        with sesion() as s:
            sedes = [x.id for x in s.exec(select(Sede)).all()]
        salida: list[Hueco] = []
        for sede_id in sedes:
            salida += self._ocupado_sede(sede_id, desde, hasta)  # type: ignore[arg-type]
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
        # Se re-verifica igual, aunque el choque externo sea imposible: dos
        # pacientes pueden estar eligiendo el mismo hueco a la vez.
        libres = await self.huecos(
            sede_id, inicio - timedelta(minutes=1), fin + timedelta(minutes=1)
        )
        if not any(h.inicio == inicio for h in libres):
            raise CupoYaOcupado("El horario se ocupó mientras el paciente elegía")

        # Dentro de una franja reservada la cita queda EN FIRME. Al paciente
        # se le confirma en el momento, sin «se lo confirmamos luego».
        return ResultadoReserva(
            ok=True,
            externo_id="",
            requiere_confirmacion_humana=False,
            motivo="Franja reservada. La asistente debe cargarla en Doctoralia.",
        )

    async def cancelar(self, externo_id: str) -> bool:
        # El cupo se libera acá al instante. En Doctoralia lo retira la
        # asistente, y el panel se lo avisa.
        return True

    async def reprogramar(
        self, externo_id: str, inicio: datetime, fin: datetime
    ) -> ResultadoReserva:
        return ResultadoReserva(
            ok=True,
            externo_id=externo_id,
            requiere_confirmacion_humana=False,
            motivo="La asistente debe moverla también en Doctoralia.",
        )


# ----------------------------------------------------------------------


def hay_franjas(sede_id: int) -> bool:
    """
    ¿Esta sede tiene franjas configuradas?

    Si no las tiene, el asistente no puede prometer ningún horario: toma el
    pedido como solicitud y lo confirma una persona.
    """
    with sesion() as s:
        sede = s.get(Sede, sede_id)
    if not sede:
        return False
    try:
        return bool(json.loads(sede.franjas_json or "[]"))
    except json.JSONDecodeError:
        return False


def _rejilla_de_franjas(
    sede: Sede, desde: datetime, hasta: datetime
) -> list[tuple[datetime, datetime]]:
    """
    Los espacios de las franjas reservadas, en UTC.

    Las franjas se definen en hora del consultorio, así que se arman en
    local y recién ahí se convierten.
    """
    try:
        franjas = json.loads(sede.franjas_json or "[]")
    except json.JSONDecodeError:
        log.error("franjas_json inválido en la sede %s", sede.id)
        return []

    if not franjas:
        return []

    duracion = timedelta(minutes=sede.duracion_cita_min or 30)
    salida: list[tuple[datetime, datetime]] = []

    dia = a_local(desde).date() - timedelta(days=1)
    ultimo = a_local(hasta).date() + timedelta(days=1)

    while dia <= ultimo:
        for f in franjas:
            if f.get("dia") != dia.weekday():
                continue
            abre = combinar_local(dia, time.fromisoformat(f["desde"]))
            cierra = combinar_local(dia, time.fromisoformat(f["hasta"]))
            t = abre
            while t + duracion <= cierra:
                if desde <= t <= hasta:
                    salida.append((t, t + duracion))
                t += duracion
        dia += timedelta(days=1)

    return sorted(salida)


def citas_por_cargar() -> list[Cita]:
    """
    Las que la asistente todavía no pasó a Doctoralia.

    Es su lista de pendientes del día, y la razón por la que este flujo no
    se convierte en doble gestión de agendas: mientras algo esté acá, se ve.
    """
    with sesion() as s:
        return list(s.exec(
            select(Cita)
            .where(
                Cita.cargada_en_doctoralia == False,  # noqa: E712
                Cita.estado.in_([  # type: ignore[attr-defined]
                    EstadoCita.AGENDADA, EstadoCita.CONFIRMADA,
                    EstadoCita.SOLICITADA,
                ]),
                Cita.inicio >= datetime.utcnow(),
            )
            .order_by(Cita.inicio)  # type: ignore[arg-type]
        ).all())
