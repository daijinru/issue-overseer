"""Mango configuration — type-safe settings loaded from overseer.toml."""

from __future__ import annotations

from functools import lru_cache

from typing import Any, Tuple, Type

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict, PydanticBaseSettingsSource


# ── Sub-section models ───────────────────────────────────────────────


class ServerConfig(BaseModel):
    port: int = 18800


class AgentConfig(BaseModel):
    max_turns: int = 3
    task_timeout: int = 1800


class OpenCodeConfig(BaseModel):
    url: str = "http://localhost:4096"
    timeout: int = 300


class ProjectConfig(BaseModel):
    repo_path: str = "."
    default_branch: str = "main"


class DatabaseConfig(BaseModel):
    path: str = "./data/mango.db"


class SecurityConfig(BaseModel):
    allowed_commands: list[str] = [
        "git", "python", "pytest", "pip", "uv",
        "cat", "ls", "find", "grep", "head", "tail",
        "mkdir", "cp", "mv", "echo",
    ]
    blocked_patterns: list[str] = [
        "rm -rf /", "rm -rf ~", "sudo",
        "curl | bash", "wget | sh", "chmod 777",
    ]


class ContextConfig(BaseModel):
    max_git_diff_lines: int = 2000
    max_result_chars: int = 5000


# ── Root settings ────────────────────────────────────────────────────


class Settings(BaseSettings):
    """Root settings — loads from overseer.toml, falls back to defaults."""

    model_config = SettingsConfigDict(
        toml_file="overseer.toml",
    )

    server: ServerConfig = ServerConfig()
    agent: AgentConfig = AgentConfig()
    opencode: OpenCodeConfig = OpenCodeConfig()
    project: ProjectConfig = ProjectConfig()
    database: DatabaseConfig = DatabaseConfig()
    security: SecurityConfig = SecurityConfig()
    context: ContextConfig = ContextConfig()

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
