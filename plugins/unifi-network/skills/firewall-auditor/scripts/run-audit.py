#!/usr/bin/env python3
"""Run a comprehensive firewall and topology audit via MCP tools.

Checks firewall policies against security benchmarks, analyzes network
topology, scores results, and tracks trends over time.

Usage:
    python run-audit.py [--mcp-url URL] [--format json|human] [--state-dir DIR]
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow importing sibling modules when run as a script.
_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from config import get_server_url, get_state_dir  # noqa: E402
from mcp_client import MCPClient, MCPConnectionError, MCPToolError  # noqa: E402

logger = logging.getLogger("run-audit")

HISTORY_FILENAME = "audit-history.json"

# Severity deduction weights.
SEVERITY_DEDUCTIONS = {
    "critical": 5,
    "warning": 2,
    "info": 1,
}

CATEGORY_MAX = 25


# ── Argument parsing ─────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit UniFi firewall policies via MCP.")
    parser.add_argument(
        "--mcp-url",
        default=None,
        help="MCP server URL (default: auto-detect from env / localhost:3000)",
    )
    parser.add_argument(
        "--format",
        choices=["json", "human"],
        default="json",
        dest="output_format",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--state-dir",
        default=None,
        help="Directory for audit history state files (default: auto-detect)",
    )
    return parser.parse_args(argv)


# ── Data extraction helpers ──────────────────────────────────────────────────


def _extract_data(result: dict) -> Any:
    """Extract the data payload from an MCP tool result."""
    if not result.get("success", False):
        return None
    return result.get("data")


def _extract_list(result: dict, key: str) -> list:
    """Extract a list payload from an MCP tool result by key."""
    if not result.get("success", False):
        return []
    # Some tools nest under a key, others return data directly.
    val = result.get(key, result.get("data"))
    if isinstance(val, list):
        return val
    return []


# ── Finding builder ──────────────────────────────────────────────────────────


def _finding(
    benchmark_id: str,
    severity: str,
    message: str,
    fix: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a structured finding dict."""
    f: dict[str, Any] = {
        "benchmark_id": benchmark_id,
        "severity": severity,
        "message": message,
    }
    if fix:
        f["fix"] = fix
    return f


# ── Segmentation checks ─────────────────────────────────────────────────────


def check_segmentation(
    policies: list[dict],
    policy_details: dict[str, dict],
    networks: list[dict],
    zones: list[dict],
) -> list[dict]:
    """Check for inter-VLAN isolation and per-VLAN explicit policies."""
    findings: list[dict] = []

    # Identify VLANs by purpose / naming conventions.
    iot_networks = [n for n in networks if _is_iot_network(n)]
    guest_networks = [n for n in networks if _is_guest_network(n)]
    private_networks = [n for n in networks if _is_private_network(n)]

    # Build sets of network IDs that have *any* enabled policy referencing them.
    covered_network_ids: set[str] = set()
    for pid, detail in policy_details.items():
        if not detail.get("enabled", True):
            continue
        for direction in ("source", "destination"):
            ep = detail.get(direction, {})
            if isinstance(ep, dict):
                nid = ep.get("network_id")
                if nid:
                    covered_network_ids.add(nid)

    # SEG-01: IoT → private isolation.
    has_iot_to_private_block = _has_cross_vlan_block(
        policy_details, iot_networks, private_networks
    )
    if iot_networks and private_networks and not has_iot_to_private_block:
        findings.append(
            _finding(
                "SEG-01",
                "critical",
                "No rule blocking IoT VLAN traffic to private networks.",
                {
                    "tool": "unifi_create_firewall_policy",
                    "params": {
                        "name": "Block IoT to Internal",
                        "action": "REJECT",
                        "source": {
                            "zone_id": "<iot_zone_id>",
                            "matching_target": "ANY",
                        },
                        "destination": {
                            "zone_id": "<internal_zone_id>",
                            "matching_target": "ANY",
                        },
                    },
                    "_note": (
                        "Resolve <iot_zone_id> / <internal_zone_id> via "
                        "unifi_list_firewall_zones before applying."
                    ),
                },
            )
        )

    # SEG-02: Guest → private isolation.
    has_guest_to_private_block = _has_cross_vlan_block(
        policy_details, guest_networks, private_networks
    )
    if guest_networks and private_networks and not has_guest_to_private_block:
        findings.append(
            _finding(
                "SEG-02",
                "critical",
                "No rule blocking guest VLAN traffic to private networks.",
                {
                    "tool": "unifi_create_firewall_policy",
                    "params": {
                        "name": "Block Guest to Internal",
                        "action": "REJECT",
                        "source": {
                            "zone_id": "<guest_zone_id>",
                            "matching_target": "ANY",
                        },
                        "destination": {
                            "zone_id": "<internal_zone_id>",
                            "matching_target": "ANY",
                        },
                    },
                    "_note": (
                        "Resolve <guest_zone_id> / <internal_zone_id> via "
                        "unifi_list_firewall_zones before applying."
                    ),
                },
            )
        )

    # SEG-03: Each VLAN should have at least one explicit policy.
    for net in networks:
        nid = net.get("_id", "")
        name = net.get("name", "unknown")
        if net.get("purpose") == "wan":
            continue
        if nid and nid not in covered_network_ids:
            findings.append(
                _finding(
                    "SEG-03",
                    "warning",
                    f"Network '{name}' (ID: {nid}) has no explicit firewall policies referencing it.",
                )
            )

    return findings


