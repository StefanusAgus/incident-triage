"""Environment-backed application settings."""

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.constants import (
    DEFAULT_DATABASE_URL,
    DEFAULT_DATA_PATH,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_TIMEOUT_SECONDS,
    DEFAULT_PORT,
    MAX_LLM_TIMEOUT_SECONDS,
    MAX_PORT,
    MIN_LLM_TIMEOUT,
    MIN_MODEL_NAME_LENGTH,
    MIN_PORT,
)


class Settings(BaseSettings):
    # BaseSettings consumes this configuration when Settings() is constructed.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_api_key: SecretStr | None = None
    llm_model: str = Field(default=DEFAULT_LLM_MODEL, min_length=MIN_MODEL_NAME_LENGTH)
    llm_timeout_seconds: float = Field(
        default=DEFAULT_LLM_TIMEOUT_SECONDS,
        gt=MIN_LLM_TIMEOUT,
        le=MAX_LLM_TIMEOUT_SECONDS,
    )
    database_url: str = DEFAULT_DATABASE_URL
    data_path: Path = Path(DEFAULT_DATA_PATH)
    port: int = Field(default=DEFAULT_PORT, ge=MIN_PORT, le=MAX_PORT)
