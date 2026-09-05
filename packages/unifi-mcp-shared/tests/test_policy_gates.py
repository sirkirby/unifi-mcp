"""Tests for reading policy gates out of a tools manifest."""

import json

import pytest
from unifi_mcp_shared.tool_index import policy_gates_from_manifest


def _write_manifest(tmp_path, tools):
    path = tmp_path / "tools_manifest.json"
    path.write_text(json.dumps({"count": len(tools), "tools": tools, "module_map": {}}))
    return path


def test_returns_the_manifest_category_and_action_pairs(tmp_path):
    path = _write_manifest(
        tmp_path,
        [
            {"name": "protect_update_camera", "permission_category": "camera", "permission_action": "update"},
            {"name": "unifi_delete_client_group", "permission_category": "client_group", "permission_action": "delete"},
            {"name": "protect_arm_alarm", "permission_category": "alarm", "permission_action": "update"},
        ],
    )

    assert policy_gates_from_manifest(path) == frozenset(
        {("camera", "update"), ("client_group", "delete"), ("alarm", "update")}
    )


def test_tools_without_a_full_permission_pair_are_skipped(tmp_path):
    path = _write_manifest(
        tmp_path,
        [
            {"name": "protect_list_cameras"},
            {"name": "protect_get_camera", "permission_category": "camera"},
        ],
    )

    assert policy_gates_from_manifest(path) == frozenset()


def test_missing_manifest_yields_no_gates(tmp_path):
    assert policy_gates_from_manifest(tmp_path / "missing.json") == frozenset()


@pytest.mark.parametrize(
    "manifest",
    [
        ["not", "an", "object"],
        {"tools": "not a list"},
        {"tools": ["not a dict", None]},
        {"tools": [{"name": "x", "permission_category": ["camera"], "permission_action": "update"}]},
        {"tools": [{"name": "x", "permission_category": 7, "permission_action": "update"}]},
        {"tools": [{"name": "x", "permission_category": "camera", "permission_action": None}]},
    ],
)
def test_malformed_manifest_shapes_yield_no_gates_instead_of_raising(tmp_path, manifest):
    path = tmp_path / "tools_manifest.json"
    path.write_text(json.dumps(manifest))

    assert policy_gates_from_manifest(path) == frozenset()