def _is_iot_network(net: dict) -> bool:
    name = (net.get("name") or "").lower()
    return "iot" in name


def _is_guest_network(net: dict) -> bool:
    name = (net.get("name") or "").lower()
    purpose = (net.get("purpose") or "").lower()
    return "guest" in name or purpose == "guest"


def _is_private_network(net: dict) -> bool:
    name = (net.get("name") or "").lower()
    purpose = (net.get("purpose") or "").lower()
    if purpose == "wan":
        return False
    if _is_iot_network({"name": name}) or _is_guest_network({"name": name, "purpose": purpose}):
        return False
    return True


def _has_cross_vlan_block(
    policy_details: dict[str, dict],
    src_networks: list[dict],
    dst_networks: list[dict],
) -> bool:
    """Check if any enabled drop/reject policy blocks src→dst."""
    src_ids = {n.get("_id") for n in src_networks}
    dst_ids = {n.get("_id") for n in dst_networks}

    for detail in policy_details.values():
        if not detail.get("enabled", True):
            continue
        action = (detail.get("action") or "").lower()
        if action not in ("drop", "reject"):
            continue
        src_ep = detail.get("source", {})
        dst_ep = detail.get("destination", {})
        if not isinstance(src_ep, dict) or not isinstance(dst_ep, dict):
            continue
        src_nid = src_ep.get("network_id")
        dst_nid = dst_ep.get("network_id")
        # Direct network-to-network block.
        if src_nid in src_ids and dst_nid in dst_ids:
            return True
        # Zone-level block also counts (less precise but still effective).
        src_zone = src_ep.get("zone_id", "")
        dst_zone = dst_ep.get("zone_id", "")
        src_target = src_ep.get("matching_target", "")
        dst_target = dst_ep.get("matching_target", "")
        if src_target == "zone" and dst_target == "zone" and src_zone and dst_zone:
            return True
    return False


# ── Egress checks ────────────────────────────────────────────────────────────


def check_egress(
    policies: list[dict],
    policy_details: dict[str, dict],
    networks: list[dict],
) -> list[dict]:
    """Check for outbound filtering on IoT / guest VLANs."""
    findings: list[dict] = []

    iot_networks = [n for n in networks if _is_iot_network(n)]
    guest_networks = [n for n in networks if _is_guest_network(n)]
    high_risk = iot_networks + guest_networks

    for net in high_risk:
        nid = net.get("_id", "")
        name = net.get("name", "unknown")
        has_egress = False

        for detail in policy_details.values():
            if not detail.get("enabled", True):
                continue
            action = (detail.get("action") or "").lower()
            if action not in ("drop", "reject"):
                continue
            src_ep = detail.get("source", {})
            dst_ep = detail.get("destination", {})
            if not isinstance(src_ep, dict) or not isinstance(dst_ep, dict):
                continue
            # Check if source references this network and destination is WAN.
            src_nid = src_ep.get("network_id")
            dst_zone = (dst_ep.get("zone_id") or "").lower()
            if src_nid == nid and dst_zone == "wan":
                has_egress = True
                break
            # Also check source zone-level references.
            src_target = src_ep.get("matching_target", "")
            if src_target == "network_id" and src_nid == nid:
                has_egress = True
                break

        if not has_egress:
            findings.append(
                _finding(
                    "EGR-01",
                    "warning",
                    f"No egress filtering for high-risk network '{name}' — unrestricted outbound access.",
                    {
                        "tool": "unifi_create_firewall_policy",
                        "params": {
                            "name": f"Restrict {name} Egress",
                            "action": "BLOCK",
                            "source": {
                                "zone_id": "<source_zone_id>",
                                "matching_target": "NETWORK",
                                "matching_target_type": "OBJECT",
                                "network_ids": [nid],
                            },
                            "destination": {
                                "zone_id": "<external_zone_id>",
                                "matching_target": "ANY",
                            },
                        },
                        "_note": (
                            "Resolve <source_zone_id> / <external_zone_id> via "
                            "unifi_list_firewall_zones before applying."
                        ),
                    },
                )
            )

    return findings


