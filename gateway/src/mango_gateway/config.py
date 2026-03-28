"""Mango Gateway configuration — type-safe settings loaded from gateway.toml."""

from __future__ import annotations

from functools import lru_cache
from typing import Tuple, Type

from pydantic import BaseModel
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource


# ── Sub-section models ───────────────────────────────────────────────


class ServerConfig(BaseModel):
    port: int = 18900
    host: str = "0.0.0.0"


class RuntimeConfig(BaseModel):
    url: str = "http://localhost:18800"
    timeout: int = 30


class SessionConfig(BaseModel):
    timeout_hours: int = 24
    cleanup_interval_minutes: int = 60


class GatewayConfig(BaseModel):
    max_wait_timeout: int = 1800


class DatabaseConfig(BaseModel):
    path: str = "./data/gateway.db"


# ── Root settings ────────────────────────────────────────────────────


class Settings(BaseSettings):
    """Root settings — loads from gateway.toml, falls back to defaults."""

    server: ServerConfig = ServerConfig()
    runtime: RuntimeConfig = RuntimeConfig()
    session: SessionConfig = SessionConfig()
    gateway: GatewayConfig = GatewayConfig()
    database: DatabaseConfig = DatabaseConfig()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        from pydantic_settings import TomlConfigSettingsSource

        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
            TomlConfigSettingsSource(settings_cls, toml_file="gateway.toml"),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton of the application settings."""
    return Settings()
