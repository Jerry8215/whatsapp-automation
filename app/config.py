"""Configuración leída del entorno. Nada sensible vive en el código."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    entorno: Literal["desarrollo", "produccion"] = "desarrollo"
    zona_horaria: str = "America/Mexico_City"

    database_url: str = "sqlite:///./datos/consultorio.db"

    # --- WhatsApp Cloud API ---
    wa_phone_number_id: str = ""
    wa_business_account_id: str = ""
    wa_token: str = ""
    wa_app_secret: str = ""
    wa_verify_token: str = "cambiar-esto"
    wa_api_version: str = "v21.0"

    # --- OpenAI ---
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    ia_limite_mensual_usd: float = 15.00

    modo_asistente: Literal["basico", "hibrido", "ia"] = "hibrido"

    # --- Agenda ---
    agenda_proveedor: Literal["api", "calendar", "franjas", "google"] = "franjas"
    doctoralia_api_base: str = ""
    doctoralia_api_key: str = ""
    doctoralia_ical_urls: str = ""
    minutos_traslado_entre_sedes: int = 45

    # Google Calendar. Se conecta con una cuenta de servicio: el consultorio
    # comparte su agenda con ese correo y le da permiso de hacer cambios. No
    # hay que iniciar sesión con la cuenta personal del doctor ni renovar
    # nada a mano.
    google_cuenta_servicio_json: str = ""   # el JSON completo, o una ruta a él
    google_calendario_id: str = ""          # agenda por defecto
    google_zona_horaria: str = ""           # vacío → la del consultorio

    # --- Avisos ---
    telegram_bot_token: str = ""
    telegram_chat_ids: str = ""
    smtp_host: str = ""
    smtp_puerto: int = 587
    smtp_usuario: str = ""
    smtp_clave: str = ""
    correo_avisos: str = ""

    # Avisos push al celular. Sin claves configuradas el panel no ofrece la
    # opción y los avisos siguen saliendo por Telegram y correo.
    # Se generan una sola vez con: python -m scripts.generar_claves_vapid
    vapid_clave_publica: str = ""
    vapid_clave_privada: str = ""
    vapid_contacto: str = ""       # mailto:... exigido por los navegadores

    # --- Panel ---
    panel_secreto: str = "cambiar-esto"
    panel_url_publica: str = "http://localhost:8000"

    retencion_conversaciones_dias: int = 365

    @property
    def url_base_datos(self) -> str:
        """
        La URL de conexión, normalizada.

        Railway, Render y Heroku inyectan `postgresql://...` (o el antiguo
        `postgres://`). Con esa forma SQLAlchemy busca psycopg2, que no está
        instalado: este proyecto usa psycopg 3. Se reescribe el esquema para
        que el despliegue funcione sin tener que tocar nada a mano.
        """
        url = self.database_url
        for viejo in ("postgresql://", "postgres://"):
            if url.startswith(viejo):
                return "postgresql+psycopg://" + url[len(viejo):]
        return url

    @property
    def wa_api_base(self) -> str:
        return f"https://graph.facebook.com/{self.wa_api_version}"

    @property
    def ical_urls(self) -> list[str]:
        return [u.strip() for u in self.doctoralia_ical_urls.split(",") if u.strip()]

    @property
    def chats_telegram(self) -> list[str]:
        return [c.strip() for c in self.telegram_chat_ids.split(",") if c.strip()]

    @property
    def correos_aviso(self) -> list[str]:
        return [c.strip() for c in self.correo_avisos.split(",") if c.strip()]

    @property
    def push_configurado(self) -> bool:
        return bool(self.vapid_clave_publica and self.vapid_clave_privada)

    @property
    def google_configurado(self) -> bool:
        return bool(self.google_cuenta_servicio_json)

    @property
    def zona_google(self) -> str:
        return self.google_zona_horaria or self.zona_horaria


@lru_cache
def obtener_config() -> Config:
    return Config()


config = obtener_config()
