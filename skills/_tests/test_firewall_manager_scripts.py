"""Tests for firewall-manager skill scripts: export, diff, apply-template."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# The scripts live in the plugin's scripts/ directory — add it to sys.path for import.
_scripts_dir = Path(__file__).resolve().parent.parent.parent / (
    "plugins/unifi-network/skills/firewall-manager/scripts"
)
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

# Import hyphenated modules by filename.
import importlib.util


def _import_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, _scripts_dir / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules[name] = mod
    return mod


export_mod = _import_script("export_policies", "export-policies.py")
diff_mod = _import_script("diff_policies", "diff-policies.py")
apply_mod = _import_script("apply_template", "apply-template.py")

# Pull out names from export-policies.
export_policies = export_mod.export_policies
export_parse_args = export_mod.parse_args
save_snapshot = export_mod.save_snapshot
list_snapshots = export_mod.list_snapshots
_extract_list = export_mod._extract_list

# Pull out names from diff-policies.
diff_snapshots = diff_mod.diff_snapshots
diff_collection = diff_mod.diff_collection
diff_parse_args = diff_mod.parse_args
load_snapshot_pair = diff_mod.load_snapshot_pair
find_recent_snapshots = diff_mod.find_recent_snapshots

# Pull out names from apply-template.
apply_template = apply_mod.apply_template
apply_parse_args = apply_mod.parse_args
list_templates = apply_mod.list_templates
load_templates = apply_mod.load_templates
get_template_by_name = apply_mod.get_template_by_name
get_template_names = apply_mod.get_template_names
parse_params = apply_mod.parse_params
validate_params = apply_mod.validate_params
get_required_params = apply_mod.get_required_params
_substitute = apply_mod._substitute


# ==============================================================================
# Mock MCP client helper
# ==============================================================================


def _make_mock_client(tool_results: dict, ready: bool = True):
    """Create a mock MCPClient that returns canned results."""
    client = MagicMock()
    client.check_ready = MagicMock(return_value=ready)
    client.get_setup_error = MagicMock(return_value={
        "success": False,
        "error": "setup_required",
        "message": "MCP server not reachable.",
    })

    def fake_parallel(calls):
        return [tool_results.get(name, {"success": False, "error": f"{name} not mocked"}) for name, _ in calls]

    client.call_tools_parallel = MagicMock(side_effect=fake_parallel)

    def fake_call_tool(name, args=None):
        if name == "unifi_get_firewall_policy_details":
            pid = (args or {}).get("policy_id", "")
            return tool_results.get(f"detail_{pid}", {"success": False, "error": "not found"})
        return tool_results.get(name, {"success": False, "error": f"{name} not mocked"})

    client.call_tool = MagicMock(side_effect=fake_call_tool)

    return client


# Shared fixture data for export tests.
EXPORT_TOOL_RESULTS = {
    "unifi_list_firewall_policies": {
        "success": True,
        "policies": [
            {"id": "p1", "name": "Block IoT", "enabled": True, "action": "drop", "rule_index": 100, "ruleset": "LAN_IN"},
            {"id": "p2", "name": "Allow DNS", "enabled": True, "action": "accept", "rule_index": 200, "ruleset": "LAN_OUT"},
        ],
    },
    "unifi_list_firewall_zones": {
        "success": True,
        "zones": [{"_id": "z1", "name": "LAN"}, {"_id": "z2", "name": "WAN"}],
    },
    "unifi_list_networks": {
        "success": True,
        "networks": [
            {"_id": "n1", "name": "Main LAN", "purpose": "corporate"},
            {"_id": "n2", "name": "IoT VLAN", "purpose": "corporate"},
        ],
    },
    "unifi_list_firewall_groups": {
        "success": True,
        "groups": [{"_id": "g1", "name": "Servers"}],
    },
    "detail_p1": {
        "success": True,
        "details": {
            "_id": "p1",
            "name": "Block IoT",
            "enabled": True,
            "action": "drop",
            "source": {"network_id": "n2"},
            "destination": {"network_id": "n1"},
        },
    },
    "detail_p2": {
        "success": True,
        "details": {
            "_id": "p2",
            "name": "Allow DNS",
            "enabled": True,
            "action": "accept",
            "source": {"network_id": "n2"},
            "destination": {"zone_id": "wan"},
        },
    },
}


# ==============================================================================
# export-policies.py tests
# ==============================================================================


class TestExportParseArgs:
    def test_defaults(self):
        args = export_parse_args([])
        assert args.mcp_url is None
        assert args.state_dir is None

    def test_mcp_url(self):
        args = export_parse_args(["--mcp-url", "http://myhost:4000"])
        assert args.mcp_url == "http://myhost:4000"

    def test_state_dir(self):
        args = export_parse_args(["--state-dir", "/tmp/test"])
        assert args.state_dir == "/tmp/test"


def test_export_parallel_collection(tmp_path):
    """Test that export calls four tools in parallel then fetches details."""
    mock_client = _make_mock_client(EXPORT_TOOL_RESULTS)

    with patch(f"{export_mod.__name__}.MCPClient", return_value=mock_client):
        result = export_policies("http://localhost:3000", tmp_path)

    assert result["success"] is True
    # Parallel collection should have been called.
    mock_client.call_tools_parallel.assert_called_once()
    call_args = mock_client.call_tools_parallel.call_args[0][0]
    tool_names = [name for name, _ in call_args]
    assert "unifi_list_firewall_policies" in tool_names
    assert "unifi_list_firewall_zones" in tool_names
    assert "unifi_list_networks" in tool_names
    assert "unifi_list_firewall_groups" in tool_names


def test_export_fetches_policy_details(tmp_path):
    """Test that export fetches details for each policy."""
    mock_client = _make_mock_client(EXPORT_TOOL_RESULTS)

    with patch(f"{export_mod.__name__}.MCPClient", return_value=mock_client):
        result = export_policies("http://localhost:3000", tmp_path)

    assert result["success"] is True
    detail_calls = [
        c for c in mock_client.call_tool.call_args_list
        if c[0][0] == "unifi_get_firewall_policy_details"
    ]
    assert len(detail_calls) == 2


def test_export_snapshot_structure(tmp_path):
    """Test that the snapshot has the correct top-level keys."""
    mock_client = _make_mock_client(EXPORT_TOOL_RESULTS)

    with patch(f"{export_mod.__name__}.MCPClient", return_value=mock_client):
        result = export_policies("http://localhost:3000", tmp_path)

    snapshot = result["snapshot"]
    assert "timestamp" in snapshot
    assert "policies" in snapshot
    assert "zones" in snapshot
    assert "networks" in snapshot
    assert "firewall_groups" in snapshot
    assert len(snapshot["policies"]) == 2
    assert len(snapshot["zones"]) == 2
    assert len(snapshot["networks"]) == 2
    assert len(snapshot["firewall_groups"]) == 1


def test_export_saves_file(tmp_path):
    """Test that export saves a timestamped snapshot file."""
    mock_client = _make_mock_client(EXPORT_TOOL_RESULTS)

    with patch(f"{export_mod.__name__}.MCPClient", return_value=mock_client):
        result = export_policies("http://localhost:3000", tmp_path)

    assert result["success"] is True
    assert "file" in result
    saved_path = Path(result["file"])
    assert saved_path.exists()
    saved_data = json.loads(saved_path.read_text())
    assert "timestamp" in saved_data
    assert "policies" in saved_data


def test_export_snapshot_file_naming(tmp_path):
    """Test that snapshot files have timestamp-based names in the correct subdir."""
    mock_client = _make_mock_client(EXPORT_TOOL_RESULTS)

    with patch(f"{export_mod.__name__}.MCPClient", return_value=mock_client):
        result = export_policies("http://localhost:3000", tmp_path)

    file_path = Path(result["file"])
    assert file_path.suffix == ".json"
    assert file_path.parent.name == "firewall-snapshots"


def test_export_setup_required(tmp_path):
    """Test that unreachable server returns setup_required error."""
    mock_client = _make_mock_client({}, ready=False)

    with patch(f"{export_mod.__name__}.MCPClient", return_value=mock_client):
        result = export_policies("http://localhost:3000", tmp_path)

    assert result["success"] is False
    assert result["error"] == "setup_required"


def test_export_summary_counts(tmp_path):
    """Test that export returns correct summary counts."""
    mock_client = _make_mock_client(EXPORT_TOOL_RESULTS)

    with patch(f"{export_mod.__name__}.MCPClient", return_value=mock_client):
        result = export_policies("http://localhost:3000", tmp_path)

    assert result["summary"]["policies"] == 2
    assert result["summary"]["zones"] == 2
    assert result["summary"]["networks"] == 2
    assert result["summary"]["firewall_groups"] == 1


def test_export_extract_list_success():
    """Test _extract_list with a successful result."""
    result = {"success": True, "policies": [{"id": "p1"}]}
    assert _extract_list(result, "policies") == [{"id": "p1"}]


def test_export_extract_list_failure():
    """Test _extract_list with a failed result."""
    result = {"success": False, "error": "something"}
    assert _extract_list(result, "policies") == []


def test_list_snapshots_empty(tmp_path):
    """Test list_snapshots with no snapshots directory."""
    assert list_snapshots(tmp_path) == []


def test_list_snapshots_sorted(tmp_path):
    """Test that list_snapshots returns files sorted by name."""
    snap_dir = tmp_path / "firewall-snapshots"
    snap_dir.mkdir()
    (snap_dir / "2026-01-01T00-00-00.json").write_text("{}")
    (snap_dir / "2026-01-02T00-00-00.json").write_text("{}")
    (snap_dir / "2026-01-01T12-00-00.json").write_text("{}")

    files = list_snapshots(tmp_path)
    names = [f.name for f in files]
    assert names == sorted(names)
    assert len(files) == 3


# ==============================================================================
# diff-policies.py tests
# ==============================================================================


# Sample snapshots for diff tests.
SNAPSHOT_V1 = {
    "timestamp": "2026-01-01T00:00:00+00:00",
    "policies": [
        {"id": "p1", "name": "Block IoT", "enabled": True, "action": "drop"},
        {"id": "p2", "name": "Allow DNS", "enabled": True, "action": "accept"},
    ],
    "zones": [{"_id": "z1", "name": "LAN"}, {"_id": "z2", "name": "WAN"}],
    "networks": [{"_id": "n1", "name": "Main LAN"}, {"_id": "n2", "name": "IoT VLAN"}],
    "firewall_groups": [{"_id": "g1", "name": "Servers"}],
}

SNAPSHOT_V2 = {
    "timestamp": "2026-01-02T00:00:00+00:00",
    "policies": [
        {"id": "p1", "name": "Block IoT", "enabled": False, "action": "drop"},  # modified: enabled changed
        # p2 removed
        {"id": "p3", "name": "Block Guest", "enabled": True, "action": "reject"},  # added
    ],
    "zones": [{"_id": "z1", "name": "LAN"}, {"_id": "z2", "name": "WAN"}],
    "networks": [{"_id": "n1", "name": "Main LAN"}, {"_id": "n2", "name": "IoT VLAN"}, {"_id": "n3", "name": "Guest"}],
    "firewall_groups": [{"_id": "g1", "name": "Servers"}],
}


class TestDiffParseArgs:
    def test_defaults(self):
        args = diff_parse_args([])
        assert args.current is None
        assert args.previous is None
        assert args.state_dir is None

    def test_explicit_files(self):
        args = diff_parse_args(["--current", "/tmp/a.json", "--previous", "/tmp/b.json"])
        assert args.current == "/tmp/a.json"
        assert args.previous == "/tmp/b.json"


class TestDiffCollection:
    def test_added_items(self):
        prev = [{"id": "p1", "name": "A"}]
        curr = [{"id": "p1", "name": "A"}, {"id": "p2", "name": "B"}]
        result = diff_collection(prev, curr, "id")
        assert len(result["added"]) == 1
        assert result["added"][0]["id"] == "p2"
        assert result["removed"] == []
        assert result["modified"] == []
        assert result["unchanged_count"] == 1

    def test_removed_items(self):
        prev = [{"id": "p1", "name": "A"}, {"id": "p2", "name": "B"}]
        curr = [{"id": "p1", "name": "A"}]
        result = diff_collection(prev, curr, "id")
        assert result["added"] == []
        assert len(result["removed"]) == 1
        assert result["removed"][0]["id"] == "p2"
        assert result["unchanged_count"] == 1

    def test_modified_items(self):
        prev = [{"id": "p1", "name": "A", "enabled": True}]
        curr = [{"id": "p1", "name": "A", "enabled": False}]
        result = diff_collection(prev, curr, "id")
        assert result["added"] == []
        assert result["removed"] == []
        assert len(result["modified"]) == 1
        assert result["modified"][0]["changes"]["enabled"]["old"] is True
        assert result["modified"][0]["changes"]["enabled"]["new"] is False

    def test_identical_items(self):
        items = [{"id": "p1", "name": "A", "enabled": True}]
        result = diff_collection(items, items, "id")
        assert result["added"] == []
        assert result["removed"] == []
        assert result["modified"] == []
        assert result["unchanged_count"] == 1


class TestDiffSnapshots:
    def test_detect_policy_added(self):
        result = diff_snapshots(SNAPSHOT_V1, SNAPSHOT_V2)
        policies = result["policies"]
        added_ids = [a["id"] for a in policies["added"]]
        assert "p3" in added_ids

    def test_detect_policy_removed(self):
        result = diff_snapshots(SNAPSHOT_V1, SNAPSHOT_V2)
        policies = result["policies"]
        removed_ids = [r["id"] for r in policies["removed"]]
        assert "p2" in removed_ids

    def test_detect_policy_modified(self):
        result = diff_snapshots(SNAPSHOT_V1, SNAPSHOT_V2)
        policies = result["policies"]
        modified_ids = [m["id"] for m in policies["modified"]]
        assert "p1" in modified_ids
        p1_mod = [m for m in policies["modified"] if m["id"] == "p1"][0]
        assert "enabled" in p1_mod["changes"]

    def test_detect_network_added(self):
        result = diff_snapshots(SNAPSHOT_V1, SNAPSHOT_V2)
        nets = result["networks"]
        added_ids = [a["id"] for a in nets["added"]]
        assert "n3" in added_ids

    def test_identical_snapshots(self):
        result = diff_snapshots(SNAPSHOT_V1, SNAPSHOT_V1)
        assert result["summary"]["has_changes"] is False
        assert result["summary"]["total_added"] == 0
        assert result["summary"]["total_removed"] == 0
        assert result["summary"]["total_modified"] == 0

    def test_summary_counts(self):
        result = diff_snapshots(SNAPSHOT_V1, SNAPSHOT_V2)
        summary = result["summary"]
        assert summary["has_changes"] is True
        assert summary["total_added"] >= 1  # p3 + n3
        assert summary["total_removed"] >= 1  # p2
        assert summary["total_modified"] >= 1  # p1

    def test_timestamps_preserved(self):
        result = diff_snapshots(SNAPSHOT_V1, SNAPSHOT_V2)
        assert result["previous_timestamp"] == SNAPSHOT_V1["timestamp"]
        assert result["current_timestamp"] == SNAPSHOT_V2["timestamp"]


class TestAutoLoadSnapshots:
    def test_auto_load_most_recent(self, tmp_path):
        """Test auto-loading two most recent snapshots from state-dir."""
        snap_dir = tmp_path / "firewall-snapshots"
        snap_dir.mkdir()
        (snap_dir / "2026-01-01T00-00-00.json").write_text(json.dumps(SNAPSHOT_V1))
        (snap_dir / "2026-01-02T00-00-00.json").write_text(json.dumps(SNAPSHOT_V2))

        previous, current = load_snapshot_pair(None, None, tmp_path)
        assert previous["timestamp"] == SNAPSHOT_V1["timestamp"]
        assert current["timestamp"] == SNAPSHOT_V2["timestamp"]

    def test_auto_load_insufficient_snapshots(self, tmp_path):
        """Test that fewer than 2 snapshots causes an error exit."""
        snap_dir = tmp_path / "firewall-snapshots"
        snap_dir.mkdir()
        (snap_dir / "2026-01-01T00-00-00.json").write_text(json.dumps(SNAPSHOT_V1))

        with pytest.raises(SystemExit):
            load_snapshot_pair(None, None, tmp_path)

    def test_explicit_file_paths(self, tmp_path):
        """Test loading explicit file paths."""
        f_prev = tmp_path / "prev.json"
        f_curr = tmp_path / "curr.json"
        f_prev.write_text(json.dumps(SNAPSHOT_V1))
        f_curr.write_text(json.dumps(SNAPSHOT_V2))

        previous, current = load_snapshot_pair(str(f_curr), str(f_prev), tmp_path)
        assert previous["timestamp"] == SNAPSHOT_V1["timestamp"]
        assert current["timestamp"] == SNAPSHOT_V2["timestamp"]

    def test_find_recent_snapshots_empty(self, tmp_path):
        """Test find_recent_snapshots with no directory."""
        assert find_recent_snapshots(tmp_path) == []


# ==============================================================================
# apply-template.py tests
# ==============================================================================


# Path to the real templates file.
_templates_path = _scripts_dir.parent / "references" / "policy-templates.yaml"


class TestApplyParseArgs:
    def test_defaults(self):
        args = apply_parse_args([])
        assert args.template is None
        assert args.params == []
        assert args.list_templates is False

    def test_list_flag(self):
        args = apply_parse_args(["--list"])
        assert args.list_templates is True

    def test_template_and_params(self):
        args = apply_parse_args(["--template", "iot-isolation", "--param", "a=1", "--param", "b=2"])
        assert args.template == "iot-isolation"
        assert args.params == ["a=1", "b=2"]


class TestLoadTemplates:
    def test_load_real_templates(self):
        """Test loading the actual policy-templates.yaml file."""
        templates = load_templates(_templates_path)
        assert len(templates) > 0
        names = get_template_names(templates)
        assert "iot-isolation" in names
        assert "guest-lockdown" in names

    def test_load_missing_file(self, tmp_path):
        """Test loading from a non-existent path returns empty."""
        templates = load_templates(tmp_path / "nonexistent.yaml")
        assert templates == []


class TestListTemplates:
    def test_list_real_templates(self):
        """Test listing templates includes name, description, required_params."""
        templates = load_templates(_templates_path)
        summaries = list_templates(templates)
        assert len(summaries) > 0
        for summary in summaries:
            assert "name" in summary
            assert "description" in summary
            assert "required_params" in summary
            assert isinstance(summary["required_params"], list)

    def test_iot_isolation_has_correct_required_params(self):
        """Test that iot-isolation template lists its required params (V2 zone-based)."""
        templates = load_templates(_templates_path)
        summaries = list_templates(templates)
        iot = [s for s in summaries if s["name"] == "iot-isolation"][0]
        assert "iot_zone_id" in iot["required_params"]
        assert "private_zone_id" in iot["required_params"]


class TestParseParams:
    def test_valid_params(self):
        result = parse_params(["key1=value1", "key2=value2"])
        assert result == {"key1": "value1", "key2": "value2"}

    def test_param_with_equals_in_value(self):
        result = parse_params(["key=val=ue"])
        assert result == {"key": "val=ue"}

    def test_invalid_param_exits(self):
        with pytest.raises(SystemExit):
            parse_params(["invalid_no_equals"])


class TestValidateParams:
    def test_all_provided(self):
        config = {"params": [
            {"name": "a", "required": True},
            {"name": "b", "required": True},
        ]}
        missing = validate_params(config, {"a": "1", "b": "2"})
        assert missing == []

    def test_missing_params(self):
        config = {"params": [
            {"name": "a", "required": True},
            {"name": "b", "required": True},
            {"name": "c", "required": True},
        ]}
        missing = validate_params(config, {"a": "1"})
        assert "b" in missing
        assert "c" in missing

    def test_no_required_params(self):
        config = {"params": [
            {"name": "x", "required": False},
        ]}
        missing = validate_params(config, {})
        assert missing == []

    def test_empty_params_list(self):
        config = {"params": []}
        missing = validate_params(config, {})
        assert missing == []


class TestSubstitute:
    def test_string_substitution(self):
        assert _substitute("Hello {name}", {"name": "World"}) == "Hello World"

    def test_multiple_substitutions(self):
        result = _substitute("{a} to {b}", {"a": "X", "b": "Y"})
        assert result == "X to Y"

    def test_missing_param_preserved(self):
        result = _substitute("{present} {missing}", {"present": "yes"})
        assert result == "yes {missing}"

    def test_dict_substitution(self):
        template = {"name": "Block {net}", "action": "drop"}
        result = _substitute(template, {"net": "IoT"})
        assert result == {"name": "Block IoT", "action": "drop"}

    def test_nested_substitution(self):
        template = {"outer": {"inner": "{val}"}}
        result = _substitute(template, {"val": "replaced"})
        assert result == {"outer": {"inner": "replaced"}}

    def test_list_substitution(self):
        template = ["{a}", "{b}", "literal"]
        result = _substitute(template, {"a": "X", "b": "Y"})
        assert result == ["X", "Y", "literal"]

    def test_non_string_passthrough(self):
        assert _substitute(42, {"a": "b"}) == 42
        assert _substitute(True, {"a": "b"}) is True


class TestApplyTemplate:
    def test_iot_isolation(self):
        templates = load_templates(_templates_path)
        config = get_template_by_name(templates, "iot-isolation")
        assert config is not None
        params = {
            "iot_zone_id": "iot-zone-id-123",
            "private_zone_id": "internal-zone-id-456",
        }
        result = apply_template("iot-isolation", config, params)

        # V2 zone-based payload (post-#210).
        assert result["preview"] is True
        assert result["tool"] == "unifi_create_firewall_policy"
        assert result["arguments"]["action"] == "REJECT"
        assert result["arguments"]["source"]["zone_id"] == "iot-zone-id-123"
        assert result["arguments"]["source"]["matching_target"] == "ANY"
        assert result["arguments"]["destination"]["zone_id"] == "internal-zone-id-456"
        assert result["arguments"]["destination"]["matching_target"] == "ANY"

    def test_guest_lockdown(self):
        templates = load_templates(_templates_path)
        config = get_template_by_name(templates, "guest-lockdown")
        assert config is not None
        params = {
            "guest_zone_id": "guest-zone-id-789",
            "private_zone_id": "internal-zone-id-456",
        }
        result = apply_template("guest-lockdown", config, params)

        # V2 zone-based payload (post-#210).
        assert result["preview"] is True
        assert result["tool"] == "unifi_create_firewall_policy"
        assert result["arguments"]["action"] == "REJECT"
        assert result["arguments"]["source"]["zone_id"] == "guest-zone-id-789"
        assert result["arguments"]["destination"]["zone_id"] == "internal-zone-id-456"

    def test_single_step_output_structure(self):
        """Verify single-step output structure matches the spec."""
        templates = load_templates(_templates_path)
        config = get_template_by_name(templates, "iot-isolation")
        assert config is not None
        params = {"iot_zone_id": "iot-zone", "private_zone_id": "internal-zone"}
        result = apply_template("iot-isolation", config, params)

        assert set(result.keys()) == {"tool", "arguments", "preview"}
        assert isinstance(result["arguments"], dict)
        assert result["preview"] is True

    def test_multi_step_template(self):
        """Test that multi-step templates (with 'rules') produce steps."""
        templates = load_templates(_templates_path)
        config = get_template_by_name(templates, "camera-isolation")
        assert config is not None
        params = {
            "camera_zone_id": "cam-zone",
            "internal_zone_id": "int-zone",
            "nvr_ips": '["192.168.50.10"]',
        }
        result = apply_template("camera-isolation", config, params)

        assert "steps" in result
        assert len(result["steps"]) == 2
        assert result["steps"][0]["step"] == 1
        assert result["steps"][1]["step"] == 2
        assert result["steps"][0]["preview"] is True
        assert result["steps"][1]["preview"] is True

    def test_unknown_template_not_found(self):
        """Test that an unknown template name returns None from lookup."""
        templates = load_templates(_templates_path)
        result = get_template_by_name(templates, "nonexistent-template")
        assert result is None

    def test_get_required_params(self):
        """Test extracting required params from a template config."""
        config = {
            "params": [
                {"name": "a", "required": True},
                {"name": "b", "required": False},
                {"name": "c", "required": True},
            ]
        }
        required = get_required_params(config)
        assert required == ["a", "c"]
