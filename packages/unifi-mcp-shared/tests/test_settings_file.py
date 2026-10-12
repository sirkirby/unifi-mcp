"""The per-user settings file named by UNIFI_SETTINGS_FILE."""

from __future__ import annotations

import logging
import os

import pytest
from unifi_core.policy_gate import PolicyGateChecker, resolve_permission_mode
from unifi_mcp_shared import bootstrap
from unifi_mcp_shared.settings_file import SettingsFileReport, apply_settings_file, parse_settings

SENTINEL = "SENTINEL-settings-value"
posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX ownership and mode checks")


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch, tmp_path):
    """Start from no UNIFI_* variables and restore whatever a test applied."""
    saved = dict(os.environ)
    for key in list(os.environ):
        if key.startswith("UNIFI_") or key == "CONFIG_PATH":
            del os.environ[key]
    monkeypatch.setattr(bootstrap, "_TRUSTED_VARS", None)
    monkeypatch.setattr(bootstrap, "_SETTINGS_REPORT", None)
    monkeypatch.chdir(tmp_path)
    yield
    os.environ.clear()
    os.environ.update(saved)


def settings(tmp_path, text: str, mode: int = 0o600):
    path = tmp_path / "network.env"
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)
    return path


def flushed(caplog) -> str:
    """Log the bootstrap's pending settings messages and return all captured text."""
    with caplog.at_level(logging.DEBUG):
        bootstrap.report_settings_file(logging.getLogger("test-settings"))
    return caplog.text


# -- parsing -----------------------------------------------------------------


def test_parses_pairs_comments_blanks_and_quotes():
    report = SettingsFileReport()
    parsed = parse_settings(
        "# comment\n"
        "\n"
        "UNIFI_NETWORK_HOST=192.0.2.10\n"
        "  UNIFI_NETWORK_USERNAME = admin  \n"
        'UNIFI_NETWORK_SITE="default"\n'
        "UNIFI_NETWORK_PORT='8443'\n"
        "UNIFI_NETWORK_PASSWORD=a=b#c ${HOME}\n"
        "UNIFI_TOOL_REGISTRATION_MODE=\n"
        "UNIFI_NETWORK_API_KEY=it's\n",
        report,
    )
    assert parsed == {
        "UNIFI_NETWORK_HOST": "192.0.2.10",
        "UNIFI_NETWORK_USERNAME": "admin",
        "UNIFI_NETWORK_SITE": "default",
        "UNIFI_NETWORK_PORT": "8443",
        # No inline comments and no interpolation.
        "UNIFI_NETWORK_PASSWORD": "a=b#c ${HOME}",
        "UNIFI_TOOL_REGISTRATION_MODE": "",
        "UNIFI_NETWORK_API_KEY": "it's",
    }
    assert report.messages == []


def test_crlf_and_bom_are_tolerated(tmp_path):
    path = tmp_path / "network.env"
    path.write_bytes(b"\xef\xbb\xbfUNIFI_NETWORK_HOST=192.0.2.10\r\nUNIFI_NETWORK_SITE=default\r\n")
    path.chmod(0o600)
    env = {"UNIFI_SETTINGS_FILE": str(path)}
    assert apply_settings_file(env).state == "loaded"
    assert env["UNIFI_NETWORK_HOST"] == "192.0.2.10"
    assert env["UNIFI_NETWORK_SITE"] == "default"


@pytest.mark.parametrize(
    "line",
    [
        f"export UNIFI_NETWORK_PASSWORD={SENTINEL}",
        f"{SENTINEL}",
        f"UNIFI-NETWORK-PASSWORD={SENTINEL}",
        f'UNIFI_NETWORK_PASSWORD="{SENTINEL}',
        f"UNIFI_NETWORK_PASSWORD='{SENTINEL}\"",
        "=nothing",
    ],
)
def test_malformed_line_is_ignored_and_named_by_number_only(line):
    report = SettingsFileReport()
    parsed = parse_settings(f"UNIFI_NETWORK_HOST=192.0.2.10\n\n{line}\n", report)
    assert parsed == {"UNIFI_NETWORK_HOST": "192.0.2.10"}
    [(level, message, args)] = report.messages
    assert level == logging.WARNING
    assert 3 in args
    assert SENTINEL not in message % args


