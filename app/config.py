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
    agenda_proveedor: Literal["api", "calendar", "franjas"] = "franjas"
    doctoralia_api_base: str = ""
    doctoralia_api_key: str = ""
    doctoralia_ical_urls: str = ""
    minutos_traslado_entre_sedes: int = 45

    # --- Avisos ---
    telegram_bot_token: str = ""
    telegram_chat_ids: str = ""
    smtp_host: str = ""
    smtp_puerto: int = 587
    smtp_usuario: str = ""
    smtp_clave: str = ""
    correo_avisos: str = ""

    # --- Panel ---
    panel_secreto: str = "cambiar-esto"
    panel_url_publica: str = "http://localhost:8000"

    retencion_conversaciones_dias: int = 365

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


@lru_cache
def obtener_config() -> Config:
    return Config()


config = obtener_config()
