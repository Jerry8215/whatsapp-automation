"""
Interfaz de agenda.

Existe porque el acceso a la API de Doctoralia depende de que Docplanner
lo autorice, y eso no está garantizado. El resto del sistema habla con
esta interfaz y no le importa cuál de los dos caminos esté activo:

  Plan A — `DoctoraliaAPI`        descartado: Doctoralia no tiene API
  Plan B — `SincroniaCalendario`  sin uso: tampoco exporta la agenda
  Plan C — `AgendaGoogle`         lectura y escritura reales, listo y en pausa
  Hoy    — `FranjasReservadas`    el que está activo

Cambiar de uno a otro es un interruptor en el panel, no una reescritura.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Hueco:
    """Un espacio libre en una sede concreta."""

    inicio: datetime
    fin: datetime
    sede_id: int
    externo_id: str = ""

    def se_solapa_con(self, otro_inicio: datetime, otro_fin: datetime) -> bool:
        return self.inicio < otro_fin and otro_inicio < self.fin


@dataclass(frozen=True)
class ResultadoReserva:
    ok: bool
    externo_id: str = ""
    requiere_confirmacion_humana: bool = False
    motivo: str = ""


class ErrorAgenda(RuntimeError):
    pass


class CupoYaOcupado(ErrorAgenda):
    """El hueco se ocupó entre que se ofreció y que se confirmó."""


class ProveedorAgenda(ABC):
    """Contrato que cumplen tanto el Plan A como el Plan B."""

    #: True solo si el proveedor puede ESCRIBIR en la agenda de verdad.
    #:
    #: Con las franjas es False: Doctoralia no admite escritura de ninguna
    #: forma, así que la cita la copia una persona y aparece en la lista de
    #: pendientes del panel. Con Google es True, y no queda paso manual.
    escribe_en_la_agenda: bool = False

    @abstractmethod
    async def huecos(
        self, sede_id: int, desde: datetime, hasta: datetime
    ) -> list[Hueco]:
        """Espacios libres reales de esa sede."""

    @abstractmethod
    async def ocupado(self, desde: datetime, hasta: datetime) -> list[Hueco]:
        """
        Todo lo ocupado en ese rango, en TODAS las sedes.

        Se usa para el bloqueo cruzado: el doctor no puede estar en dos
        consultorios a la vez, y hay que respetar el traslado entre ellos.
        """

    @abstractmethod
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
        """Reserva. Debe re-verificar disponibilidad antes de confirmar."""

    @abstractmethod
    async def cancelar(self, externo_id: str) -> bool: ...

    @abstractmethod
    async def reprogramar(
        self, externo_id: str, inicio: datetime, fin: datetime
    ) -> ResultadoReserva: ...
