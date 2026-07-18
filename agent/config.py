"""Mango configuration — type-safe settings loaded from overseer.toml."""

from __future__ import annotations

import os
from functools import lru_cache

from typing import Any, Tuple, Type

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict, PydanticBaseSettingsSource


# ── Sub-section models ───────────────────────────────────────────────


class ServerConfig(BaseModel):
    port: int = 18800


class CCConnectConfig(BaseModel):
    """Connection details for cc-connect's Bridge WebSocket endpoint."""

    url: str = "ws://localhost:9810/bridge/ws"
    token: str = Field(default_factory=lambda: os.environ.get("CC_CONNECT_BRIDGE_TOKEN", ""))
    platform: str = "issue-overseer"
    timeout: int = 1800


class DatabaseConfig(BaseModel):
    path: str = "./data/mango.db"


# ── Root settings ────────────────────────────────────────────────────


class Settings(BaseSettings):
    """Root settings — loads from overseer.toml, falls back to defaults."""

    model_config = SettingsConfigDict(
        toml_file="overseer.toml",
    )

    server: ServerConfig = ServerConfig()
    cc_connect: CCConnectConfig = CCConnectConfig()
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
            TomlConfigSettingsSource(settings_cls),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton of the application settings."""
    return Settings()
