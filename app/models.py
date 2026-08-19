"""
Modelo de datos.

Principio rector: se guarda el mínimo indispensable para operar.
NO se almacena información clínica — ni síntomas, ni diagnósticos, ni
estudios. Lo que el paciente escriba de índole clínica se deriva a una
persona y no se procesa (ver app/brain/safety.py).
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


def ahora() -> datetime:
    return datetime.utcnow()


# ============================================================
#  Enumeraciones
# ============================================================

class ModoAsistente(str, Enum):
    BASICO = "basico"
    HIBRIDO = "hibrido"
    IA = "ia"


class EstadoConversacion(str, Enum):
    BOT = "bot"                    # el asistente responde
    REQUIERE_ATENCION = "atencion"  # esperando a una persona
    HUMANO = "humano"              # una persona tomó el control
    RESUELTA = "resuelta"


class MotivoEscalado(str, Enum):
    POSIBLE_URGENCIA = "posible_urgencia"
    CONTENIDO_CLINICO = "contenido_clinico"
    PIDIO_DOCTOR = "pidio_doctor"
    MOLESTIA = "molestia"
    NO_COMPRENDIDO = "no_comprendido"
    ESTANCADA = "estancada"
    FACTURACION = "facturacion"


class Intencion(str, Enum):
    CITA = "cita"
    COSTOS = "costos"
    POSTOPERATORIO = "postoperatorio"
    URGENCIA = "urgencia"
    UBICACION = "ubicacion"
    INFORMACION = "informacion"
    FACTURACION = "facturacion"
    REFERENCIA = "referencia"
    CANCELAR = "cancelar"
    CONFIRMAR = "confirmar"
    SALUDO = "saludo"
    DESCONOCIDA = "desconocida"


class EstadoCita(str, Enum):
    SOLICITADA = "solicitada"      # Plan B: espera validación de la asistente
    AGENDADA = "agendada"
    CONFIRMADA = "confirmada"
    CANCELADA = "cancelada"
    REPROGRAMADA = "reprogramada"
    ASISTIO = "asistio"
    NO_ASISTIO = "no_asistio"


class RolUsuario(str, Enum):
    ADMIN = "admin"                # el doctor
    ASISTENTE = "asistente"


class Remitente(str, Enum):
    PACIENTE = "paciente"
    BOT = "bot"
    HUMANO = "humano"
    SISTEMA = "sistema"            # notas internas, no se envían a WhatsApp


# ============================================================
#  Tablas
# ============================================================

class Sede(SQLModel, table=True):
    """Cada consultorio. Se ofrece al paciente solo si activa=True."""

    id: Optional[int] = Field(default=None, primary_key=True)
    nombre: str
    direccion: str
    referencias: str = ""
    mapa_url: str = ""
    telefono: str = ""
    precio_valoracion: Optional[float] = None
    convenios: str = ""            # aseguradoras, separadas por coma
    horarios: str = ""             # texto legible: "Lun, mié y vie 9:00-14:00"
    # Versión que lee la máquina. Lunes = 0.
    # [{"dia": 0, "desde": "09:00", "hasta": "14:00"}, ...]
    horario_json: str = "[]"
    duracion_cita_min: int = 30

    # Franjas que el consultorio bloqueó en Doctoralia y destinó
    # exclusivamente a WhatsApp. Mismo formato que horario_json.
    #
    # Como ningún otro canal puede tomarlas, dentro de estas franjas no
    # existe posibilidad de choque: el asistente agenda en firme. Es la
    # respuesta al hecho de que Doctoralia no permite leer la agenda.
    franjas_json: str = "[]"
    ical_url: str = ""             # Plan B: feed de esa sede
    doctoralia_recurso_id: str = ""  # Plan A: identificador en Doctoralia
    # Plan C: la agenda de Google de esta sede. Vacío = se usa la del
    # profesional principal. Ver app/agenda/google_calendar.py.
    calendario_google_id: str = ""
    activa: bool = True
    orden: int = 0

    citas: list["Cita"] = Relationship(back_populates="sede")


class Profesional(SQLModel, table=True):
    """
    Quién atiende. Hoy es uno solo; la tabla existe para que sumar otro sea
    agregar una fila y no rehacer el sistema.

    Cubre los dos casos que planteó el consultorio:

      * **El Dr. Padilla** (`principal=True`): el asistente le agenda.
      * **Otro profesional que atiende por su propio número** — la agenda de
        su esposa, un colega. Con `deriva=True` el asistente NO le agenda:
        reconoce que el paciente lo busca a él y le pasa el número correcto.
        Es lo que evita que el número del doctor termine atendiendo dos
        agendas distintas.

    `calendario_google_id` es la agenda propia de cada quien, para el día que
    se deje Doctoralia. Ver app/agenda/google_calendar.py.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    nombre: str
    titulo: str = "Dr."                # Dr. | Dra. | Lic.
    especialidad: str = ""
    principal: bool = False            # el titular del número de WhatsApp

    # Derivación a otro número
    deriva: bool = False
    telefono_whatsapp: str = ""        # el número que se le pasa al paciente
    # Cómo lo nombran los pacientes, separado por coma: "doctora, su esposa,
    # dra ramirez". Es lo que dispara el reconocimiento.
    palabras_clave: str = ""
    mensaje_derivacion: str = ""       # si se quiere un texto propio

    calendario_google_id: str = ""
    activo: bool = True
    orden: int = 0

    @property
    def nombre_completo(self) -> str:
        return f"{self.titulo} {self.nombre}".strip()


