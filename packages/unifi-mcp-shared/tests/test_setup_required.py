"""Setup-mode guidance for a server with no controller host."""

import pytest
from omegaconf import OmegaConf
from unifi_mcp_shared.settings_file import SettingsFileReport
from unifi_mcp_shared.setup_required import controller_host_configured, setup_required_message


@pytest.mark.parametrize(
    ("unifi", "configured"),
    [({"host": "192.0.2.10"}, True), ({"host": ""}, False), ({"host": "  "}, False), ({}, False)],
)
def test_controller_host_configured(unifi, configured):
    assert controller_host_configured(OmegaConf.create({"unifi": unifi})) is configured


def test_missing_unifi_section_counts_as_unconfigured():
    assert controller_host_configured(OmegaConf.create({})) is False


def message(state: str | None) -> str:
    report = None if state is None else SettingsFileReport(state=state, path="/home/someone/.config/x.env")
    return setup_required_message(plugin_name="unifi-protect", env_prefix="PROTECT", report=report)


def test_names_every_setup_path():
    text = message(None)
    assert "not configured" in text
    assert "/unifi-protect:unifi-protect-setup" in text
    assert ".claude/settings.local.json" in text
    assert "Codex or OpenClaw: run the unifi-protect-setup skill" in text
    assert "~/.config/unifi-mcp/protect.env" in text
    assert "UNIFI_PROTECT_HOST" in text and "UNIFI_SETTINGS_FILE" in text
    assert "does not exist yet" not in text and "ignored" not in text


def test_names_the_recovery_that_works_in_each_client():
    text = message(None)
    assert "Claude Code: run /reload-plugins or start a new session" in text
    assert "/mcp reconnect does not load new plugin options" in text
    assert "Codex: restart Codex or start a new session" in text
    assert "OpenClaw: start a new session or run openclaw gateway restart" in text
    assert "Standalone: restart the server" in text
    assert "reconnect it in the client" not in text


def test_points_at_the_other_unifi_plugins_without_naming_installed_ones():
    text = message(None)
    assert "Any other UniFi plugins you have installed (Network, Protect, Access) need the same setup" in text


def test_message_stays_short():
    assert len(message("missing").splitlines()) <= 20


@pytest.mark.parametrize(("state", "phrase"), [("missing", "does not exist yet"), ("ignored", "was ignored")])
def test_settings_file_state_is_named_without_its_path(state, phrase):
    text = message(state)
    assert phrase in text
    assert "/home/someone" not in text


def test_loaded_file_without_host_adds_no_file_hint():
    text = message("loaded")
    assert "does not exist yet" not in text and "was ignored" not in text