def test_non_unifi_key_is_ignored_and_named_without_its_value():
    report = SettingsFileReport()
    parsed = parse_settings(f"PYTHONPATH={SENTINEL}\nUNIFI_NETWORK_HOST=192.0.2.10\n", report)
    assert parsed == {"UNIFI_NETWORK_HOST": "192.0.2.10"}
    [(level, message, args)] = report.messages
    assert level == logging.WARNING
    rendered = message % args
    assert "PYTHONPATH" in rendered
    assert SENTINEL not in rendered


def test_settings_file_cannot_name_another_settings_file():
    report = SettingsFileReport()
    assert parse_settings("UNIFI_SETTINGS_FILE=/elsewhere.env\n", report) == {}
    assert report.messages


# -- precedence --------------------------------------------------------------


def test_process_environment_wins_over_the_file(tmp_path):
    path = settings(tmp_path, "UNIFI_NETWORK_HOST=from-file.invalid\nUNIFI_NETWORK_SITE=filesite\n")
    env = {"UNIFI_SETTINGS_FILE": str(path), "UNIFI_NETWORK_HOST": "from-env.invalid"}
    report = apply_settings_file(env)
    assert report.state == "loaded"
    assert env["UNIFI_NETWORK_HOST"] == "from-env.invalid"
    assert env["UNIFI_NETWORK_SITE"] == "filesite"


def test_tilde_is_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    settings(tmp_path, "UNIFI_NETWORK_HOST=192.0.2.10\n")
    env = {"UNIFI_SETTINGS_FILE": "~/network.env"}
    report = apply_settings_file(env)
    assert report.state == "loaded"
    assert report.path == str(tmp_path / "network.env")
    assert env["UNIFI_NETWORK_HOST"] == "192.0.2.10"


# -- missing, relative, unreadable -------------------------------------------


def test_missing_file_loads_nothing_and_does_not_raise(tmp_path):
    env = {"UNIFI_SETTINGS_FILE": str(tmp_path / "absent.env")}
    report = apply_settings_file(env)
    assert report.state == "missing"
    assert env == {"UNIFI_SETTINGS_FILE": str(tmp_path / "absent.env")}


@pytest.mark.parametrize("value", ["network.env", "./network.env", "config/network.env"])
def test_relative_path_is_refused_with_an_error_naming_the_variable(tmp_path, value):
    (tmp_path / "config").mkdir()
    settings(tmp_path, "UNIFI_NETWORK_HOST=project.invalid\n")
    (tmp_path / "config" / "network.env").write_text("UNIFI_NETWORK_HOST=project.invalid\n")
    env = {"UNIFI_SETTINGS_FILE": value}
    report = apply_settings_file(env)
    assert report.state == "ignored"
    assert "UNIFI_NETWORK_HOST" not in env
    [(level, message, args)] = report.messages
    assert level == logging.ERROR
    assert "UNIFI_SETTINGS_FILE" in message % args


def test_directory_is_refused(tmp_path):
    env = {"UNIFI_SETTINGS_FILE": str(tmp_path)}
    assert apply_settings_file(env).state == "ignored"


@posix_only
def test_fifo_is_refused_without_blocking(tmp_path):
    fifo = tmp_path / "network.env"
    os.mkfifo(fifo, 0o600)
    env = {"UNIFI_SETTINGS_FILE": str(fifo)}
    assert apply_settings_file(env).state == "ignored"


def test_non_utf8_file_is_refused(tmp_path):
    path = tmp_path / "network.env"
    path.write_bytes(b"UNIFI_NETWORK_HOST=\xff\n")
    path.chmod(0o600)
    assert apply_settings_file({"UNIFI_SETTINGS_FILE": str(path)}).state == "ignored"