# ── Rule hygiene checks ──────────────────────────────────────────────────────


def check_hygiene(
    policies: list[dict],
    policy_details: dict[str, dict],
    networks: list[dict],
    firewall_groups: list[dict],
) -> list[dict]:
    """Check for conflicts, redundancies, stale references, naming, ordering."""
    findings: list[dict] = []
    network_ids = {n.get("_id") for n in networks}
    firewall_group_ids = {g.get("_id") for g in firewall_groups}

    enabled_policies = [p for p in policies if p.get("enabled")]
    disabled_policies = [p for p in policies if not p.get("enabled")]

    # HYG-01: Disabled rules that duplicate enabled ones.
    enabled_names = {(p.get("name") or "").lower() for p in enabled_policies}
    for dp in disabled_policies:
        dname = (dp.get("name") or "").lower()
        if dname and dname in enabled_names:
            findings.append(
                _finding(
                    "HYG-01",
                    "info",
                    f"Disabled policy '{dp.get('name')}' duplicates an enabled rule by name.",
                    {
                        "tool": "unifi_toggle_firewall_policy",
                        "params": {"policy_id": dp.get("id"), "confirm": False},
                    },
                )
            )

    # HYG-02: Conflicting actions on same ruleset + similar index range.
    _check_conflicts(enabled_policies, policy_details, findings)

    # HYG-03: Stale references — networks or IP groups that don't exist.
    for pid, detail in policy_details.items():
        pname = detail.get("name", pid)
        for direction in ("source", "destination"):
            ep = detail.get(direction, {})
            if not isinstance(ep, dict):
                continue
            ref_nid = ep.get("network_id")
            if ref_nid and ref_nid not in network_ids:
                findings.append(
                    _finding(
                        "HYG-03",
                        "warning",
                        f"Policy '{pname}' references non-existent network ID '{ref_nid}' in {direction}.",
                    )
                )
            ref_gid = ep.get("ip_group_id")
            if ref_gid and ref_gid not in firewall_group_ids:
                findings.append(
                    _finding(
                        "HYG-03",
                        "warning",
                        f"Policy '{pname}' references non-existent IP group ID '{ref_gid}' in {direction}.",
                    )
                )

    # HYG-04: Unnamed or default-named rules.
    for p in policies:
        name = p.get("name") or ""
        if not name.strip() or name.strip().lower() in ("", "unnamed", "untitled", "new rule", "new policy"):
            findings.append(
                _finding(
                    "HYG-04",
                    "info",
                    f"Policy ID '{p.get('id')}' has a missing or default name.",
                    {
                        "tool": "unifi_update_firewall_policy",
                        "params": {"policy_id": p.get("id"), "update_data": {"name": "TODO: descriptive name"}},
                    },
                )
            )

    # HYG-05: Index ordering — broad accept rules before specific drop rules.
    _check_ordering(enabled_policies, policy_details, findings)

    return findings


def _check_conflicts(
    enabled_policies: list[dict],
    policy_details: dict[str, dict],
    findings: list[dict],
) -> None:
    """Detect rules with same traffic match but different actions."""
    by_ruleset: dict[str, list[dict]] = {}
    for p in enabled_policies:
        rs = p.get("ruleset", "")
        by_ruleset.setdefault(rs, []).append(p)

    for rs, group in by_ruleset.items():
        for i, p1 in enumerate(group):
            for p2 in group[i + 1 :]:
                d1 = policy_details.get(p1.get("id", ""), {})
                d2 = policy_details.get(p2.get("id", ""), {})
                if not d1 or not d2:
                    continue
                if _same_traffic_match(d1, d2) and d1.get("action") != d2.get("action"):
                    findings.append(
                        _finding(
                            "HYG-02",
                            "critical",
                            (
                                f"Conflict in ruleset '{rs}': "
                                f"'{d1.get('name')}' ({d1.get('action')}) vs "
                                f"'{d2.get('name')}' ({d2.get('action')}) match similar traffic."
                            ),
                        )
                    )


