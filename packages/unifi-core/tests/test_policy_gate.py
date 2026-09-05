"""Tests for the startup scan of unrecognized UNIFI_POLICY_* env vars."""

import logging
import os

import pytest
from unifi_core.policy_gate import PolicyGateChecker, check_unknown_policy_env_vars

LOGGER = logging.getLogger("unifi_core.policy_gate")

# (permission_category, permission_action) pairs as the manifest records them,
# and the category map that turns the shorthand into the env var's config key.
PROTECT_GATES = [
    ("camera", "update"),
    ("light", "update"),
    ("alarm", "create"),
    ("alarm", "delete"),
]
PROTECT_MAP = {"camera": "cameras", "light": "lights"}


@pytest.fixture(autouse=True)
def _clear_policy_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("UNIFI_POLICY_"):
            monkeypatch.delenv(key)


def _run(server_prefix, gates, caplog, category_map=PROTECT_MAP):
    with caplog.at_level(logging.WARNING, logger="unifi_core.policy_gate"):
        return check_unknown_policy_env_vars(server_prefix, LOGGER, gates, category_map)


def test_env_var_names_resolve_the_category_and_order_most_specific_first():
    checker = PolicyGateChecker("protect", PROTECT_MAP)

    assert checker.env_var_names("camera", "update") == [
        "UNIFI_POLICY_PROTECT_CAMERAS_UPDATE",
        "UNIFI_POLICY_PROTECT_UPDATE",
        "UNIFI_POLICY_UPDATE",
    ]


def test_denial_message_names_the_config_key_form(caplog):
    checker = PolicyGateChecker("protect", PROTECT_MAP)

    assert "Set UNIFI_POLICY_PROTECT_CAMERAS_UPDATE=true" in checker.denial_message("camera", "update")
    assert "UNIFI_POLICY_PROTECT_CAMERAS_READ" in checker.denial_message("camera", "read")


def test_unknown_category_warns_and_names_the_nearest_valid_var(monkeypatch, caplog):
    monkeypatch.setenv("UNIFI_POLICY_PROTECT_CAMERA_UPDATE", "true")

    unknown = _run("protect", PROTECT_GATES, caplog)

    assert unknown == ["UNIFI_POLICY_PROTECT_CAMERA_UPDATE"]
    assert "UNIFI_POLICY_PROTECT_CAMERA_UPDATE" in caplog.text
    assert "UNIFI_POLICY_PROTECT_CAMERAS_UPDATE" in caplog.text


@pytest.mark.parametrize(
    "var",
    [
        "UNIFI_POLICY_PROTECT_CAMERAS_UPDATE",  # registered category gate
        "UNIFI_POLICY_PROTECT_ALARM_DELETE",  # category not in the map, used as is
        "UNIFI_POLICY_PROTECT_UPDATE",  # server-level action
        "UNIFI_POLICY_DELETE",  # global action
        "UNIFI_POLICY_NETWORK_CLIENT_GROUP_DELETE",  # another server's variable
        "UNIFI_POLICY_ACCESS_DOOR_UPDATE",  # another server's variable
        "UNIFI_PERMISSIONS_CAMERA_UPDATE",  # deprecated prefix, handled elsewhere
    ],
)
def test_recognized_or_out_of_scope_vars_do_not_warn(var, monkeypatch, caplog):
    monkeypatch.setenv(var, "true")

    assert _run("protect", PROTECT_GATES, caplog) == []
    assert caplog.text == ""


def test_action_no_tool_registers_for_that_category_warns(monkeypatch, caplog):
    monkeypatch.setenv("UNIFI_POLICY_PROTECT_CAMERAS_DELETE", "true")

    assert _run("protect", PROTECT_GATES, caplog) == ["UNIFI_POLICY_PROTECT_CAMERAS_DELETE"]
    assert "UNIFI_POLICY_PROTECT_CAMERAS_UPDATE" in caplog.text


@pytest.mark.parametrize(
    "var",
    [
        "UNIFI_POLICY_PROTEKT_CAMERAS_UPDATE",  # misspelled server segment
        "UNIFI_POLICY_PROTECTCAMERAS_UPDATE",  # missing underscore
        "UNIFI_POLICY_CAMERAS_UPDATE",  # server segment dropped
    ],
)
def test_var_whose_first_segment_is_not_a_known_server_warns(var, monkeypatch, caplog):
    monkeypatch.setenv(var, "false")

    assert _run("protect", PROTECT_GATES, caplog) == [var]
    assert "UNIFI_POLICY_PROTECT_CAMERAS_UPDATE" in caplog.text


def test_misspelled_global_action_warns(monkeypatch, caplog):
    monkeypatch.setenv("UNIFI_POLICY_UPDAET", "false")

    assert _run("protect", PROTECT_GATES, caplog) == ["UNIFI_POLICY_UPDAET"]
    assert "UNIFI_POLICY_UPDATE" in caplog.text


def test_read_gates_are_never_valid_because_reads_are_not_gated(monkeypatch, caplog):
    monkeypatch.setenv("UNIFI_POLICY_ACCESS_DOORS_READ", "false")

    unknown = _run("access", [("door", "read"), ("door", "update")], caplog, {"door": "doors"})

    assert unknown == ["UNIFI_POLICY_ACCESS_DOORS_READ"]
    assert "UNIFI_POLICY_ACCESS_DOORS_UPDATE" in caplog.text


def test_unknown_var_with_no_close_match_still_names_the_var(monkeypatch, caplog):
    monkeypatch.setenv("UNIFI_POLICY_PROTECT_ZZZZZZZZ_QQQQQQ", "true")

    assert _run("protect", PROTECT_GATES, caplog) == ["UNIFI_POLICY_PROTECT_ZZZZZZZZ_QQQQQQ"]
    assert "UNIFI_POLICY_PROTECT_ZZZZZZZZ_QQQQQQ" in caplog.text


def test_empty_gate_list_skips_the_scan_and_says_so(monkeypatch, caplog):
    monkeypatch.setenv("UNIFI_POLICY_PROTECT_CAMERA_UPDATE", "true")

    assert _run("protect", [], caplog) == []
    assert "UNIFI_POLICY_PROTECT_CAMERA_UPDATE" not in caplog.text
    assert "skipping the UNIFI_POLICY_* scan" in caplog.text


def test_only_read_gates_counts_as_no_gates(monkeypatch, caplog):
    monkeypatch.setenv("UNIFI_POLICY_PROTECT_CAMERA_UPDATE", "true")

    assert _run("protect", [("camera", "read")], caplog) == []
    assert "skipping the UNIFI_POLICY_* scan" in caplog.text


def test_newlines_in_a_variable_name_are_escaped_in_the_log(monkeypatch, caplog):
    monkeypatch.setenv("UNIFI_POLICY_PROTECT_X\nCRITICAL forged line", "true")

    _run("protect", PROTECT_GATES, caplog)

    assert "\nCRITICAL" not in caplog.text
    assert "UNIFI_POLICY_PROTECT_X\\nCRITICAL forged line" in caplog.text


def test_reporting_is_capped_with_a_summary_line(monkeypatch, caplog):
    names = [f"UNIFI_POLICY_PROTECT_BOGUS{i:02d}_UPDATE" for i in range(23)]
    for name in names:
        monkeypatch.setenv(name, "true")

    assert _run("protect", PROTECT_GATES, caplog) == names
    assert caplog.text.count("Unrecognized env var") == 20
    assert "3 more unrecognized UNIFI_POLICY_* variables not listed" in caplog.text