def test_oversized_file_is_refused(tmp_path):
    path = settings(tmp_path, "# padding\n" * 200_000)
    assert apply_settings_file({"UNIFI_SETTINGS_FILE": str(path)}).state == "ignored"


def test_empty_variable_counts_as_unset():
    env = {"UNIFI_SETTINGS_FILE": ""}
    assert apply_settings_file(env).state == "unset"


# -- permissions -------------------------------------------------------------


@posix_only
@pytest.mark.parametrize("mode", [0o620, 0o602, 0o666])
def test_group_or_world_writable_file_is_ignored(tmp_path, mode):
    path = settings(tmp_path, "UNIFI_NETWORK_HOST=192.0.2.10\n", mode=mode)
    env = {"UNIFI_SETTINGS_FILE": str(path)}
    report = apply_settings_file(env)
    assert report.state == "ignored"
    assert "UNIFI_NETWORK_HOST" not in env
    assert report.messages[-1][0] == logging.ERROR


@posix_only
def test_file_owned_by_someone_else_is_ignored(tmp_path, monkeypatch):
    path = settings(tmp_path, "UNIFI_NETWORK_HOST=192.0.2.10\n")
    monkeypatch.setattr(os, "geteuid", lambda: os.stat(path).st_uid + 1)
    env = {"UNIFI_SETTINGS_FILE": str(path)}
    report = apply_settings_file(env)
    assert report.state == "ignored"
    assert "UNIFI_NETWORK_HOST" not in env
    assert "not owned by the current user" in report.messages[-1][1]


@posix_only
@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644])
def test_group_or_world_readable_file_warns_and_is_used(tmp_path, mode):
    path = settings(tmp_path, "UNIFI_NETWORK_HOST=192.0.2.10\n", mode=mode)
    env = {"UNIFI_SETTINGS_FILE": str(path)}
    report = apply_settings_file(env)
    assert report.state == "loaded"
    assert env["UNIFI_NETWORK_HOST"] == "192.0.2.10"
    assert any(level == logging.WARNING and "chmod 600" in message for level, message, _ in report.messages)


@posix_only
def test_windows_skips_the_mode_check(tmp_path):
    path = settings(tmp_path, "UNIFI_NETWORK_HOST=192.0.2.10\n", mode=0o666)
    env = {"UNIFI_SETTINGS_FILE": str(path)}
    assert apply_settings_file(env, os_name="nt").state == "loaded"
    assert env["UNIFI_NETWORK_HOST"] == "192.0.2.10"


# -- startup: every reader sees the file -------------------------------------


@pytest.fixture
def bundled_config(tmp_path, monkeypatch):
    bundle = tmp_path / "bundled"
    bundle.mkdir()
    (bundle / "config.yaml").write_text(
        'unifi:\n  host: ""\n  username: ""\n  password: ""\n  api_key: ""\n'
        "  port: 443\n  site: default\n  verify_ssl: false\n"
        'server:\n  log_level: ${oc.env:UNIFI_MCP_LOG_LEVEL,"INFO"}\n'
    )
    monkeypatch.setattr(bootstrap.importlib.resources, "files", lambda _: bundle)


def load_config():
    return bootstrap.load_server_config(
        package_name="synthetic.config", env_prefix="NETWORK", logger=logging.getLogger("test-settings")
    )