def _same_traffic_match(d1: dict, d2: dict) -> bool:
    """Rough check: same source/destination zone or network."""
    for direction in ("source", "destination"):
        ep1 = d1.get(direction, {})
        ep2 = d2.get(direction, {})
        if not isinstance(ep1, dict) or not isinstance(ep2, dict):
            return False
        # Compare zone_id and network_id.
        if ep1.get("zone_id") != ep2.get("zone_id"):
            return False
        if ep1.get("network_id") != ep2.get("network_id"):
            return False
        if ep1.get("matching_target") != ep2.get("matching_target"):
            return False
    return True


def _check_ordering(
    enabled_policies: list[dict],
    policy_details: dict[str, dict],
    findings: list[dict],
) -> None:
    """Detect broad accept rules placed before more specific drop/reject rules."""
    by_ruleset: dict[str, list[dict]] = {}
    for p in enabled_policies:
        rs = p.get("ruleset", "")
        by_ruleset.setdefault(rs, []).append(p)

    for rs, group in by_ruleset.items():
        sorted_group = sorted(group, key=lambda x: x.get("rule_index", 0))
        for i, p1 in enumerate(sorted_group):
            d1 = policy_details.get(p1.get("id", ""), {})
            if (d1.get("action") or "").lower() != "accept":
                continue
            # Check if a more specific drop/reject comes after.
            for p2 in sorted_group[i + 1 :]:
                d2 = policy_details.get(p2.get("id", ""), {})
                if (d2.get("action") or "").lower() in ("drop", "reject"):
                    # Heuristic: if the accept has broader matching_target, it might shadow.
                    src1 = d1.get("source", {})
                    src2 = d2.get("source", {})
                    if isinstance(src1, dict) and isinstance(src2, dict):
                        if (
                            src1.get("matching_target") == "zone"
                            and src2.get("matching_target") in ("network_id", "ip_group_id", "client_macs")
                            and src1.get("zone_id") == src2.get("zone_id")
                        ):
                            findings.append(
                                _finding(
                                    "HYG-05",
                                    "warning",
                                    (
                                        f"Ordering issue in '{rs}': broad accept '{d1.get('name')}' "
                                        f"(index {p1.get('rule_index')}) may shadow specific "
                                        f"'{d2.get('name')}' (index {p2.get('rule_index')})."
                                    ),
                                )
                            )


# ── Topology checks ─────────────────────────────────────────────────────────


def check_topology(devices: list[dict]) -> list[dict]:
    """Check device health: offline, firmware updates, VLAN consistency."""
    findings: list[dict] = []

    if not devices:
        return findings

    # TOP-01: Offline devices.
    for dev in devices:
        status = dev.get("status", dev.get("state", ""))
        name = dev.get("name", dev.get("mac", "unknown"))
        if isinstance(status, str):
            status = status.lower()
        if status in (0, "offline", "disconnected"):
            findings.append(
                _finding(
                    "TOP-01",
                    "warning",
                    f"Device '{name}' is offline.",
                )
            )

    # TOP-02: Firmware updates available.
    for dev in devices:
        name = dev.get("name", dev.get("mac", "unknown"))
        if dev.get("upgradeable") or dev.get("upgrade_available"):
            findings.append(
                _finding(
                    "TOP-02",
                    "info",
                    f"Device '{name}' has a firmware update available.",
                    {
                        "tool": "unifi_upgrade_device",
                        "params": {"device_mac": dev.get("mac", "")},
                    },
                )
            )

    # TOP-03: Switch VLAN consistency — look for ports with unexpected VLAN assignments.
    switches = [d for d in devices if (d.get("type") or "").startswith(("usw", "usk"))]
    for sw in switches:
        ports = sw.get("ports", sw.get("port_table", []))
        if not isinstance(ports, list):
            continue
        name = sw.get("name", sw.get("mac", "unknown"))
        vlan_set: set[int] = set()
        for port in ports:
            vid = port.get("native_networkconf_id") or port.get("vlan")
            if isinstance(vid, int):
                vlan_set.add(vid)
        # Flag if a switch has a very wide spread of VLANs (potential misconfiguration).
        if len(vlan_set) > 10:
            findings.append(
                _finding(
                    "TOP-03",
                    "info",
                    f"Switch '{name}' has {len(vlan_set)} distinct VLANs on ports — review for consistency.",
                )
            )

    return findings


