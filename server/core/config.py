"""
server/core/config.py
=====================
Configuración central de la aplicación usando Pydantic Settings.

Por qué Pydantic Settings:
  - Lee automáticamente desde variables de entorno Y desde archivos .env.
  - Valida tipos en tiempo de arranque (falla rápido si algo está mal).
  - Centraliza toda la config en un solo lugar: no hay valores mágicos
    dispersos por el código.

Uso en cualquier módulo:
    from server.core.config import settings
    print(settings.SERVER_PORT)
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from server.db.enums import ModeloIA


class Settings(BaseSettings):
    # --- Servidor ---
    SERVER_HOST: str = "0.0.0.0"
    SERVER_PORT: int = 8000
    SECRET_KEY:  str = "CAMBIA_ESTO_EN_PRODUCCION"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 horas (turno escolar completo)

    # --- Base de Datos ---
    DATABASE_URL: str = "sqlite:///./server/data/asistencia.db"

    # --- Telegram ---
    TELEGRAM_BOT_TOKEN:       str = ""
    TELEGRAM_CHAT_ID_PORTERIA: str = ""
    TELEGRAM_CHAT_ID_ADMIN:    str = ""

    # --- WhatsApp ---
    WHATSAPP_ENABLED: bool = False

    # --- Reconocimiento Facial ---
    DEFAULT_RECOGNITION_MODEL: ModeloIA = ModeloIA.HOG
    FACE_TOLERANCE: float = 0.6
    PHOTOS_DIR: str = "./server/data/photos"      # Fotos de alumnos
    ENCODINGS_DIR: str = "./server/data/encodings" # Archivos .pkl

    # --- Regla de Re-escaneo ---
    RESCAN_THRESHOLD_SECONDS: int = 300  # 5 minutos

    # Pydantic lee desde archivo .env automáticamente
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )


# Instancia global — importar esta, no la clase
settings = Settings()