def test_file_configures_host_secret_provider_and_yaml_interpolation(tmp_path, bundled_config, caplog):
    secret = tmp_path / "password"
    secret.write_text(f"{SENTINEL}\n")
    secret.chmod(0o600)
    path = settings(
        tmp_path,
        "UNIFI_NETWORK_HOST=192.0.2.11\nUNIFI_NETWORK_PORT=9\nUNIFI_NETWORK_USERNAME=fake-user\n"
        f"UNIFI_NETWORK_PASSWORD_FILE={secret}\nUNIFI_NETWORK_VERIFY_SSL=true\nUNIFI_MCP_LOG_LEVEL=DEBUG\n",
    )
    os.environ["UNIFI_SETTINGS_FILE"] = str(path)
    bootstrap.load_process_env()
    with caplog.at_level(logging.DEBUG):
        cfg = load_config()
    assert cfg.unifi.host == "192.0.2.11"
    assert int(cfg.unifi.port) == 9
    assert cfg.unifi.verify_ssl is True
    assert cfg.unifi.password == SENTINEL
    assert cfg.server.log_level == "DEBUG"
    # Applied before the snapshot, so the indirection counts as launcher-supplied.
    assert "UNIFI_NETWORK_PASSWORD_FILE" in bootstrap._TRUSTED_VARS
    bootstrap.assert_credentials_configured(
        cfg, plugin_name="unifi-network", env_prefix="NETWORK", logger=logging.getLogger("test-settings")
    )
    assert SENTINEL not in flushed(caplog)


@posix_only
def test_command_provider_from_the_file_runs_and_inherits_file_settings(tmp_path, bundled_config, caplog):
    helper = tmp_path / "helper.sh"
    helper.write_text('#!/bin/sh\nprintf %s "$UNIFI_HELPER_ITEM"\n')
    helper.chmod(0o700)
    path = settings(
        tmp_path,
        f"UNIFI_NETWORK_HOST=192.0.2.11\nUNIFI_HELPER_ITEM={SENTINEL}\nUNIFI_NETWORK_PASSWORD_COMMAND={helper}\n",
    )
    os.environ["UNIFI_SETTINGS_FILE"] = str(path)
    bootstrap.load_process_env()
    with caplog.at_level(logging.DEBUG):
        cfg = load_config()
    assert cfg.unifi.password == SENTINEL
    assert SENTINEL not in flushed(caplog)


def test_policy_gates_permission_and_registration_modes_read_the_file(tmp_path):
    path = settings(
        tmp_path,
        "UNIFI_POLICY_NETWORK_DELETE=false\n"
        "UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_UPDATE=false\n"
        "UNIFI_NETWORK_TOOL_PERMISSION_MODE=bypass\n"
        "UNIFI_TOOL_REGISTRATION_MODE=eager\n",
    )
    os.environ["UNIFI_SETTINGS_FILE"] = str(path)
    bootstrap.load_process_env()
    gates = PolicyGateChecker(server_prefix="NETWORK", category_map={"firewall": "firewall_policies"})
    assert gates.check("devices", "delete") is False
    assert gates.check("firewall", "update") is False
    assert gates.check("devices", "update") is True
    assert resolve_permission_mode("network") == "bypass"
    assert bootstrap.validate_registration_mode(logging.getLogger("test-settings")) == "eager"


def test_auto_confirm_reads_the_file(tmp_path):
    path = settings(tmp_path, "UNIFI_AUTO_CONFIRM=true\n")
    os.environ["UNIFI_SETTINGS_FILE"] = str(path)
    bootstrap.load_process_env()
    assert resolve_permission_mode("network") == "bypass"


def test_process_environment_still_wins_at_startup(tmp_path, bundled_config):
    path = settings(tmp_path, "UNIFI_NETWORK_HOST=from-file.invalid\nUNIFI_POLICY_NETWORK_DELETE=true\n")
    os.environ["UNIFI_SETTINGS_FILE"] = str(path)
    os.environ["UNIFI_NETWORK_HOST"] = "from-env.invalid"
    os.environ["UNIFI_POLICY_NETWORK_DELETE"] = "false"
    bootstrap.load_process_env()
    assert load_config().unifi.host == "from-env.invalid"
    assert PolicyGateChecker(server_prefix="NETWORK").check("devices", "delete") is False


