"""Tests for run-audit.py script."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# The script lives in the plugin's scripts/ directory — add it to sys.path for import.
_scripts_dir = Path(__file__).resolve().parent.parent.parent / (
    "plugins/unifi-network/skills/firewall-auditor/scripts"
)
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

# Import the module by filename (run-audit.py has a hyphen).
import importlib.util

_spec = importlib.util.spec_from_file_location("run_audit", _scripts_dir / "run-audit.py")
run_audit_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_audit_mod)
# Register so unittest.mock.patch() can resolve "run_audit.MCPClient".
sys.modules["run_audit"] = run_audit_mod

# Pull out the names we need.
parse_args = run_audit_mod.parse_args
run_audit = run_audit_mod.run_audit
main = run_audit_mod.main
format_human = run_audit_mod.format_human
check_segmentation = run_audit_mod.check_segmentation
check_egress = run_audit_mod.check_egress
check_hygiene = run_audit_mod.check_hygiene
check_topology = run_audit_mod.check_topology
score_findings = run_audit_mod.score_findings
overall_status = run_audit_mod.overall_status
load_history = run_audit_mod.load_history
save_history = run_audit_mod.save_history
compute_trend = run_audit_mod.compute_trend
build_recommendations = run_audit_mod.build_recommendations
CATEGORY_MAX = run_audit_mod.CATEGORY_MAX
_finding = run_audit_mod._finding


# ── Argument parsing tests ───────────────────────────────────────────────────


class TestParseArgs:
    def test_defaults(self):
        args = parse_args([])
        assert args.mcp_url is None
        assert args.output_format == "json"
        assert args.state_dir is None

    def test_mcp_url(self):
        args = parse_args(["--mcp-url", "http://myhost:4000"])
        assert args.mcp_url == "http://myhost:4000"

    def test_format_json(self):
        args = parse_args(["--format", "json"])
        assert args.output_format == "json"

    def test_format_human(self):
        args = parse_args(["--format", "human"])
        assert args.output_format == "human"

    def test_state_dir(self):
        args = parse_args(["--state-dir", "/tmp/my-state"])
        assert args.state_dir == "/tmp/my-state"

    def test_all_args(self):
        args = parse_args(["--mcp-url", "http://x:1234", "--format", "human", "--state-dir", "/tmp/s"])
        assert args.mcp_url == "http://x:1234"
        assert args.output_format == "human"
        assert args.state_dir == "/tmp/s"


# ── Segmentation check tests ────────────────────────────────────────────────


class TestCheckSegmentation:
    def test_no_iot_no_findings(self):
        """No IoT/guest networks means no segmentation findings."""
        networks = [
            {"_id": "n1", "name": "LAN", "purpose": "corporate"},
        ]
        findings = check_segmentation([], {}, networks, [])
        # SEG-01 and SEG-02 should not fire since there are no IoT/guest networks.
        seg_ids = {f["benchmark_id"] for f in findings}
        assert "SEG-01" not in seg_ids
        assert "SEG-02" not in seg_ids

    def test_iot_to_private_missing(self):
        """IoT network present but no blocking rule produces SEG-01."""
        networks = [
            {"_id": "n1", "name": "Main LAN", "purpose": "corporate"},
            {"_id": "n2", "name": "IoT Devices", "purpose": "corporate"},
        ]
        findings = check_segmentation([], {}, networks, [])
        seg01 = [f for f in findings if f["benchmark_id"] == "SEG-01"]
        assert len(seg01) == 1
        assert seg01[0]["severity"] == "critical"

    def test_guest_to_private_missing(self):
        """Guest network present but no blocking rule produces SEG-02."""
        networks = [
            {"_id": "n1", "name": "Main LAN", "purpose": "corporate"},
            {"_id": "n3", "name": "Guest WiFi", "purpose": "guest"},
        ]
        findings = check_segmentation([], {}, networks, [])
        seg02 = [f for f in findings if f["benchmark_id"] == "SEG-02"]
        assert len(seg02) == 1
        assert seg02[0]["severity"] == "critical"

    def test_iot_block_present(self):
        """If a drop rule blocks IoT to private, SEG-01 should not fire."""
        networks = [
            {"_id": "n1", "name": "Main LAN", "purpose": "corporate"},
            {"_id": "n2", "name": "IoT Devices", "purpose": "corporate"},
        ]
        policy_details = {
            "p1": {
                "enabled": True,
                "action": "drop",
                "source": {"matching_target": "network_id", "network_id": "n2", "zone_id": "lan"},
                "destination": {"matching_target": "network_id", "network_id": "n1", "zone_id": "lan"},
            }
        }
        findings = check_segmentation([], policy_details, networks, [])
        seg01 = [f for f in findings if f["benchmark_id"] == "SEG-01"]
        assert len(seg01) == 0

    def test_uncovered_network(self):
        """Networks with no firewall policy references get SEG-03."""
        networks = [
            {"_id": "n1", "name": "LAN", "purpose": "corporate"},
            {"_id": "n2", "name": "Servers", "purpose": "corporate"},
        ]
        # Policy details reference n1 only.
        policy_details = {
            "p1": {
                "enabled": True,
                "action": "accept",
                "source": {"network_id": "n1"},
                "destination": {},
            }
        }
        findings = check_segmentation([], policy_details, networks, [])
        seg03 = [f for f in findings if f["benchmark_id"] == "SEG-03"]
        assert any("Servers" in f["message"] for f in seg03)

    def test_wan_network_excluded_from_seg03(self):
        """WAN purpose networks should not trigger SEG-03."""
        networks = [
            {"_id": "n1", "name": "WAN", "purpose": "wan"},
        ]
        findings = check_segmentation([], {}, networks, [])
        seg03 = [f for f in findings if f["benchmark_id"] == "SEG-03"]
        assert len(seg03) == 0


# ── Egress check tests ──────────────────────────────────────────────────────


class TestCheckEgress:
    def test_no_high_risk_networks(self):
        """No IoT/guest networks means no egress findings."""
        networks = [{"_id": "n1", "name": "LAN", "purpose": "corporate"}]
        findings = check_egress([], {}, networks)
        assert len(findings) == 0

    def test_iot_without_egress_filter(self):
        """IoT network without egress filter triggers EGR-01."""
        networks = [
            {"_id": "n1", "name": "IoT VLAN", "purpose": "corporate"},
        ]
        findings = check_egress([], {}, networks)
        egr01 = [f for f in findings if f["benchmark_id"] == "EGR-01"]
        assert len(egr01) == 1
        assert egr01[0]["severity"] == "warning"

    def test_iot_with_egress_filter(self):
        """IoT network with proper egress filtering should not fire EGR-01."""
        networks = [{"_id": "n1", "name": "IoT VLAN", "purpose": "corporate"}]
        policy_details = {
            "p1": {
                "enabled": True,
                "action": "drop",
                "source": {"matching_target": "network_id", "network_id": "n1"},
                "destination": {"zone_id": "wan"},
            }
        }
        findings = check_egress([], policy_details, networks)
        egr01 = [f for f in findings if f["benchmark_id"] == "EGR-01"]
        assert len(egr01) == 0


# ── Hygiene check tests ─────────────────────────────────────────────────────


class TestCheckHygiene:
    def test_disabled_duplicate_detected(self):
        """Disabled rule matching enabled rule name triggers HYG-01."""
        policies = [
            {"id": "p1", "name": "Block Bad Traffic", "enabled": True},
            {"id": "p2", "name": "Block Bad Traffic", "enabled": False},
        ]
        findings = check_hygiene(policies, {}, [], [])
        hyg01 = [f for f in findings if f["benchmark_id"] == "HYG-01"]
        assert len(hyg01) == 1

    def test_conflict_detection(self):
        """Same-traffic rules with different actions trigger HYG-02."""
        policies = [
            {"id": "p1", "name": "Allow LAN", "enabled": True, "ruleset": "LAN_IN", "rule_index": 100},
            {"id": "p2", "name": "Block LAN", "enabled": True, "ruleset": "LAN_IN", "rule_index": 200},
        ]
        policy_details = {
            "p1": {
                "name": "Allow LAN",
                "enabled": True,
                "action": "accept",
                "source": {"zone_id": "lan", "matching_target": "zone"},
                "destination": {"zone_id": "lan", "matching_target": "zone"},
            },
            "p2": {
                "name": "Block LAN",
                "enabled": True,
                "action": "drop",
                "source": {"zone_id": "lan", "matching_target": "zone"},
                "destination": {"zone_id": "lan", "matching_target": "zone"},
            },
        }
        findings = check_hygiene(policies, policy_details, [], [])
        hyg02 = [f for f in findings if f["benchmark_id"] == "HYG-02"]
        assert len(hyg02) == 1
        assert hyg02[0]["severity"] == "critical"

    def test_stale_network_reference(self):
        """Policy referencing a deleted network triggers HYG-03."""
        policies = [{"id": "p1", "name": "Stale Rule", "enabled": True}]
        policy_details = {
            "p1": {
                "name": "Stale Rule",
                "source": {"network_id": "deleted_net"},
                "destination": {},
            }
        }
        networks = [{"_id": "n1", "name": "LAN"}]
        findings = check_hygiene(policies, policy_details, networks, [])
        hyg03 = [f for f in findings if f["benchmark_id"] == "HYG-03"]
        assert len(hyg03) == 1
        assert "deleted_net" in hyg03[0]["message"]

    def test_stale_ip_group_reference(self):
        """Policy referencing a deleted IP group triggers HYG-03."""
        policies = [{"id": "p1", "name": "Stale Group", "enabled": True}]
        policy_details = {
            "p1": {
                "name": "Stale Group",
                "source": {"ip_group_id": "deleted_group"},
                "destination": {},
            }
        }
        findings = check_hygiene(policies, policy_details, [], [])
        hyg03 = [f for f in findings if f["benchmark_id"] == "HYG-03"]
        assert len(hyg03) == 1
        assert "deleted_group" in hyg03[0]["message"]

    def test_unnamed_rule(self):
        """Rules with blank or default names trigger HYG-04."""
        policies = [
            {"id": "p1", "name": "", "enabled": True},
            {"id": "p2", "name": "Unnamed", "enabled": True},
        ]
        findings = check_hygiene(policies, {}, [], [])
        hyg04 = [f for f in findings if f["benchmark_id"] == "HYG-04"]
        assert len(hyg04) == 2

    def test_ordering_issue(self):
        """Broad accept before specific drop triggers HYG-05."""
        policies = [
            {"id": "p1", "name": "Allow All LAN", "enabled": True, "ruleset": "LAN_IN", "rule_index": 100},
            {"id": "p2", "name": "Block IoT", "enabled": True, "ruleset": "LAN_IN", "rule_index": 200},
        ]
        policy_details = {
            "p1": {
                "name": "Allow All LAN",
                "action": "accept",
                "source": {"zone_id": "lan", "matching_target": "zone"},
                "destination": {"zone_id": "lan", "matching_target": "zone"},
            },
            "p2": {
                "name": "Block IoT",
                "action": "drop",
                "source": {"zone_id": "lan", "matching_target": "network_id", "network_id": "n2"},
                "destination": {"zone_id": "lan", "matching_target": "zone"},
            },
        }
        findings = check_hygiene(policies, policy_details, [], [])
        hyg05 = [f for f in findings if f["benchmark_id"] == "HYG-05"]
        assert len(hyg05) == 1
        assert hyg05[0]["severity"] == "warning"


# ── Topology check tests ────────────────────────────────────────────────────


class TestCheckTopology:
    def test_no_devices(self):
        assert check_topology([]) == []

    def test_offline_device(self):
        devices = [{"name": "AP-Down", "state": 0, "mac": "aa:bb:cc:dd:ee:01"}]
        findings = check_topology(devices)
        top01 = [f for f in findings if f["benchmark_id"] == "TOP-01"]
        assert len(top01) == 1
        assert "AP-Down" in top01[0]["message"]

    def test_upgradeable_device(self):
        devices = [{"name": "Switch", "state": 1, "mac": "aa:bb:cc:dd:ee:02", "upgradeable": True}]
        findings = check_topology(devices)
        top02 = [f for f in findings if f["benchmark_id"] == "TOP-02"]
        assert len(top02) == 1
        assert top02[0]["severity"] == "info"


# ── Scoring tests ────────────────────────────────────────────────────────────


class TestScoring:
    def test_no_findings_max_score(self):
        assert score_findings([]) == CATEGORY_MAX

    def test_critical_deduction(self):
        findings = [_finding("X", "critical", "bad")]
        assert score_findings(findings) == CATEGORY_MAX - 5

    def test_warning_deduction(self):
        findings = [_finding("X", "warning", "meh")]
        assert score_findings(findings) == CATEGORY_MAX - 2

    def test_info_deduction(self):
        findings = [_finding("X", "info", "fyi")]
        assert score_findings(findings) == CATEGORY_MAX - 1

    def test_floor_at_zero(self):
        """Score cannot go below 0."""
        findings = [_finding("X", "critical", f"bad {i}") for i in range(10)]
        assert score_findings(findings) == 0

    def test_mixed_severities(self):
        findings = [
            _finding("A", "critical", "crit"),
            _finding("B", "warning", "warn"),
            _finding("C", "info", "info"),
        ]
        expected = CATEGORY_MAX - 5 - 2 - 1
        assert score_findings(findings) == expected

    def test_overall_status_healthy(self):
        assert overall_status(80) == "healthy"
        assert overall_status(100) == "healthy"

    def test_overall_status_needs_attention(self):
        assert overall_status(79) == "needs_attention"
        assert overall_status(60) == "needs_attention"

    def test_overall_status_critical(self):
        assert overall_status(59) == "critical"
        assert overall_status(0) == "critical"


# ── History and trend tests ──────────────────────────────────────────────────


class TestHistory:
    def test_load_missing(self, tmp_path):
        assert load_history(tmp_path) == []

    def test_save_and_load(self, tmp_path):
        entries = [{"timestamp": "2026-01-01T00:00:00Z", "overall_score": 72}]
        save_history(tmp_path, entries)
        loaded = load_history(tmp_path)
        assert loaded == entries

    def test_load_corrupted(self, tmp_path):
        (tmp_path / "audit-history.json").write_text("not json!")
        assert load_history(tmp_path) == []

    def test_trend_no_history(self):
        trend = compute_trend([], 80)
        assert trend["previous_score"] is None
        assert trend["change"] is None

    def test_trend_positive(self):
        history = [{"overall_score": 65}]
        trend = compute_trend(history, 72)
        assert trend["previous_score"] == 65
        assert trend["change"] == "+7"

    def test_trend_negative(self):
        history = [{"overall_score": 80}]
        trend = compute_trend(history, 70)
        assert trend["previous_score"] == 80
        assert trend["change"] == "-10"

    def test_trend_no_change(self):
        history = [{"overall_score": 72}]
        trend = compute_trend(history, 72)
        assert trend["change"] == "+0"

    def test_save_trims_to_50(self, tmp_path):
        entries = [{"overall_score": i} for i in range(100)]
        save_history(tmp_path, entries)
        loaded = load_history(tmp_path)
        assert len(loaded) == 50
        assert loaded[0]["overall_score"] == 50


# ── Mock MCP client for integration tests ────────────────────────────────────


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


CLEAN_TOOL_RESULTS = {
    "unifi_list_firewall_policies": {
        "success": True,
        "policies": [
            {
                "id": "p1",
                "name": "Block IoT to Private",
                "enabled": True,
                "action": "drop",
                "rule_index": 100,
                "ruleset": "LAN_IN",
                "description": "Isolate IoT",
            },
        ],
    },
    "unifi_list_firewall_zones": {
        "success": True,
        "zones": [{"_id": "z1", "name": "LAN"}, {"_id": "z2", "name": "WAN"}],
    },
    "unifi_list_networks": {
        "success": True,
        "networks": [
            {"_id": "n1", "name": "Main LAN", "purpose": "corporate", "vlan_enabled": False},
            {"_id": "n2", "name": "IoT VLAN", "purpose": "corporate", "vlan_enabled": True, "vlan": 20},
        ],
    },
    "unifi_list_firewall_groups": {
        "success": True,
        "groups": [{"_id": "g1", "name": "Servers"}],
    },
    "unifi_list_devices": {
        "success": True,
        "devices": [
            {"name": "Gateway", "mac": "aa:00:00:00:00:01", "state": 1, "type": "ugw", "model": "UDM-Pro"},
            {"name": "AP-LR", "mac": "aa:00:00:00:00:02", "state": 1, "type": "uap", "model": "U6-LR"},
            {"name": "Switch24", "mac": "aa:00:00:00:00:03", "state": 1, "type": "usw", "model": "USW-24"},
        ],
    },
    "detail_p1": {
        "success": True,
        "details": {
            "_id": "p1",
            "name": "Block IoT to Private",
            "enabled": True,
            "action": "drop",
            "source": {"matching_target": "network_id", "network_id": "n2", "zone_id": "lan"},
            "destination": {"matching_target": "network_id", "network_id": "n1", "zone_id": "lan"},
        },
    },
}


def test_run_audit_clean(tmp_path):
    """Test full audit with a reasonably clean configuration."""
    mock_client = _make_mock_client(CLEAN_TOOL_RESULTS)

    with patch(f"{run_audit_mod.__name__}.MCPClient", return_value=mock_client):
        result = run_audit("http://localhost:3000", tmp_path)

    assert result["success"] is True
    assert "overall_score" in result
    assert "overall_status" in result
    assert "categories" in result
    assert "trend" in result
    assert "summary" in result
    assert "recommendations" in result
    assert result["summary"]["total_policies"] == 1
    assert result["summary"]["networks"] == 2
    assert result["summary"]["devices"] == 3


def test_run_audit_setup_required(tmp_path):
    """Test that unreachable server returns setup_required error."""
    mock_client = _make_mock_client({}, ready=False)

    with patch(f"{run_audit_mod.__name__}.MCPClient", return_value=mock_client):
        result = run_audit("http://localhost:3000", tmp_path)

    assert result["success"] is False
    assert result["error"] == "setup_required"


def test_run_audit_saves_history(tmp_path):
    """Running the audit should save history."""
    mock_client = _make_mock_client(CLEAN_TOOL_RESULTS)

    with patch(f"{run_audit_mod.__name__}.MCPClient", return_value=mock_client):
        run_audit("http://localhost:3000", tmp_path)

    history_path = tmp_path / "audit-history.json"
    assert history_path.exists()
    history = json.loads(history_path.read_text())
    assert len(history) == 1
    assert "overall_score" in history[0]


def test_run_audit_trend_on_second_run(tmp_path):
    """Second run should include trend data."""
    mock_client = _make_mock_client(CLEAN_TOOL_RESULTS)

    with patch(f"{run_audit_mod.__name__}.MCPClient", return_value=mock_client):
        first = run_audit("http://localhost:3000", tmp_path)

    assert first["trend"]["previous_score"] is None

    with patch(f"{run_audit_mod.__name__}.MCPClient", return_value=mock_client):
        second = run_audit("http://localhost:3000", tmp_path)

    assert second["trend"]["previous_score"] is not None
    assert second["trend"]["change"] is not None


def test_run_audit_with_issues(tmp_path):
    """Test audit detecting multiple issue categories."""
    # Policies with conflicts.
    tool_results = {
        "unifi_list_firewall_policies": {
            "success": True,
            "policies": [
                {"id": "p1", "name": "Allow LAN", "enabled": True, "action": "accept", "rule_index": 100, "ruleset": "LAN_IN"},
                {"id": "p2", "name": "Block LAN", "enabled": True, "action": "drop", "rule_index": 200, "ruleset": "LAN_IN"},
            ],
        },
        "unifi_list_firewall_zones": {"success": True, "zones": []},
        "unifi_list_networks": {
            "success": True,
            "networks": [
                {"_id": "n1", "name": "LAN", "purpose": "corporate"},
                {"_id": "n2", "name": "IoT", "purpose": "corporate"},
                {"_id": "n3", "name": "Guest WiFi", "purpose": "guest"},
            ],
        },
        "unifi_list_firewall_groups": {"success": True, "groups": []},
        "unifi_list_devices": {
            "success": True,
            "devices": [
                {"name": "AP-Down", "mac": "aa:00:00:00:00:01", "state": 0, "type": "uap"},
            ],
        },
        "detail_p1": {
            "success": True,
            "details": {
                "name": "Allow LAN",
                "enabled": True,
                "action": "accept",
                "source": {"zone_id": "lan", "matching_target": "zone"},
                "destination": {"zone_id": "lan", "matching_target": "zone"},
            },
        },
        "detail_p2": {
            "success": True,
            "details": {
                "name": "Block LAN",
                "enabled": True,
                "action": "drop",
                "source": {"zone_id": "lan", "matching_target": "zone"},
                "destination": {"zone_id": "lan", "matching_target": "zone"},
            },
        },
    }
    mock_client = _make_mock_client(tool_results)

    with patch(f"{run_audit_mod.__name__}.MCPClient", return_value=mock_client):
        result = run_audit("http://localhost:3000", tmp_path)

    assert result["success"] is True
    # Should have critical findings (SEG-01, SEG-02 missing, conflict).
    assert len(result["critical_findings"]) > 0
    # Overall score should be reduced.
    assert result["overall_score"] < 100


def test_output_structure(tmp_path):
    """Validate that output has all required top-level keys."""
    mock_client = _make_mock_client(CLEAN_TOOL_RESULTS)

    with patch(f"{run_audit_mod.__name__}.MCPClient", return_value=mock_client):
        result = run_audit("http://localhost:3000", tmp_path)

    required_keys = {
        "success",
        "timestamp",
        "overall_score",
        "overall_status",
        "categories",
        "trend",
        "critical_findings",
        "summary",
        "recommendations",
    }
    assert required_keys.issubset(set(result.keys()))

    # Validate category structure.
    for cat_name in ("segmentation", "egress_control", "rule_hygiene", "topology"):
        assert cat_name in result["categories"]
        cat = result["categories"][cat_name]
        assert "score" in cat
        assert "max" in cat
        assert cat["max"] == CATEGORY_MAX
        assert "findings" in cat
        assert isinstance(cat["findings"], list)

    # Validate summary.
    summary = result["summary"]
    for key in ("total_policies", "enabled", "disabled", "networks", "devices"):
        assert key in summary

    # Validate trend.
    assert "previous_score" in result["trend"]
    assert "change" in result["trend"]

    assert isinstance(result["critical_findings"], list)
    assert isinstance(result["recommendations"], list)


# ── Human-readable format tests ──────────────────────────────────────────────


def test_human_format(tmp_path):
    """Test human-readable output contains expected sections."""
    mock_client = _make_mock_client(CLEAN_TOOL_RESULTS)

    with patch(f"{run_audit_mod.__name__}.MCPClient", return_value=mock_client):
        result = run_audit("http://localhost:3000", tmp_path)

    text = format_human(result)
    assert "Firewall Audit Report" in text
    assert "Score:" in text
    assert "Policies:" in text
    assert "Recommendations" in text


# ── Recommendations tests ────────────────────────────────────────────────────


class TestRecommendations:
    def test_no_findings_clean_message(self):
        categories = {
            "segmentation": {"findings": []},
            "egress_control": {"findings": []},
            "rule_hygiene": {"findings": []},
            "topology": {"findings": []},
        }
        recs = build_recommendations(categories)
        assert any("no issues" in r.lower() for r in recs)

    def test_critical_first(self):
        categories = {
            "segmentation": {"findings": [_finding("SEG-01", "critical", "Critical issue")]},
            "rule_hygiene": {"findings": [_finding("HYG-01", "info", "Minor issue")]},
            "egress_control": {"findings": []},
            "topology": {"findings": []},
        }
        recs = build_recommendations(categories)
        assert "SEG-01" in recs[0]

    def test_fix_tool_included(self):
        categories = {
            "segmentation": {
                "findings": [
                    _finding("SEG-01", "critical", "Missing block", {"tool": "unifi_create_firewall_policy", "params": {}})
                ]
            },
            "egress_control": {"findings": []},
            "rule_hygiene": {"findings": []},
            "topology": {"findings": []},
        }
        recs = build_recommendations(categories)
        assert "unifi_create_firewall_policy" in recs[0]
