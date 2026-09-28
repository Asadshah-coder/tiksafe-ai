"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "TikSave AI"
    environment: str = "development"
    version: str = "1.0.0"

    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "*"

    temp_dir: Path = Path("temp")
    temp_file_ttl_seconds: int = 3600
    max_upload_mb: int = 200
    max_download_mb: int = 500

    request_timeout_seconds: int = 60
    extraction_timeout_seconds: int = 45
    ffmpeg_timeout_seconds: int = 600
    rate_limit_per_minute: int = 60

    openai_api_key: str = Field(
        default="", validation_alias=AliasChoices("OPENAI_API_KEY", "TIKSAFE_OPENAI_API_KEY")
    )
    openai_model: str = Field(
        default="gpt-4o-mini", validation_alias=AliasChoices("OPENAI_MODEL", "TIKSAFE_OPENAI_MODEL")
    )
    gemini_api_key: str = Field(
        default="", validation_alias=AliasChoices("GEMINI_API_KEY", "TIKSAFE_GEMINI_API_KEY")
    )
    gemini_model: str = Field(
        default="gemini-2.0-flash",
        validation_alias=AliasChoices("GEMINI_MODEL", "TIKSAFE_GEMINI_MODEL"),
    )

    whisper_model: str = Field(
        default="small", validation_alias=AliasChoices("WHISPER_MODEL", "TIKSAFE_WHISPER_MODEL")
    )
    log_level: str = "INFO"

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
