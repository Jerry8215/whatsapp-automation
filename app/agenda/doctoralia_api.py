"""
Plan A — integración directa con la API de Doctoralia (Docplanner).

ESTADO: pendiente de que Docplanner habilite el acceso para la cuenta del
Dr. Padilla. La solicitud se envió el día 1 del proyecto.

Los nombres de los endpoints y la forma de las respuestas están puestos
según el patrón habitual de la plataforma y DEBEN confirmarse contra la
documentación que entregue Docplanner junto con las credenciales. Hasta
entonces el sistema opera con el Plan B (`calendar_sync`), y el cambio es
una variable de entorno: AGENDA_PROVEEDOR=api
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from app.agenda.base import (
    CupoYaOcupado,
    ErrorAgenda,
    Hueco,
    ProveedorAgenda,
    ResultadoReserva,
)
from app.config import config

log = logging.getLogger(__name__)

TIEMPO_ESPERA = 20.0


class DoctoraliaAPI(ProveedorAgenda):
    escribe_en_la_agenda = True

    def __init__(self) -> None:
        if not config.doctoralia_api_key:
            raise ErrorAgenda(
                "Falta DOCTORALIA_API_KEY. Mientras Docplanner no habilite el "
                "acceso, use AGENDA_PROVEEDOR=calendar (Plan B)."
            )
        self._base = config.doctoralia_api_base.rstrip("/")

    def _cabeceras(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {config.doctoralia_api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _pedir(self, metodo: str, ruta: str, **kw) -> dict:
        async with httpx.AsyncClient(timeout=TIEMPO_ESPERA) as c:
            r = await c.request(
                metodo, f"{self._base}{ruta}", headers=self._cabeceras(), **kw
            )
        if r.status_code == 409:
            raise CupoYaOcupado("El horario ya fue tomado")
        if r.status_code >= 400:
            log.error("Doctoralia %s %s → %s: %s", metodo, ruta, r.status_code, r.text)
            raise ErrorAgenda(f"{r.status_code}: {r.text}")
        return r.json() if r.content else {}

    # ------------------------------------------------------------------

    async def huecos(self, sede_id: int, desde: datetime, hasta: datetime) -> list[Hueco]:
        datos = await self._pedir(
            "GET",
            "/slots",
            params={
                "facility_id": _recurso(sede_id),
                "start": desde.isoformat(),
                "end": hasta.isoformat(),
                "status": "available",
            },
        )
        return [
            Hueco(
                inicio=datetime.fromisoformat(s["start"]),
                fin=datetime.fromisoformat(s["end"]),
                sede_id=sede_id,
                externo_id=str(s.get("id", "")),
            )
            for s in datos.get("data", [])
        ]

    async def ocupado(self, desde: datetime, hasta: datetime) -> list[Hueco]:
        datos = await self._pedir(
            "GET",
            "/bookings",
            params={"start": desde.isoformat(), "end": hasta.isoformat()},
        )
        salida: list[Hueco] = []
        for b in datos.get("data", []):
            salida.append(Hueco(
                inicio=datetime.fromisoformat(b["start"]),
                fin=datetime.fromisoformat(b["end"]),
                sede_id=_sede_de(b.get("facility_id", "")),
                externo_id=str(b.get("id", "")),
            ))
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
        # Re-verificación en el instante de confirmar. Entre que se
        # ofrecieron los horarios y el paciente eligió pudo entrar una
        # reserva por el widget del sitio web o por la propia Doctoralia.
        libres = await self.huecos(sede_id, inicio, fin)
        if not any(h.inicio == inicio for h in libres):
            raise CupoYaOcupado("El horario se ocupó mientras el paciente elegía")

        datos = await self._pedir(
            "POST",
            "/bookings",
            json={
                "facility_id": _recurso(sede_id),
                "start": inicio.isoformat(),
                "end": fin.isoformat(),
                "patient": {"name": nombre_paciente, "phone": telefono},
                "note": motivo,
                "source": "whatsapp",
            },
        )
        return ResultadoReserva(ok=True, externo_id=str(datos.get("id", "")))

    async def cancelar(self, externo_id: str) -> bool:
        await self._pedir("DELETE", f"/bookings/{externo_id}")
        return True

    async def reprogramar(
        self, externo_id: str, inicio: datetime, fin: datetime
    ) -> ResultadoReserva:
        datos = await self._pedir(
            "PATCH",
            f"/bookings/{externo_id}",
            json={"start": inicio.isoformat(), "end": fin.isoformat()},
        )
        return ResultadoReserva(ok=True, externo_id=str(datos.get("id", externo_id)))

    async def bloquear(
        self, sede_id: int, inicio: datetime, fin: datetime, motivo: str
    ) -> str:
        """
        Bloquea un espacio en la agenda del doctor.

        Necesario si más adelante se suma un segundo médico: al ocuparse un
        horario en el calendario del otro profesional, hay que bloquearlo
        aquí. Esto SOLO es posible con el Plan A: los feeds iCal del Plan B
        son de solo lectura.
        """
        datos = await self._pedir(
            "POST",
            "/blocks",
            json={
                "facility_id": _recurso(sede_id),
                "start": inicio.isoformat(),
                "end": fin.isoformat(),
                "reason": motivo,
            },
        )
        return str(datos.get("id", ""))


# ----------------------------------------------------------------------
#  Traducción entre nuestras sedes y los recursos de Doctoralia
# ----------------------------------------------------------------------

def _recurso(sede_id: int) -> str:
    from app.db import sesion
    from app.models import Sede

    with sesion() as s:
        sede = s.get(Sede, sede_id)
        if not sede or not sede.doctoralia_recurso_id:
            raise ErrorAgenda(f"La sede {sede_id} no tiene recurso de Doctoralia asignado")
        return sede.doctoralia_recurso_id


def _sede_de(recurso_id: str) -> int:
    from sqlmodel import select

    from app.db import sesion
    from app.models import Sede

    with sesion() as s:
        sede = s.exec(
            select(Sede).where(Sede.doctoralia_recurso_id == str(recurso_id))
        ).first()
        return sede.id if sede and sede.id else 0
