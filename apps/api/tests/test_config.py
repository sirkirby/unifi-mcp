"""Config loader tests."""

from pathlib import Path

import pytest
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig, load_config


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
    assert cfg.policy.response.redact_sensitive_fields is True


def test_load_config_policy_response_redact_sensitive_fields_false(tmp_path: Path) -> None:
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text("policy:\n  response:\n    redact_sensitive_fields: false\n")

    cfg = load_config(yaml_path)

    assert cfg.policy.response.redact_sensitive_fields is False


def test_api_config_direct_construction_defaults_policy() -> None:
    cfg = ApiConfig(
        http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
        logging=LoggingConfig(level="WARNING"),
        db=DbConfig(path="/tmp/unifi-api.db"),
    )

    assert cfg.policy.response.redact_sensitive_fields is True


def test_env_override_takes_precedence(tmp_path: Path, monkeypatch) -> None:
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text("http:\n  host: 127.0.0.1\n  port: 8080\n")
    monkeypatch.setenv("UNIFI_API_HTTP_PORT", "9000")
    cfg = load_config(yaml_path)
    assert cfg.http.port == 9000


def test_global_redaction_env_override_applies_to_api_policy(tmp_path: Path, monkeypatch) -> None:
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text("")
    monkeypatch.setenv("UNIFI_REDACT_SENSITIVE_FIELDS", "false")

    cfg = load_config(yaml_path)

    assert cfg.policy.response.redact_sensitive_fields is False


def test_db_key_must_come_from_env(monkeypatch) -> None:
    monkeypatch.delenv("UNIFI_API_DB_KEY", raising=False)
    with pytest.raises(RuntimeError, match="UNIFI_API_DB_KEY"):
        ApiConfig.read_db_key()
    monkeypatch.setenv("UNIFI_API_DB_KEY", "test-key-not-for-prod")
    assert ApiConfig.read_db_key() == "test-key-not-for-prod"