# ── Scoring ──────────────────────────────────────────────────────────────────


def score_findings(findings: list[dict]) -> int:
    """Compute a category score from findings. Max CATEGORY_MAX, min 0."""
    deduction = 0
    for f in findings:
        sev = f.get("severity", "info")
        deduction += SEVERITY_DEDUCTIONS.get(sev, 0)
    return max(0, CATEGORY_MAX - deduction)


def overall_status(score: int) -> str:
    """Derive overall status string from total score (0-100)."""
    if score >= 80:
        return "healthy"
    elif score >= 60:
        return "needs_attention"
    else:
        return "critical"


# ── History / trend tracking ─────────────────────────────────────────────────


def load_history(state_dir: Path) -> list[dict]:
    """Load audit history from disk."""
    path = state_dir / HISTORY_FILENAME
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_history(state_dir: Path, history: list[dict]) -> None:
    """Persist audit history. Keep last 50 entries."""
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / HISTORY_FILENAME
    trimmed = history[-50:]
    path.write_text(json.dumps(trimmed, indent=2))


def compute_trend(history: list[dict], current_score: int) -> dict[str, Any]:
    """Compute score trend compared to last entry."""
    if not history:
        return {"previous_score": None, "change": None}
    prev = history[-1].get("overall_score", 0)
    diff = current_score - prev
    sign = "+" if diff >= 0 else ""
    return {"previous_score": prev, "change": f"{sign}{diff}"}


# ── Recommendations builder ─────────────────────────────────────────────────


def build_recommendations(
    categories: dict[str, dict],
) -> list[str]:
    """Generate prioritized recommendations from category findings."""
    recs: list[str] = []
    all_findings: list[dict] = []
    for cat_data in categories.values():
        all_findings.extend(cat_data.get("findings", []))

    # Sort by severity: critical first.
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    all_findings.sort(key=lambda f: severity_order.get(f.get("severity", "info"), 3))

    seen_benchmarks: set[str] = set()
    for f in all_findings:
        bid = f.get("benchmark_id", "")
        if bid in seen_benchmarks:
            continue
        seen_benchmarks.add(bid)
        fix = f.get("fix")
        if fix:
            recs.append(f"[{bid}] {f['message']} — use {fix.get('tool', 'manual fix')}.")
        else:
            recs.append(f"[{bid}] {f['message']}")

    if not recs:
        recs.append("No issues found. Firewall configuration meets all benchmarks.")

    return recs


# ── Human-readable output ────────────────────────────────────────────────────


def format_human(report: dict) -> str:
    """Render report dict as a human-readable string."""
    lines: list[str] = []
    lines.append("=== Firewall Audit Report ===")
    lines.append(f"Score: {report['overall_score']}/100  Status: {report['overall_status'].upper()}")
    lines.append(f"Timestamp: {report['timestamp']}")
    lines.append("")

    summary = report.get("summary", {})
    lines.append(
        f"Policies: {summary.get('total_policies', 0)} total "
        f"({summary.get('enabled', 0)} enabled, {summary.get('disabled', 0)} disabled)"
    )
    lines.append(f"Networks: {summary.get('networks', 0)}  Devices: {summary.get('devices', 0)}")
    lines.append("")

    for cat_name, cat_data in report.get("categories", {}).items():
        lines.append(f"-- {cat_name.replace('_', ' ').title()} ({cat_data['score']}/{cat_data['max']}) --")
        for f in cat_data.get("findings", []):
            sev = f.get("severity", "info").upper()
            lines.append(f"  [{sev}] {f['message']}")
        if not cat_data.get("findings"):
            lines.append("  No issues found.")
        lines.append("")

    trend = report.get("trend", {})
    if trend.get("previous_score") is not None:
        lines.append(f"Trend: {trend['change']} from previous score of {trend['previous_score']}")
        lines.append("")

    critical = report.get("critical_findings", [])
    if critical:
        lines.append("-- Critical Findings --")
        for f in critical:
            lines.append(f"  - {f['message']}")
        lines.append("")

    recs = report.get("recommendations", [])
    if recs:
        lines.append("-- Recommendations --")
        for i, r in enumerate(recs, 1):
            lines.append(f"  {i}. {r}")

    return "\n".join(lines)


# ── Main logic ───────────────────────────────────────────────────────────────


