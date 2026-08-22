import os
import sys

import pytest


def test_help_prints_usage_without_loading_relay_config(monkeypatch, capsys):
    from unifi_mcp_relay import __main__ as entrypoint

    dotenv_calls = []
    monkeypatch.setattr(sys, "argv", ["unifi-mcp-relay", "--help"])
    monkeypatch.setattr(entrypoint, "load_dotenv", lambda: dotenv_calls.append(True))
    for name in ("UNIFI_RELAY_URL", "UNIFI_RELAY_TOKEN", "UNIFI_RELAY_LOCATION_NAME"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(SystemExit) as exc:
        entrypoint.main()

    captured = capsys.readouterr()
    assert exc.value.code == 0
    assert dotenv_calls == []
    assert "usage: unifi-mcp-relay" in captured.out
    assert "UNIFI_RELAY_URL" not in captured.err


@pytest.mark.parametrize(
    ("dotenv_value", "environment_value", "expected"),
    [
        ("from-dotenv", None, "from-dotenv"),
        ("from-dotenv", "from-environment", "from-environment"),
        (None, None, "MISSING"),
    ],
)
def test_main_loads_cwd_dotenv_without_overriding_environment(
    tmp_path,
    monkeypatch,
    dotenv_value,
    environment_value,
    expected,
):
    from unifi_mcp_relay import __main__ as entrypoint
    from unifi_mcp_relay import config as config_module

    marker = "UNIFI_TEST_RELAY_CWD_DOTENV"
    if dotenv_value is not None:
        (tmp_path / ".env").write_text(f"{marker}={dotenv_value}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(marker, raising=False)
    if environment_value is not None:
        monkeypatch.setenv(marker, environment_value)

    class ConfigObserved(Exception):
        pass

    def observe_config():
        assert os.getenv(marker, "MISSING") == expected
        raise ConfigObserved

    monkeypatch.setattr(config_module, "load_config", observe_config)

    with pytest.raises(ConfigObserved):
        entrypoint.main([])
