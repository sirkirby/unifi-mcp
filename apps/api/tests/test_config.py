"""Config loader tests."""

from pathlib import Path

import pytest
from unifi_api.config import ApiConfig, load_config


def test_load_default_config_yaml(tmp_path: Path) -> None:
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        "http:\n  host: 0.0.0.0\n  port: 8080\nlogging:\n  level: INFO\ndb:\n  path: /var/lib/unifi-api/state.db\n"
    )
    cfg = load_config(yaml_path)
    assert cfg.http.host == "0.0.0.0"
    assert cfg.http.port == 8080
    assert cfg.logging.level == "INFO"
    assert cfg.db.path == "/var/lib/unifi-api/state.db"


def test_env_override_takes_precedence(tmp_path: Path, monkeypatch) -> None:
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text("http:\n  host: 127.0.0.1\n  port: 8080\n")
    monkeypatch.setenv("UNIFI_API_HTTP_PORT", "9000")
    cfg = load_config(yaml_path)
    assert cfg.http.port == 9000


def test_db_key_must_come_from_env(monkeypatch) -> None:
    monkeypatch.delenv("UNIFI_API_DB_KEY", raising=False)
    with pytest.raises(RuntimeError, match="UNIFI_API_DB_KEY"):
        ApiConfig.read_db_key()
    monkeypatch.setenv("UNIFI_API_DB_KEY", "test-key-not-for-prod")
    assert ApiConfig.read_db_key() == "test-key-not-for-prod"
