"""Tests for config loading."""

from __future__ import annotations

from agent.config import CCConnectConfig
from agent.config import Settings


def test_default_config_loads():
    """Settings can be instantiated with all defaults (no TOML file)."""
    settings = Settings()
    assert settings.server.port == 18800
    assert settings.cc_connect.url == "ws://localhost:9810/bridge/ws"
    assert settings.cc_connect.timeout == 1800
    assert settings.database.path == "./data/mango.db"


def test_cc_connect_token_reads_environment_at_instantiation(monkeypatch):
    monkeypatch.setenv("CC_CONNECT_BRIDGE_TOKEN", "bridge-token")

    assert CCConnectConfig().token == "bridge-token"