def run_audit(mcp_url: str, state_dir: Path) -> dict:
    """Connect to MCP, gather data, run checks, score, return report."""
    client = MCPClient(mcp_url)

    # Check readiness.
    ready = client.check_ready("unifi_tool_index")
    if not ready:
        return client.get_setup_error()

    # Step 1: Collect bulk data in parallel.
    try:
        results = client.call_tools_parallel([
            ("unifi_list_firewall_policies", {}),
            ("unifi_list_firewall_zones", {}),
            ("unifi_list_networks", {}),
            ("unifi_list_firewall_groups", {}),
            ("unifi_list_devices", {}),
        ])
    except (MCPConnectionError, MCPToolError) as e:
        return {"success": False, "error": f"Failed to collect data: {e}"}

    policies_result, zones_result, networks_result, firewall_groups_result, devices_result = results

    policies = _extract_list(policies_result, "policies")
    zones = _extract_list(zones_result, "zones")
    networks = _extract_list(networks_result, "networks")
    firewall_groups = _extract_list(firewall_groups_result, "groups")
    devices = _extract_list(devices_result, "devices")

    # Step 2: Fetch details for each policy.
    policy_details: dict[str, dict] = {}
    for p in policies:
        pid = p.get("id")
        if not pid:
            continue
        try:
            detail_result = client.call_tool(
                "unifi_get_firewall_policy_details", {"policy_id": pid}
            )
            if detail_result.get("success"):
                detail = detail_result.get("details", {})
                # Merge summary fields for convenience.
                detail.setdefault("name", p.get("name"))
                detail.setdefault("enabled", p.get("enabled"))
                detail.setdefault("action", p.get("action"))
                policy_details[pid] = detail
        except (MCPConnectionError, MCPToolError):
            logger.warning("Failed to fetch details for policy %s", pid)

    # Step 3: Run benchmark checks.
    seg_findings = check_segmentation(policies, policy_details, networks, zones)
    egress_findings = check_egress(policies, policy_details, networks)
    hygiene_findings = check_hygiene(policies, policy_details, networks, firewall_groups)
    topology_findings = check_topology(devices)

    # Step 4: Score each category.
    categories = {
        "segmentation": {
            "score": score_findings(seg_findings),
            "max": CATEGORY_MAX,
            "findings": seg_findings,
        },
        "egress_control": {
            "score": score_findings(egress_findings),
            "max": CATEGORY_MAX,
            "findings": egress_findings,
        },
        "rule_hygiene": {
            "score": score_findings(hygiene_findings),
            "max": CATEGORY_MAX,
            "findings": hygiene_findings,
        },
        "topology": {
            "score": score_findings(topology_findings),
            "max": CATEGORY_MAX,
            "findings": topology_findings,
        },
    }

    total_score = sum(c["score"] for c in categories.values())

    # Step 5: Trend tracking.
    history = load_history(state_dir)
    trend = compute_trend(history, total_score)

    # Collect critical findings for top-level visibility.
    critical_findings = []
    for cat_data in categories.values():
        for f in cat_data.get("findings", []):
            if f.get("severity") == "critical":
                critical_findings.append(f)

    # Summary.
    enabled_count = sum(1 for p in policies if p.get("enabled"))
    disabled_count = sum(1 for p in policies if not p.get("enabled"))
    summary = {
        "total_policies": len(policies),
        "enabled": enabled_count,
        "disabled": disabled_count,
        "networks": len(networks),
        "devices": len(devices),
    }

    # Build recommendations.
    recommendations = build_recommendations(categories)

    report = {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall_score": total_score,
        "overall_status": overall_status(total_score),
        "categories": categories,
        "trend": trend,
        "critical_findings": critical_findings,
        "summary": summary,
        "recommendations": recommendations,
    }

    # Step 6: Save history.
    history.append({
        "timestamp": report["timestamp"],
        "overall_score": total_score,
    })
    save_history(state_dir, history)

    return report


# ── Entry point ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    mcp_url = args.mcp_url or get_server_url("network")
    state_dir = Path(args.state_dir) if args.state_dir else get_state_dir(ensure=True)

    report = run_audit(mcp_url, state_dir)

    if args.output_format == "human":
        print(format_human(report))
    else:
        print(json.dumps(report, indent=2))

    # Exit with non-zero if unhealthy or setup required.
    if not report.get("success", False):
        sys.exit(1)
    if report.get("overall_status") == "critical":
        sys.exit(2)


if __name__ == "__main__":
    main()
