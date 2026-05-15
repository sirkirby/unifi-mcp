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