class Paciente(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    telefono: str = Field(index=True, unique=True)
    nombre: str = ""
    ciudad: str = ""
    motivo_consulta: str = ""      # categoría administrativa, NO dato clínico
    fuente: str = ""               # google, facebook, doctoralia, web, recomendacion
    consentimiento_en: Optional[datetime] = None
    # El paciente pidió no recibir más mensajes del consultorio. Se le
    # promete en el primer contacto («responda BAJA»), así que tiene que
    # cumplirse: desde acá no sale ningún recordatorio ni plantilla.
    baja_en: Optional[datetime] = None
    sede_preferida_id: Optional[int] = Field(default=None, foreign_key="sede.id")
    ultima_interaccion: datetime = Field(default_factory=ahora)
    creado_en: datetime = Field(default_factory=ahora)

    conversaciones: list["Conversacion"] = Relationship(back_populates="paciente")
    citas: list["Cita"] = Relationship(back_populates="paciente")

    @property
    def es_conocido(self) -> bool:
        return bool(self.nombre)


class Conversacion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    paciente_id: int = Field(foreign_key="paciente.id", index=True)
    estado: EstadoConversacion = Field(default=EstadoConversacion.BOT, index=True)
    intencion: Intencion = Intencion.DESCONOCIDA
    motivo_escalado: Optional[MotivoEscalado] = None
    sede_id: Optional[int] = Field(default=None, foreign_key="sede.id")
    paso: str = ""                 # paso actual del flujo
    contexto: str = "{}"           # JSON con lo que se lleva reunido
    tomada_por_id: Optional[int] = Field(default=None, foreign_key="usuario.id")
    tomada_en: Optional[datetime] = None
    intentos_fallidos: int = 0
    abierta_en: datetime = Field(default_factory=ahora)
    ultima_actividad: datetime = Field(default_factory=ahora)
    cerrada_en: Optional[datetime] = None
    convirtio: bool = False        # terminó en cita agendada
    motivo_perdida: str = ""

    paciente: Optional[Paciente] = Relationship(back_populates="conversaciones")
    mensajes: list["Mensaje"] = Relationship(back_populates="conversacion")


class Mensaje(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    conversacion_id: int = Field(foreign_key="conversacion.id", index=True)
    remitente: Remitente
    texto: str
    wa_message_id: str = ""
    usuario_id: Optional[int] = Field(default=None, foreign_key="usuario.id")
    # Cuando el paciente envía imagen/audio NO se descarga ni se guarda:
    # se registra únicamente que llegó, y se deriva a una persona.
    tipo_adjunto: str = ""
    generado_por_ia: bool = False
    tokens_entrada: int = 0
    tokens_salida: int = 0
    costo_usd: float = 0.0
    enviado_en: datetime = Field(default_factory=ahora, index=True)

    conversacion: Optional[Conversacion] = Relationship(back_populates="mensajes")


class Cita(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    paciente_id: int = Field(foreign_key="paciente.id", index=True)
    sede_id: int = Field(foreign_key="sede.id", index=True)
    # Con un solo profesional queda en None y nada cambia. Existe para que
    # sumar un segundo médico no obligue a migrar las citas ya cargadas.
    profesional_id: Optional[int] = Field(default=None, foreign_key="profesional.id")
    inicio: datetime = Field(index=True)
    fin: datetime
    estado: EstadoCita = Field(default=EstadoCita.SOLICITADA, index=True)
    tipo: str = "valoracion"       # valoracion | control | postoperatorio
    externo_id: str = ""           # id en Doctoralia, si lo hay
    recordatorio_enviado_en: Optional[datetime] = None
    confirmada_por_paciente_en: Optional[datetime] = None
    # Doctoralia no admite integración: la asistente carga la cita a mano.
    # Mientras esto sea False, la cita aparece en su lista de pendientes.
    cargada_en_doctoralia: bool = False
    cargada_en_doctoralia_en: Optional[datetime] = None
    creada_en: datetime = Field(default_factory=ahora)
    creada_por: str = "bot"        # bot | humano | doctoralia
    notas: str = ""

    paciente: Optional[Paciente] = Relationship(back_populates="citas")
    sede: Optional[Sede] = Relationship(back_populates="citas")


class Usuario(SQLModel, table=True):
    """El doctor y sus asistentes. Cada persona con su propia cuenta."""

    id: Optional[int] = Field(default=None, primary_key=True)
    nombre: str
    correo: str = Field(index=True, unique=True)
    hash_clave: str
    rol: RolUsuario = RolUsuario.ASISTENTE
    telegram_chat_id: str = ""
    activo: bool = True
    ultimo_acceso: Optional[datetime] = None
    creado_en: datetime = Field(default_factory=ahora)


class SuscripcionPush(SQLModel, table=True):
    """
    Un navegador que aceptó recibir avisos de intervención humana.

    Cada persona puede tener varias —el celular y la computadora— y cada una
    es una suscripción distinta. Guardamos lo que el navegador nos entrega:
    el endpoint del servicio de envío y las dos claves con las que se cifra
    el mensaje. No hay nada del paciente aquí.

    Se borra sola: si el servicio de envío responde que el endpoint ya no
    existe (el usuario desinstaló la app o revocó el permiso), la fila se
    elimina en el siguiente envío. Ver app/push.py.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuario.id", index=True)
    endpoint: str = Field(index=True, unique=True)
    clave_p256dh: str
    clave_auth: str
    agente: str = ""               # navegador declarado, para reconocerla
    creada_en: datetime = Field(default_factory=ahora)
    ultimo_envio_en: Optional[datetime] = None


class RegistroAuditoria(SQLModel, table=True):
    """Quién hizo qué y cuándo. Requisito del proyecto, no opcional."""

    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: Optional[int] = Field(default=None, foreign_key="usuario.id")
    actor: str = "sistema"         # sistema | bot | correo del usuario
    accion: str = Field(index=True)
    entidad: str = ""
    entidad_id: Optional[int] = None
    detalle: str = ""
    ocurrido_en: datetime = Field(default_factory=ahora, index=True)


class Ajuste(SQLModel, table=True):
    """Configuración editable desde el panel, sin tocar código."""

    clave: str = Field(primary_key=True)
    valor: str
    actualizado_en: datetime = Field(default_factory=ahora)


class RespuestaFrecuente(SQLModel, table=True):
    """Contenido del consultorio, editable por el doctor desde el panel."""

    id: Optional[int] = Field(default=None, primary_key=True)
    intencion: Intencion = Field(index=True)
    disparadores: str = ""         # palabras clave, separadas por coma
    respuesta: str
    sede_id: Optional[int] = Field(default=None, foreign_key="sede.id")
    activa: bool = True
    veces_usada: int = 0


class ConsumoIA(SQLModel, table=True):
    """Gasto de IA por mes, para el tope duro y el medidor del panel."""

    id: Optional[int] = Field(default=None, primary_key=True)
    periodo: str = Field(index=True, unique=True)  # "2026-08"
    tokens_entrada: int = 0
    tokens_salida: int = 0
    costo_usd: float = 0.0
    llamadas: int = 0
    tope_alcanzado_en: Optional[datetime] = None