def test_file_is_loaded_once(tmp_path):
    path = settings(tmp_path, "UNIFI_NETWORK_HOST=192.0.2.10\n")
    os.environ["UNIFI_SETTINGS_FILE"] = str(path)
    bootstrap.load_process_env()
    del os.environ["UNIFI_NETWORK_HOST"]
    bootstrap.load_process_env()
    assert "UNIFI_NETWORK_HOST" not in os.environ


def test_project_dotenv_is_still_not_loaded(tmp_path, bundled_config):
    (tmp_path / ".env").write_text("UNIFI_NETWORK_HOST=project.invalid\n")
    path = settings(tmp_path, "UNIFI_NETWORK_SITE=filesite\n")
    os.environ["UNIFI_SETTINGS_FILE"] = str(path)
    bootstrap.load_process_env()
    assert load_config().unifi.host == ""


# -- unconfigured and refused files ------------------------------------------


def unconfigured_message(caplog) -> str:
    with caplog.at_level(logging.DEBUG), pytest.raises(SystemExit) as error:
        bootstrap.assert_credentials_configured(
            load_config(), plugin_name="unifi-network", env_prefix="NETWORK", logger=logging.getLogger("test-settings")
        )
    assert error.value.code == 5
    return caplog.text


def test_missing_file_starts_as_unconfigured_with_a_setup_hint(tmp_path, bundled_config, caplog):
    absent = tmp_path / "absent.env"
    os.environ["UNIFI_SETTINGS_FILE"] = str(absent)
    bootstrap.load_process_env()
    text = unconfigured_message(caplog)
    assert "unifi-network-setup skill" in text
    assert str(absent) in text
    assert "does not exist yet" in text


def test_unset_variable_mentions_the_settings_file_option(bundled_config, caplog):
    bootstrap.load_process_env()
    text = unconfigured_message(caplog)
    assert "UNIFI_SETTINGS_FILE" in text
    assert "does not exist yet" not in text


@posix_only
def test_refused_file_is_called_out_when_unconfigured(tmp_path, bundled_config, caplog):
    path = settings(tmp_path, "UNIFI_NETWORK_HOST=192.0.2.10\n", mode=0o666)
    os.environ["UNIFI_SETTINGS_FILE"] = str(path)
    bootstrap.load_process_env()
    text = flushed(caplog) + unconfigured_message(caplog)
    assert "other users can write" in text
    assert "UNIFI_SETTINGS_FILE was ignored" in text


# -- values never reach the logs ---------------------------------------------


def test_no_value_from_the_file_is_logged(tmp_path, bundled_config, caplog):
    path = settings(
        tmp_path,
        f"UNIFI_NETWORK_HOST=192.0.2.11\nUNIFI_NETWORK_PASSWORD={SENTINEL}\n"
        f"OTHER_SECRET={SENTINEL}\nexport UNIFI_NETWORK_API_KEY={SENTINEL}\n{SENTINEL}\n"
        f"UNIFI_NETWORK_USERNAME='{SENTINEL}\n",
        mode=0o644,
    )
    os.environ["UNIFI_SETTINGS_FILE"] = str(path)
    os.environ["UNIFI_NETWORK_HOST"] = "from-env.invalid"
    bootstrap.load_process_env()
    with caplog.at_level(logging.DEBUG):
        load_config()
    text = flushed(caplog)
    assert "Loaded" in text
    assert "line 4" in text and "line 5" in text and "line 6" in text
    assert "OTHER_SECRET" in text
    assert SENTINEL not in text


def test_report_is_flushed_once(tmp_path, caplog):
    path = settings(tmp_path, "UNIFI_NETWORK_HOST=192.0.2.10\n")
    os.environ["UNIFI_SETTINGS_FILE"] = str(path)
    bootstrap.load_process_env()
    first = flushed(caplog)
    caplog.clear()
    assert "Loaded 1 setting" in first
    assert flushed(caplog) == ""


def test_report_without_load_is_a_no_op(caplog):
    assert flushed(caplog) == ""
