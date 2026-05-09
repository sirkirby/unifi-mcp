#!/usr/bin/env python3
"""Live UniFi MCP smoke harness.

The harness intentionally exercises the public MCP tool layer instead of
manager internals. It defaults to conservative behavior:

* read-only tools are run when required arguments can be discovered
* mutating tools are previewed with ``confirm=False``
* only named lifecycle scenarios use ``confirm=True``
* risky physical/destructive operations are reported as pending approval
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_PREFIX = "codex-smoke"


SERVER_PACKAGES = {
    "network": "unifi-network-mcp",
    "protect": "unifi-protect-mcp",
    "access": "unifi-access-mcp",
}


SERVER_CONFIGS = {
    "network": {
        "main": "unifi_network_mcp.main",
        "runtime": "unifi_network_mcp.runtime",
        "bootstrap": "unifi_network_mcp.bootstrap",
        "categories": "unifi_network_mcp.categories",
        "jobs": "unifi_network_mcp.jobs",
        "tool_index": "unifi_network_mcp.tool_index",
        "base_package": "unifi_network_mcp.tools",
        "manifest": REPO_ROOT / "apps/network/src/unifi_network_mcp/tools_manifest.json",
        "close": "cleanup",
    },
    "protect": {
        "main": "unifi_protect_mcp.main",
        "runtime": "unifi_protect_mcp.runtime",
        "bootstrap": "unifi_protect_mcp.bootstrap",
        "categories": "unifi_protect_mcp.categories",
        "jobs": "unifi_protect_mcp.jobs",
        "tool_index": "unifi_protect_mcp.tool_index",
        "base_package": "unifi_protect_mcp.tools",
        "manifest": REPO_ROOT / "apps/protect/src/unifi_protect_mcp/tools_manifest.json",
        "prefix": "protect",
        "server_label": "UniFi Protect",
        "close": "close",
    },
    "access": {
        "main": "unifi_access_mcp.main",
        "runtime": "unifi_access_mcp.runtime",
        "bootstrap": "unifi_access_mcp.bootstrap",
        "categories": "unifi_access_mcp.categories",
        "jobs": "unifi_access_mcp.jobs",
        "tool_index": "unifi_access_mcp.tool_index",
        "base_package": "unifi_access_mcp.tools",
        "manifest": REPO_ROOT / "apps/access/src/unifi_access_mcp/tools_manifest.json",
        "prefix": "access",
        "server_label": "UniFi Access",
        "close": "close",
    },
}


STREAM_OR_HEAVY_READS = {
    "access_subscribe_events",
    "protect_subscribe_events",
    "protect_export_clip",
}


RISKY_OPERATION_NAMES = {
    "access_lock_door",
    "access_reboot_device",
    "access_revoke_credential",
    "access_unlock_door",
    "protect_delete_recording",
    "protect_reboot_camera",
    "protect_ptz_move",
    "protect_ptz_preset",
    "protect_ptz_zoom",
    "protect_toggle_recording",
    "protect_trigger_chime",
    "unifi_adopt_device",
    "unifi_authorize_guest",
    "unifi_block_client",
    "unifi_force_provision_device",
    "unifi_force_reconnect_client",
    "unifi_forget_client",
    "unifi_locate_device",
    "unifi_power_cycle_port",
    "unifi_reboot_device",
    "unifi_revoke_voucher",
    "unifi_set_device_led",
    "unifi_set_site_leds",
    "unifi_toggle_device",
    "unifi_trigger_rf_scan",
    "unifi_trigger_speedtest",
    "unifi_unauthorize_guest",
    "unifi_unblock_client",
    "unifi_upgrade_device",
}


@dataclass
class SmokeRecord:
    tool: str
    phase: str
    status: str
    args: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    success: bool | None = None
    error: str | None = None
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class SmokeReport:
    server: str
    started_at: str
    finished_at: str | None = None
    connected: bool = False
    records: list[SmokeRecord] = field(default_factory=list)
    created_resources: list[dict[str, Any]] = field(default_factory=list)
    cleaned_resources: list[dict[str, Any]] = field(default_factory=list)
    pending_approval: list[dict[str, Any]] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run live smoke checks against UniFi MCP tools.")
    parser.add_argument(
        "--server",
        choices=["network", "protect", "access", "all"],
        required=False,
        help="Required for MCP-direct phases. Ignored for --phase api-actions / api-resources / api-streams.",
    )
    parser.add_argument(
        "--phase",
        choices=[
            "inventory", "readonly", "preview", "lifecycle", "approved", "safe",
            "api-actions", "api-resources", "api-streams",
        ],
        default="safe",
        help=(
            "'safe' runs readonly, preview, and named safe lifecycles. "
            "'approved' runs explicitly approved mutations. "
            "'api-actions' is a manual-only phase: spins up unifi-api locally, "
            "registers the .env-configured controllers, exercises read-only tools "
            "via POST /v1/actions/{tool}, and compares to the latest MCP-direct "
            "baseline. "
            "'api-resources' is also manual-only: same bootstrap, but exercises "
            "GET /v1/sites/{site}/{resource} endpoints and (where the tool "
            "equivalent exists) compares the data payload to the action endpoint. "
            "'api-streams' is also manual-only: same bootstrap, but opens an SSE "
            "client to GET /v1/streams/{product}/events for each registered "
            "controller and verifies frames flow within a 35s window."
        ),
    )
    parser.add_argument("--report-dir", default="live-smoke-results")
    parser.add_argument("--delay", type=float, default=0.25, help="Delay between tool calls in seconds.")
    parser.add_argument("--tool", action="append", default=[], help="Restrict to one or more tool names.")
    parser.add_argument("--include-heavy-reads", action="store_true")
    parser.add_argument("--interactive-risky", action="store_true")
    args = parser.parse_args()
    if args.phase not in {"api-actions", "api-resources", "api-streams"} and not args.server:
        parser.error(
            "--server is required unless --phase api-actions, --phase api-resources, "
            "or --phase api-streams is used"
        )
    return args


def load_manifest(server_key: str) -> dict[str, Any]:
    with SERVER_CONFIGS[server_key]["manifest"].open() as fh:
        return json.load(fh)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def run_all_servers(args: argparse.Namespace) -> int:
    failures = 0
    for server_key, package in SERVER_PACKAGES.items():
        cmd = [
            "uv",
            "run",
            "--package",
            package,
            "python",
            str(Path(__file__).resolve()),
            "--server",
            server_key,
            "--phase",
            args.phase,
            "--report-dir",
            args.report_dir,
            "--delay",
            str(args.delay),
        ]
        if args.include_heavy_reads:
            cmd.append("--include-heavy-reads")
        if args.interactive_risky:
            cmd.append("--interactive-risky")
        for tool in args.tool:
            cmd.extend(["--tool", tool])
        print(f"\n=== {server_key}: {' '.join(cmd)} ===", flush=True)
        completed = subprocess.run(cmd, cwd=REPO_ROOT, check=False)
        if completed.returncode != 0:
            failures += 1
    return 1 if failures else 0


def configure_environment() -> None:
    load_dotenv(REPO_ROOT / ".env", override=True)
    os.environ["UNIFI_TOOL_REGISTRATION_MODE"] = "eager"
    os.environ["UNIFI_TOOL_PERMISSION_MODE"] = "confirm"
    os.environ["UNIFI_AUTO_CONFIRM"] = "false"
    os.environ["UNIFI_MCP_LOG_LEVEL"] = "WARNING"
    os.environ["UNIFI_MCP_DIAGNOSTICS"] = "false"


def required_params(tool: dict[str, Any]) -> list[str]:
    return list(tool.get("schema", {}).get("input", {}).get("required") or [])


def is_read_only(tool: dict[str, Any]) -> bool:
    return tool.get("annotations", {}).get("readOnlyHint") is True


def is_destructive(tool: dict[str, Any]) -> bool:
    return tool.get("annotations", {}).get("destructiveHint") is True


def collection_items(payload: Any) -> dict[str, list[dict[str, Any]]]:
    found: dict[str, list[dict[str, Any]]] = {}

    def walk(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                walk(child_value, child_key)
        elif isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            found.setdefault(key, []).extend(value)

    walk(payload)
    return found


def first_value(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def looks_ptz_capable(item: dict[str, Any]) -> bool:
    markers = (
        "is_ptz",
        "isPtz",
        "is_ptz_camera",
        "ptz",
        "ptz_capable",
        "has_ptz",
        "pan_tilt_zoom",
    )
    for key in markers:
        value = item.get(key)
        if value is True or (isinstance(value, dict) and value):
            return True
    model_text = " ".join(str(item.get(key, "")) for key in ("name", "model", "type", "display_name")).lower()
    return "ptz" in model_text


def find_int_by_key(value: Any, keys: tuple[str, ...]) -> int | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in keys:
                try:
                    return int(child)
                except (TypeError, ValueError):
                    pass
            found = find_int_by_key(child, keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_int_by_key(child, keys)
            if found is not None:
                return found
    return None


class ResourceCache:
    def __init__(self) -> None:
        self.by_collection: dict[str, list[dict[str, Any]]] = {}
        self.by_tool: dict[str, Any] = {}

    def remember(self, tool: str, result: Any) -> None:
        self.by_tool[tool] = result
        for key, items in collection_items(result).items():
            self.by_collection.setdefault(key, []).extend(items)

    def items(self, *collections: str) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for collection in collections:
            output.extend(self.by_collection.get(collection, []))
        return output

    def items_from_tool(self, tool: str, collection: str) -> list[dict[str, Any]]:
        return collection_items(self.by_tool.get(tool, {})).get(collection, [])

    def id_from(self, collections: tuple[str, ...], keys: tuple[str, ...] = ("id", "_id", "mac", "mac_address")) -> Any:
        for item in self.items(*collections):
            value = first_value(item, keys)
            if value is not None:
                return value
        return None

    def id_from_tool(
        self,
        tool: str,
        collection: str,
        keys: tuple[str, ...] = ("id", "_id", "mac", "mac_address"),
    ) -> Any:
        for item in self.items_from_tool(tool, collection):
            value = first_value(item, keys)
            if value is not None:
                return value
        return None

    def device_mac(self, prefer: str | None = None) -> Any:
        devices = self.items("devices")
        if prefer:
            preferred = [
                item
                for item in devices
                if prefer.lower() in str(item.get("type", "")).lower()
                or prefer.lower() in str(item.get("model", "")).lower()
                or prefer.lower() in str(item.get("device_category", "")).lower()
                or prefer.lower() in str(item.get("displayable_version", "")).lower()
            ]
            for item in preferred:
                value = first_value(item, ("mac", "mac_address", "id", "_id"))
                if value:
                    return value
        for item in devices:
            value = first_value(item, ("mac", "mac_address", "id", "_id"))
            if value:
                return value
        return None

    def client_mac(self) -> Any:
        return self.id_from(("clients",), ("mac", "mac_address", "id", "_id"))

    def client_ip(self) -> Any:
        for item in self.items("clients"):
            value = first_value(item, ("ip", "ip_address", "fixed_ip"))
            if value:
                return value
        return None


class LiveSmokeRunner:
    def __init__(self, server_key: str, args: argparse.Namespace) -> None:
        self.server_key = server_key
        self.args = args
        self.config = SERVER_CONFIGS[server_key]
        self.manifest = load_manifest(server_key)
        self.cache = ResourceCache()
        self.report = SmokeReport(server=server_key, started_at=datetime.now(UTC).isoformat())
        self.server: Any | None = None
        self.connection_manager: Any | None = None

    async def setup(self) -> None:
        configure_environment()
        main_mod = importlib.import_module(self.config["main"])
        runtime_mod = importlib.import_module(self.config["runtime"])
        bootstrap_mod = importlib.import_module(self.config["bootstrap"])
        categories_mod = importlib.import_module(self.config["categories"])
        jobs_mod = importlib.import_module(self.config["jobs"])
        tool_index_mod = importlib.import_module(self.config["tool_index"])
        registration_mod = importlib.import_module("unifi_mcp_shared.tool_registration")

        self.server = runtime_mod.server
        self.connection_manager = runtime_mod.connection_manager
        self.report.connected = await self.connection_manager.initialize()

        kwargs = {
            "mode": bootstrap_mod.UNIFI_TOOL_REGISTRATION_MODE,
            "server": self.server,
            "original_tool_decorator": main_mod._original_tool_decorator,
            "tool_index_handler": tool_index_mod.tool_index_handler,
            "start_async_tool": jobs_mod.start_async_tool,
            "get_job_status": jobs_mod.get_job_status,
            "register_tool": tool_index_mod.register_tool,
            "tool_module_map": categories_mod.TOOL_MODULE_MAP,
            "setup_lazy_loading": categories_mod.setup_lazy_loading,
            "base_package": self.config["base_package"],
            "config": runtime_mod.config,
            "logger": bootstrap_mod.logger,
        }
        if self.config.get("prefix"):
            kwargs["prefix"] = self.config["prefix"]
            kwargs["server_label"] = self.config["server_label"]
        await registration_mod.register_tools_for_mode(**kwargs)

    async def close(self) -> None:
        if not self.connection_manager:
            return
        close_name = self.config["close"]
        close_fn = getattr(self.connection_manager, close_name, None)
        if close_fn:
            await close_fn()

    async def call(self, tool: str, args: dict[str, Any], phase: str) -> SmokeRecord:
        assert self.server is not None
        started = time.perf_counter()
        record = SmokeRecord(tool=tool, phase=phase, status="error", args=args)
        try:
            raw = await self.server.call_tool(tool, args)
            data = self.unwrap_result(raw)
            record.duration_ms = int((time.perf_counter() - started) * 1000)
            record.success = data.get("success") if isinstance(data, dict) else None
            record.status = "ok" if record.success is not False else "failed"
            if isinstance(data, dict):
                if data.get("error"):
                    record.error = str(data["error"])
                record.summary = summarize_payload(data)
                self.cache.remember(tool, data)
        except Exception as exc:
            record.duration_ms = int((time.perf_counter() - started) * 1000)
            record.status = "exception"
            record.success = False
            record.error = str(exc)
        self.report.records.append(record)
        print(f"{self.server_key} {phase} {record.status}: {tool} ({record.duration_ms}ms)", flush=True)
        if self.args.delay:
            await asyncio.sleep(self.args.delay)
        return record

    def unwrap_result(self, raw: Any) -> dict[str, Any]:
        if isinstance(raw, tuple) and len(raw) > 1 and isinstance(raw[1], dict):
            meta_result = raw[1].get("result")
            if isinstance(meta_result, dict):
                return meta_result
        content = raw[0] if isinstance(raw, tuple) and raw else raw
        if isinstance(content, list) and content:
            text = getattr(content[0], "text", None)
            if text:
                return json.loads(text)
        if isinstance(raw, dict):
            return raw
        return {"success": False, "error": f"Unrecognized tool result shape: {type(raw).__name__}"}

    async def run(self) -> None:
        if self.args.phase == "inventory":
            self.inventory()
            return

        await self.seed_read_lists()

        if self.args.phase in ("readonly", "safe"):
            await self.run_readonly()
        if self.args.phase in ("preview", "safe"):
            await self.run_previews()
        if self.args.phase in ("lifecycle", "safe"):
            await self.run_lifecycles()
        if self.args.phase == "approved":
            await self.run_approved()

    def selected_tools(self) -> list[dict[str, Any]]:
        tools = list(self.manifest["tools"])
        if self.args.tool:
            selected = set(self.args.tool)
            tools = [tool for tool in tools if tool["name"] in selected]
        return tools

    def inventory(self) -> None:
        tools = self.selected_tools()
        for tool in tools:
            self.report.records.append(
                SmokeRecord(
                    tool=tool["name"],
                    phase="inventory",
                    status=self.safety_tier(tool),
                    summary={
                        "read_only": is_read_only(tool),
                        "destructive": is_destructive(tool),
                        "required": required_params(tool),
                        "permission_action": tool.get("permission_action"),
                        "permission_category": tool.get("permission_category"),
                    },
                )
            )

    def safety_tier(self, tool: dict[str, Any]) -> str:
        name = tool["name"]
        if name in STREAM_OR_HEAVY_READS:
            return "defer_heavy_read"
        if is_read_only(tool):
            return "read_only"
        if name in RISKY_OPERATION_NAMES or is_destructive(tool):
            return "requires_approval"
        if "confirm" in tool.get("schema", {}).get("input", {}).get("properties", {}):
            return "preview_or_safe_lifecycle"
        return "mutating_requires_review"

    async def seed_read_lists(self) -> None:
        seed_tools = [
            tool
            for tool in self.selected_tools()
            if is_read_only(tool)
            and not required_params(tool)
            and tool["name"] not in STREAM_OR_HEAVY_READS
            and ("list_" in tool["name"] or tool["name"].endswith("_status") or tool["name"].endswith("_info"))
        ]
        for tool in seed_tools:
            await self.call(tool["name"], {}, "seed")

    async def run_readonly(self) -> None:
        for tool in self.selected_tools():
            name = tool["name"]
            if not is_read_only(tool):
                continue
            if name in STREAM_OR_HEAVY_READS and not self.args.include_heavy_reads:
                self.skip(name, "readonly", "heavy or streaming read deferred")
                continue
            args, reason = self.args_for_tool(name, required_params(tool))
            if args is None:
                self.skip(name, "readonly", reason)
                continue
            await self.call(name, args, "readonly")

    async def run_previews(self) -> None:
        for tool in self.selected_tools():
            name = tool["name"]
            if is_read_only(tool):
                continue
            tier = self.safety_tier(tool)
            if tier == "requires_approval":
                self.defer_approval(tool, "preview", "risky or destructive operation")
                continue
            args, reason = self.preview_args(name)
            if args is None:
                self.skip(name, "preview", reason)
                continue
            args["confirm"] = False
            await self.call(name, args, "preview")

    async def run_lifecycles(self) -> None:
        if self.server_key == "network":
            await self.lifecycle_network_dns()
            await self.lifecycle_network_client_group()
            await self.lifecycle_network_firewall_group()
        elif self.server_key == "access":
            await self.lifecycle_access_visitor()
        elif self.server_key == "protect":
            self.skip(
                "protect_create_liveview/protect_delete_liveview",
                "lifecycle",
                "Protect liveview API is validation-only",
            )

    async def run_approved(self) -> None:
        if self.server_key == "network":
            await self.run_lifecycles()
            await self.lifecycle_network_acl_rule()
            await self.lifecycle_network_ap_group()
            await self.lifecycle_network_wlan()
            await self.lifecycle_network_port_profile()
            await self.lifecycle_network_firewall_policy()
            await self.lifecycle_network_oon_policy()
            await self.lifecycle_network_voucher()
        elif self.server_key == "protect":
            await self.approved_protect_physical()
        elif self.server_key == "access":
            await self.approved_access_physical()

    def skip(self, tool: str, phase: str, reason: str) -> None:
        self.report.records.append(SmokeRecord(tool=tool, phase=phase, status="skipped", error=reason))
        print(f"{self.server_key} {phase} skipped: {tool} - {reason}", flush=True)

    def defer_approval(self, tool: dict[str, Any], phase: str, reason: str) -> None:
        item = {
            "tool": tool["name"],
            "phase": phase,
            "reason": reason,
            "required": required_params(tool),
            "destructive": is_destructive(tool),
        }
        self.report.pending_approval.append(item)
        self.report.records.append(SmokeRecord(tool=tool["name"], phase=phase, status="pending_approval", summary=item))
        print(f"{self.server_key} {phase} pending approval: {tool['name']}", flush=True)

    def args_for_tool(self, name: str, required: list[str]) -> tuple[dict[str, Any] | None, str]:
        args: dict[str, Any] = {}
        for param in required:
            value = self.value_for_param(name, param)
            if value is None:
                return None, f"could not discover required argument {param}"
            args[param] = value
        return args, ""

    def value_for_param(self, name: str, param: str) -> Any:
        if param in {"mac_address", "client_mac"}:
            if name == "unifi_get_device_radio":
                return self.cache.device_mac("ap")
            return self.cache.client_mac() if "client" in name else self.cache.device_mac()
        if param in {"device_mac", "gateway_mac"}:
            if param == "gateway_mac":
                return self.cache.device_mac("gateway")
            # PDU-specific tools must target a PDU; the controller rejects other
            # device categories with a clear "not a Smart Power PDU" error.
            if "pdu" in name or "outlet" in name:
                return self.cache.device_mac("pdu")
            return self.cache.device_mac()
        if param == "ap_mac":
            return self.cache.device_mac("ap") or self.cache.device_mac("uap")
        if param == "ip_address":
            return self.cache.client_ip()
        if param == "camera_id":
            return self.cache.id_from(("cameras",), ("id", "_id"))
        if param == "door_id":
            return self.cache.id_from(("doors",), ("id", "_id"))
        if param == "event_id":
            return self.cache.id_from(("events",), ("id", "_id", "event_id", "uuid"))
        if param == "credential_id":
            return self.cache.id_from(("credentials",), ("id", "_id", "credential_id", "uuid"))
        if param == "visitor_id":
            return self.cache.id_from(("visitors",), ("id", "_id", "visitor_id", "uuid"))
        if param == "policy_id":
            if "firewall" in name:
                return self.cache.id_from_tool("unifi_list_firewall_policies", "policies", ("id", "_id"))
            if "oon" in name:
                return self.cache.id_from_tool("unifi_list_oon_policies", "policies", ("id", "_id"))
            return self.cache.id_from_tool(
                "access_list_policies",
                "policies",
                ("id", "_id", "policy_id", "uuid"),
            ) or self.cache.id_from(("policies",), ("id", "_id", "policy_id", "uuid"))
        if param == "group_id":
            if "ap_group" in name:
                return self.cache.id_from_tool("unifi_list_ap_groups", "ap_groups", ("id", "_id"))
            if "client_group" in name:
                return self.cache.id_from_tool("unifi_list_client_groups", "groups", ("id", "_id"))
            if "firewall_group" in name:
                return self.cache.id_from_tool("unifi_list_firewall_groups", "groups", ("id", "_id"))
            if "usergroup" in name:
                return self.cache.id_from_tool("unifi_list_usergroups", "usergroups", ("id", "_id"))
            return self.cache.id_from(("groups",), ("id", "_id"))
        if param == "client_id":
            if "vpn_client" in name:
                return self.cache.id_from_tool("unifi_list_vpn_clients", "vpn_clients", ("_id", "id"))
            return self.cache.client_mac()
        if param == "device_id":
            return self.cache.device_mac()
        if param == "server_id":
            return self.cache.id_from_tool("unifi_list_vpn_servers", "vpn_servers", ("_id", "id"))
        if param == "rule_id":
            if "acl_rule" in name:
                return self.cache.id_from_tool("unifi_list_acl_rules", "rules", ("id", "_id"))
            if "qos_rule" in name:
                return self.cache.id_from_tool("unifi_list_qos_rules", "qos_rules", ("id", "_id"))
            return self.cache.id_from(("rules",), ("id", "_id"))
        collection_by_param = {
            "record_id": ("records",),
            "network_id": ("networks",),
            "wlan_id": ("wlans",),
            "route_id": ("traffic_routes",) if "traffic_route" in name else ("routes",),
            "port_forward_id": ("port_forwards", "rules"),
            "profile_id": ("profiles", "port_profiles"),
            "filter_id": ("filters", "content_filters"),
            "voucher_id": ("vouchers",),
            "liveview_id": ("liveviews",),
            "chime_id": ("chimes",),
            "light_id": ("lights",),
        }
        if param in collection_by_param:
            return self.cache.id_from(collection_by_param[param], ("id", "_id", "mac", "mac_address"))
        return None

    def preview_args(self, name: str) -> tuple[dict[str, Any] | None, str]:
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        simple: dict[str, dict[str, Any]] = {
            "unifi_create_dns_record": {
                "record_data": {
                    "key": f"{RUN_PREFIX}-{stamp}.test",
                    "value": "192.0.2.123",
                    "record_type": "A",
                    "ttl": 60,
                }
            },
            "unifi_create_client_group": {"name": f"{RUN_PREFIX}-{stamp}", "members": []},
            "unifi_create_firewall_group": {
                "name": f"{RUN_PREFIX}-{stamp}",
                "group_type": "address-group",
                "group_members": ["192.0.2.123"],
            },
            "access_create_visitor": self.visitor_args(stamp),
        }
        if name in simple:
            return dict(simple[name]), ""
        if name == "unifi_set_client_ip_settings":
            mac = self.cache.client_mac()
            if not mac:
                return None, "could not discover required argument mac_address"
            return {"mac_address": mac, "local_dns_record_enabled": False}, ""
        if name == "unifi_update_route":
            route_id = self.value_for_param(name, "route_id")
            if not route_id:
                return None, "could not discover required argument route_id"
            return {"route_id": route_id, "enabled": True}, ""
        if name == "unifi_update_traffic_route":
            route_id = self.value_for_param(name, "route_id")
            if not route_id:
                return None, "could not discover required argument route_id"
            return {"route_id": route_id, "enabled": True}, ""
        if name == "unifi_update_usergroup":
            group_id = self.value_for_param(name, "group_id")
            if not group_id:
                return None, "could not discover required argument group_id"
            current_name = None
            for item in self.cache.items_from_tool("unifi_list_usergroups", "usergroups"):
                if first_value(item, ("id", "_id")) == group_id:
                    current_name = item.get("name")
                    break
            return {"group_id": group_id, "name": current_name or f"{RUN_PREFIX}-preview"}, ""
        return self.args_for_tool(name, required_params(next(t for t in self.manifest["tools"] if t["name"] == name)))

    def visitor_args(self, stamp: str) -> dict[str, Any]:
        start = datetime.now(UTC) + timedelta(minutes=5)
        end = start + timedelta(minutes=30)
        return {
            "name": f"{RUN_PREFIX}-{stamp}",
            "access_start": start.isoformat().replace("+00:00", "Z"),
            "access_end": end.isoformat().replace("+00:00", "Z"),
        }

    def protect_camera_id(self, prefer_ptz: bool = False) -> str | None:
        cameras = self.cache.items_from_tool("protect_list_cameras", "cameras") or self.cache.items("cameras")
        if prefer_ptz:
            for camera in cameras:
                if looks_ptz_capable(camera):
                    value = first_value(camera, ("id", "_id", "camera_id", "uuid"))
                    if value:
                        return str(value)
            return None
        for camera in cameras:
            value = first_value(camera, ("id", "_id", "camera_id", "uuid"))
            if value:
                return str(value)
        return None

    def protect_preset_slot(self, camera_id: str) -> int | None:
        payload = self.cache.by_tool.get("protect_get_camera", {})
        detail = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(detail, dict):
            return None
        if str(first_value(detail, ("id", "_id", "camera_id", "uuid"))) not in ("", "None", camera_id):
            return None
        return find_int_by_key(detail, ("slot", "preset_slot", "presetSlot"))

    def protect_recording_enabled(self, camera_id: str) -> bool | None:
        payload = self.cache.by_tool.get("protect_get_camera", {})
        detail = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(detail, dict):
            return None
        if str(first_value(detail, ("id", "_id", "camera_id", "uuid"))) not in ("", "None", camera_id):
            return None
        mode = str(detail.get("recording_mode") or detail.get("recordingMode") or "").lower()
        if mode:
            return mode not in {"never", "disabled", "off"}
        value = detail.get("is_recording")
        return value if isinstance(value, bool) else None

    def firewall_zone_id(self, preferred_name: str) -> str | None:
        zones = self.cache.items_from_tool("unifi_list_firewall_zones", "zones")
        for zone in zones:
            if str(zone.get("name", "")).lower() == preferred_name.lower():
                value = first_value(zone, ("id", "_id", "zone_id"))
                if value:
                    return str(value)
        for zone in zones:
            value = first_value(zone, ("id", "_id", "zone_id"))
            if value:
                return str(value)
        return None

    async def lifecycle_network_dns(self) -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        key = f"{RUN_PREFIX}-{stamp}.test"
        create = await self.call(
            "unifi_create_dns_record",
            {"record_data": {"key": key, "value": "192.0.2.123", "record_type": "A", "ttl": 60}, "confirm": True},
            "lifecycle:create",
        )
        record_id = create.summary.get("resource_id")
        if not record_id:
            self.skip("unifi_update_dns_record/unifi_delete_dns_record", "lifecycle", "DNS create did not return an id")
            return
        self.report.created_resources.append({"type": "dns_record", "id": record_id, "name": key})
        await self.call(
            "unifi_update_dns_record",
            {"record_id": record_id, "update_data": {"value": "192.0.2.124"}, "confirm": True},
            "lifecycle:update",
        )
        await self.call("unifi_get_dns_record_details", {"record_id": record_id}, "lifecycle:get")
        delete = await self.call(
            "unifi_delete_dns_record",
            {"record_id": record_id, "confirm": True},
            "lifecycle:delete",
        )
        if delete.success:
            self.report.cleaned_resources.append({"type": "dns_record", "id": record_id, "name": key})

    async def lifecycle_network_client_group(self) -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        name = f"{RUN_PREFIX}-client-group-{stamp}"
        create = await self.call(
            "unifi_create_client_group",
            {"name": name, "members": [], "confirm": True},
            "lifecycle:create",
        )
        group_id = create.summary.get("resource_id")
        if not group_id:
            self.skip(
                "unifi_update_client_group/unifi_delete_client_group",
                "lifecycle",
                "client group create did not return an id",
            )
            return
        self.report.created_resources.append({"type": "client_group", "id": group_id, "name": name})
        await self.call(
            "unifi_update_client_group",
            {"group_id": group_id, "group_data": {"name": f"{name}-updated"}, "confirm": True},
            "lifecycle:update",
        )
        delete = await self.call(
            "unifi_delete_client_group",
            {"group_id": group_id, "confirm": True},
            "lifecycle:delete",
        )
        if delete.success:
            self.report.cleaned_resources.append({"type": "client_group", "id": group_id, "name": name})

    async def lifecycle_network_firewall_group(self) -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        name = f"{RUN_PREFIX}-fw-group-{stamp}"
        create = await self.call(
            "unifi_create_firewall_group",
            {"name": name, "group_type": "address-group", "group_members": ["192.0.2.123"], "confirm": True},
            "lifecycle:create",
        )
        group_id = create.summary.get("resource_id")
        if not group_id:
            self.skip(
                "unifi_update_firewall_group/unifi_delete_firewall_group",
                "lifecycle",
                "firewall group create did not return an id",
            )
            return
        self.report.created_resources.append({"type": "firewall_group", "id": group_id, "name": name})
        await self.call(
            "unifi_update_firewall_group",
            {
                "group_id": group_id,
                "group_data": {"name": f"{name}-updated", "group_members": ["192.0.2.124"]},
                "confirm": True,
            },
            "lifecycle:update",
        )
        delete = await self.call(
            "unifi_delete_firewall_group",
            {"group_id": group_id, "confirm": True},
            "lifecycle:delete",
        )
        if delete.success:
            self.report.cleaned_resources.append({"type": "firewall_group", "id": group_id, "name": name})

    async def lifecycle_network_acl_rule(self) -> None:
        network_id = self.value_for_param("unifi_create_acl_rule", "network_id")
        if not network_id:
            self.skip("unifi_create_acl_rule/unifi_delete_acl_rule", "approved", "could not discover network_id")
            return

        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        name = f"{RUN_PREFIX}-acl-{stamp}"
        create = await self.call(
            "unifi_create_acl_rule",
            {
                "name": name,
                "acl_index": 65000,
                "action": "ALLOW",
                "network_id": network_id,
                "enabled": False,
                "source_macs": [],
                "destination_macs": [],
                "confirm": True,
            },
            "approved:create",
        )
        rule_id = create.summary.get("resource_id")
        if not rule_id:
            self.skip("unifi_delete_acl_rule", "approved", "ACL create did not return an id")
            return
        self.report.created_resources.append({"type": "acl_rule", "id": rule_id, "name": name})
        delete = await self.call("unifi_delete_acl_rule", {"rule_id": rule_id, "confirm": True}, "approved:delete")
        if delete.success:
            self.report.cleaned_resources.append({"type": "acl_rule", "id": rule_id, "name": name})

    async def lifecycle_network_ap_group(self) -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        name = f"{RUN_PREFIX}-ap-group-{stamp}"
        create = await self.call(
            "unifi_create_ap_group",
            {"group_data": {"name": name, "device_macs": [], "wlan_group_ids": []}, "confirm": True},
            "approved:create",
        )
        group_id = create.summary.get("resource_id")
        if not group_id:
            self.skip("unifi_delete_ap_group", "approved", "AP group create did not return an id")
            return
        self.report.created_resources.append({"type": "ap_group", "id": group_id, "name": name})
        delete = await self.call("unifi_delete_ap_group", {"group_id": group_id, "confirm": True}, "approved:delete")
        if delete.success:
            self.report.cleaned_resources.append({"type": "ap_group", "id": group_id, "name": name})

    async def lifecycle_network_wlan(self) -> None:
        ap_group_id = self.cache.id_from_tool("unifi_list_ap_groups", "ap_groups", ("_id", "id"))
        if not ap_group_id:
            self.skip("unifi_create_wlan/unifi_delete_wlan", "approved", "could not discover AP group id")
            return

        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        name = f"{RUN_PREFIX}-ssid-{stamp}"
        create = await self.call(
            "unifi_create_wlan",
            {
                "wlan_data": {
                    "name": name,
                    "security": "open",
                    "enabled": False,
                    "hide_ssid": True,
                    "guest_policy": True,
                    "ap_group_ids": [ap_group_id],
                    "ap_group_mode": "groups",
                },
                "confirm": True,
            },
            "approved:create",
        )
        wlan_id = create.summary.get("resource_id")
        if not wlan_id:
            self.skip("unifi_delete_wlan", "approved", "WLAN create did not return an id")
            return
        self.report.created_resources.append({"type": "wlan", "id": wlan_id, "name": name})
        delete = await self.call("unifi_delete_wlan", {"wlan_id": wlan_id, "confirm": True}, "approved:delete")
        if delete.success:
            self.report.cleaned_resources.append({"type": "wlan", "id": wlan_id, "name": name})

    async def lifecycle_network_port_profile(self) -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        name = f"{RUN_PREFIX}-port-profile-{stamp}"
        create = await self.call(
            "unifi_create_port_profile",
            {"name": name, "forward": "disabled", "poe_mode": "off", "confirm": True},
            "approved:create",
        )
        profile_id = create.summary.get("resource_id")
        if not profile_id:
            self.skip("unifi_delete_port_profile", "approved", "port profile create did not return an id")
            return
        self.report.created_resources.append({"type": "port_profile", "id": profile_id, "name": name})
        delete = await self.call(
            "unifi_delete_port_profile",
            {"profile_id": profile_id, "confirm": True},
            "approved:delete",
        )
        if delete.success:
            self.report.cleaned_resources.append({"type": "port_profile", "id": profile_id, "name": name})

    async def lifecycle_network_firewall_policy(self) -> None:
        source_zone = self.firewall_zone_id("Internal")
        destination_zone = self.firewall_zone_id("External")
        if not source_zone or not destination_zone:
            self.skip(
                "unifi_create_firewall_policy/unifi_delete_firewall_policy",
                "approved",
                "could not discover source/destination firewall zones",
            )
            return

        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        name = f"{RUN_PREFIX}-fw-policy-{stamp}"
        endpoint = {"matching_target": "ANY"}
        create = await self.call(
            "unifi_create_firewall_policy",
            {
                "policy_data": {
                    "name": name,
                    "action": "ALLOW",
                    "index": 65000,
                    "enabled": False,
                    "logging": False,
                    "protocol": "all",
                    "source": {**endpoint, "zone_id": source_zone},
                    "destination": {**endpoint, "zone_id": destination_zone},
                },
                "confirm": True,
            },
            "approved:create",
        )
        policy_id = create.summary.get("resource_id")
        if not policy_id:
            self.skip("unifi_delete_firewall_policy", "approved", "firewall policy create did not return an id")
            return
        self.report.created_resources.append({"type": "firewall_policy", "id": policy_id, "name": name})
        delete = await self.call(
            "unifi_delete_firewall_policy",
            {"policy_id": policy_id, "confirm": True},
            "approved:delete",
        )
        if delete.success:
            self.report.cleaned_resources.append({"type": "firewall_policy", "id": policy_id, "name": name})

    async def lifecycle_network_oon_policy(self) -> None:
        client_mac = self.cache.client_mac()
        if not client_mac:
            self.skip("unifi_create_oon_policy/unifi_delete_oon_policy", "approved", "could not discover client MAC")
            return

        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        name = f"{RUN_PREFIX}-oon-{stamp}"
        create = await self.call(
            "unifi_create_oon_policy",
            {
                "name": name,
                "target_type": "CLIENTS",
                "targets": [{"type": "MAC", "id": client_mac}],
                "enabled": False,
                "secure": {"internet_access_enabled": True, "apps": []},
                "confirm": True,
            },
            "approved:create",
        )
        policy_id = create.summary.get("resource_id")
        if not policy_id:
            self.skip("unifi_delete_oon_policy", "approved", "OON policy create did not return an id")
            return
        self.report.created_resources.append({"type": "oon_policy", "id": policy_id, "name": name})
        delete = await self.call(
            "unifi_delete_oon_policy", {"policy_id": policy_id, "confirm": True}, "approved:delete"
        )
        if delete.success:
            self.report.cleaned_resources.append({"type": "oon_policy", "id": policy_id, "name": name})

    async def lifecycle_network_voucher(self) -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        note = f"{RUN_PREFIX}-voucher-{stamp}"
        create = await self.call(
            "unifi_create_voucher",
            {"expire_minutes": 10, "count": 1, "quota": 1, "note": note, "confirm": True},
            "approved:create",
        )
        voucher_id = create.summary.get("resource_id")
        if not voucher_id:
            await self.call("unifi_list_vouchers", {}, "approved:list")
            for voucher in self.cache.items_from_tool("unifi_list_vouchers", "vouchers"):
                if voucher.get("note") == note:
                    voucher_id = first_value(voucher, ("_id", "id", "voucher_id"))
                    break
        if not voucher_id:
            self.skip("unifi_revoke_voucher", "approved", "voucher create did not return an id")
            return
        self.report.created_resources.append({"type": "voucher", "id": voucher_id, "name": note})
        revoke = await self.call(
            "unifi_revoke_voucher",
            {"voucher_id": voucher_id, "confirm": True},
            "approved:delete",
        )
        if revoke.success:
            self.report.cleaned_resources.append({"type": "voucher", "id": voucher_id, "name": note})

    async def approved_protect_physical(self) -> None:
        camera_id = self.protect_camera_id()
        if not camera_id:
            self.skip("protect approved camera operations", "approved", "could not discover camera_id")
            return

        ptz_camera_id = self.protect_camera_id(prefer_ptz=True)
        if ptz_camera_id:
            await self.call("protect_get_camera", {"camera_id": ptz_camera_id}, "approved:get")
            await self.call(
                "protect_ptz_move",
                {"camera_id": ptz_camera_id, "pan": 200, "tilt": 0, "duration_ms": 150, "confirm": True},
                "approved:physical",
            )
            await self.call(
                "protect_ptz_zoom",
                {"camera_id": ptz_camera_id, "zoom_speed": 0, "duration_ms": 0, "confirm": True},
                "approved:physical",
            )
            preset_slot = self.protect_preset_slot(ptz_camera_id)
            if preset_slot is not None:
                await self.call(
                    "protect_ptz_preset",
                    {"camera_id": ptz_camera_id, "preset_slot": preset_slot, "confirm": True},
                    "approved:physical",
                )
            else:
                self.skip("protect_ptz_preset", "approved", "no PTZ preset slot discovered")
        else:
            self.skip("protect_ptz_move/protect_ptz_preset", "approved", "no PTZ-capable camera discovered")

        await self.call("protect_get_camera", {"camera_id": camera_id}, "approved:get")
        enabled = self.protect_recording_enabled(camera_id)
        if enabled is None:
            enabled = True
        await self.call(
            "protect_toggle_recording",
            {"camera_id": camera_id, "enabled": enabled, "confirm": False},
            "approved:preview",
        )
        await self.call(
            "protect_toggle_recording",
            {"camera_id": camera_id, "enabled": enabled, "confirm": True},
            "approved:physical",
        )
        await self.call("protect_reboot_camera", {"camera_id": camera_id, "confirm": False}, "approved:preview")
        await self.call("protect_reboot_camera", {"camera_id": camera_id, "confirm": True}, "approved:physical")

    async def approved_access_physical(self) -> None:
        door_id = self.cache.id_from(("doors",), ("id", "_id", "door_id", "uuid"))
        if door_id:
            await self.call(
                "access_unlock_door", {"door_id": door_id, "duration": 2, "confirm": False}, "approved:preview"
            )
            await self.call(
                "access_unlock_door", {"door_id": door_id, "duration": 2, "confirm": True}, "approved:physical"
            )
            await self.call("access_lock_door", {"door_id": door_id, "confirm": False}, "approved:preview")
            await self.call("access_lock_door", {"door_id": door_id, "confirm": True}, "approved:physical")
        else:
            self.skip("access_unlock_door/access_lock_door", "approved", "could not discover door_id")

        device_id = self.cache.id_from(("devices",), ("id", "_id", "device_id", "uuid"))
        if device_id:
            await self.call("access_reboot_device", {"device_id": device_id, "confirm": False}, "approved:preview")
            await self.call("access_reboot_device", {"device_id": device_id, "confirm": True}, "approved:physical")
        else:
            self.skip("access_reboot_device", "approved", "could not discover device_id")

    async def lifecycle_access_visitor(self) -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        args = self.visitor_args(stamp)
        create = await self.call("access_create_visitor", {**args, "confirm": True}, "lifecycle:create")
        visitor_id = create.summary.get("resource_id")
        if not visitor_id:
            self.skip("access_delete_visitor", "lifecycle", "visitor create did not return an id")
            return
        self.report.created_resources.append({"type": "visitor", "id": visitor_id, "name": args["name"]})
        delete = await self.call(
            "access_delete_visitor",
            {"visitor_id": visitor_id, "confirm": True},
            "lifecycle:delete",
        )
        if delete.success:
            self.report.cleaned_resources.append({"type": "visitor", "id": visitor_id, "name": args["name"]})


def summarize_payload(data: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "success",
        "count",
        "site",
        "message",
        "requires_confirmation",
        "action",
        "resource_type",
        "resource_name",
    ):
        if key in data:
            summary[key] = data[key]
    resource_id = find_resource_id(data)
    if resource_id:
        summary["resource_id"] = resource_id
    for collection, items in collection_items(data).items():
        summary[f"{collection}_count"] = len(items)
    if "error" in data:
        summary["error"] = data["error"]
    return summary


def find_resource_id(data: Any) -> str | None:
    if isinstance(data, dict):
        for key in (
            "id",
            "_id",
            "record_id",
            "group_id",
            "rule_id",
            "policy_id",
            "profile_id",
            "voucher_id",
            "visitor_id",
            "wlan_id",
            "liveview_id",
        ):
            value = data.get(key)
            if value:
                return str(value)
        for key in ("details", "group", "policy", "profile", "rule", "data", "result"):
            value = find_resource_id(data.get(key))
            if value:
                return value
    elif isinstance(data, list):
        for item in data:
            value = find_resource_id(item)
            if value:
                return value
    return None


async def run_one(args: argparse.Namespace) -> int:
    runner = LiveSmokeRunner(args.server, args)
    try:
        await runner.setup()
        await runner.run()
    finally:
        runner.report.finished_at = datetime.now(UTC).isoformat()
        await runner.close()
        report_dir = REPO_ROOT / args.report_dir
        stamp = runner.report.started_at.replace(":", "").replace("+0000", "Z")
        path = report_dir / f"{runner.server_key}-{stamp}.json"
        write_json(path, asdict(runner.report))
        print(f"\nReport: {path}", flush=True)
    failed = [record for record in runner.report.records if record.status in {"failed", "exception"}]
    return 1 if failed else 0


###############################################################################
# Phase: api-actions
#
# Manual-only phase. Spins up the unifi-api service locally against a tmp DB,
# registers each .env-configured controller via POST /v1/controllers, exercises
# a sample of read-only tools via POST /v1/actions/{tool_name}, and compares
# each response against the most recent MCP-direct baseline under
# live-smoke-results/. Tears down the server and removes the tmp DB on exit.
#
# This phase is intentionally NOT wired into CI: it requires real controllers
# and the unifi-api package, and is meant as a Phase 2 release-readiness gate.
###############################################################################


# Sample of read-only tools exercised through the action endpoint. Each entry
# pairs a product (matching controller.product_kinds) with a tool name and
# the args dict the action endpoint expects (per Phase 2 dispatcher: args are
# the tool's actual parameters, NOT a {"args": ...} wrapper).
API_ACTIONS_SAMPLE: list[tuple[str, str, dict[str, Any]]] = [
    ("network", "unifi_list_clients", {}),
    ("network", "unifi_list_devices", {}),
    ("protect", "protect_list_cameras", {}),
    ("protect", "protect_list_lights", {}),
    ("access", "access_list_doors", {}),
    ("access", "access_list_users", {}),
]


def _api_actions_baseline_dirs() -> dict[str, str]:
    """Map product -> baseline artifact directory under live-smoke-results/."""
    return {
        "network": "network-readonly-clean",
        "protect": "protect-readonly-clean",
        "access": "access-readonly",
    }


def _load_api_actions_baseline(product: str) -> dict[str, dict[str, Any]]:
    """Load the most recent MCP-direct baseline for a product.

    Returns ``{tool_name: record_dict}`` for read-only/seed records.
    Falls back to an empty mapping if no baseline directory exists.
    """
    baseline_dir = REPO_ROOT / "live-smoke-results" / _api_actions_baseline_dirs()[product]
    if not baseline_dir.is_dir():
        return {}
    candidates = sorted(baseline_dir.glob("*.json"))
    if not candidates:
        return {}
    payload = json.loads(candidates[-1].read_text())
    out: dict[str, dict[str, Any]] = {}
    for record in payload.get("records", []):
        if record.get("phase") in {"seed", "readonly"} and record.get("tool"):
            # Keep the most recent record per tool (records are appended).
            out[record["tool"]] = record
    return out


def _api_actions_controllers_from_env() -> dict[str, dict[str, Any]]:
    """Build controller-registration payloads from .env, one per product.

    Returns ``{product: payload_dict}``. Missing products (e.g., no PROTECT
    creds in .env) are omitted; the phase only exercises tools for products
    actually configured.
    """
    load_dotenv(REPO_ROOT / ".env", override=True)

    def _bool(value: str | None, default: bool = False) -> bool:
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def _build(product: str, host_var: str, port_var: str) -> dict[str, Any] | None:
        host = os.environ.get(host_var)
        if not host:
            return None
        port = os.environ.get(port_var) or "443"
        username = os.environ.get(f"UNIFI_{product.upper()}_USERNAME") or ""
        password = os.environ.get(f"UNIFI_{product.upper()}_PASSWORD") or ""
        api_key = os.environ.get(f"UNIFI_{product.upper()}_API_KEY") or None
        verify_tls = _bool(os.environ.get(f"UNIFI_{product.upper()}_VERIFY_SSL"), False)
        scheme = "https"
        # Strip any scheme the user may have included in HOST.
        host_clean = host.replace("https://", "").replace("http://", "").rstrip("/")
        base_url = f"{scheme}://{host_clean}:{port}"
        return {
            "name": f"smoke-{product}",
            "base_url": base_url,
            "username": username,
            "password": password,
            "api_token": api_key,
            "product_kinds": [product],
            "verify_tls": verify_tls,
            "is_default": product == "network",
        }

    payloads: dict[str, dict[str, Any]] = {}
    for product, host_var, port_var in (
        ("network", "UNIFI_NETWORK_HOST", "UNIFI_NETWORK_PORT"),
        ("protect", "UNIFI_PROTECT_HOST", "UNIFI_PROTECT_PORT"),
        ("access", "UNIFI_ACCESS_HOST", "UNIFI_ACCESS_PORT"),
    ):
        payload = _build(product, host_var, port_var)
        if payload:
            payloads[product] = payload
    return payloads


def _http_request(method: str, url: str, *, headers: dict[str, str] | None = None,
                  body: dict[str, Any] | None = None, timeout: float = 60.0) -> tuple[int, dict[str, Any] | str]:
    """Tiny stdlib HTTP client. Returns (status_code, parsed_json_or_text)."""
    import urllib.error
    import urllib.request

    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, method=method, data=data)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8") or ""
            status = resp.getcode()
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8") if exc.fp else str(exc)
        status = exc.code
    if not raw:
        return status, {}
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw


def _wait_for_health(base: str, deadline_s: float = 30.0) -> bool:
    end = time.time() + deadline_s
    while time.time() < end:
        try:
            status, _ = _http_request("GET", f"{base}/v1/health", timeout=2.0)
            if status == 200:
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def _pick_free_port() -> int:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _bootstrap_unifi_api(env: dict[str, str]) -> str:
    """Run `unifi-api migrate` and return the printed admin key plaintext."""
    completed = subprocess.run(
        ["uv", "run", "--package", "unifi-api", "unifi-api", "migrate"],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    plaintext: str | None = None
    for line in completed.stdout.splitlines():
        candidate = line.strip()
        if candidate.startswith("unifi_live_") or candidate.startswith("unifi_test_"):
            plaintext = candidate
            break
    if not plaintext:
        raise RuntimeError(
            "unifi-api migrate did not print an admin key. stdout was:\n"
            + completed.stdout
            + "\nstderr was:\n"
            + completed.stderr
        )
    return plaintext


def _summarize_action_response(response: Any) -> dict[str, Any]:
    """Reuse summarize_payload semantics on a /v1/actions/* response."""
    if not isinstance(response, dict):
        return {}
    return summarize_payload(response)


def _baseline_count(record: dict[str, Any] | None) -> int | None:
    if not record:
        return None
    summary = record.get("summary") or {}
    for key, value in summary.items():
        if key.endswith("_count") and isinstance(value, int):
            return value
    return None


def _live_count(summary: dict[str, Any]) -> int | None:
    for key, value in summary.items():
        if key.endswith("_count") and isinstance(value, int):
            return value
    return None


def run_api_actions_phase(args: argparse.Namespace) -> int:
    """Manual-only phase: exercise read-only tools through POST /v1/actions/{name}.

    Returns 0 on parity (every exercised tool succeeds AND matches the baseline
    success flag). Returns non-zero when a NEW failure is observed compared to
    the MCP-direct baseline.
    """
    print("\n=== api-actions: spinning up unifi-api locally ===", flush=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="unifi-api-smoke-"))
    db_path = tmp_dir / "state.db"
    db_key = "smoke-" + datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    port = _pick_free_port()
    base_url = f"http://127.0.0.1:{port}"

    env = dict(os.environ)
    env["UNIFI_API_DB_KEY"] = db_key
    env["UNIFI_API_DB_PATH"] = str(db_path)

    started_at = datetime.now(UTC).isoformat()
    server_proc: subprocess.Popen[bytes] | None = None
    server_log = tmp_dir / "server.log"
    artifact: dict[str, Any] = {
        "phase": "api-actions",
        "started_at": started_at,
        "finished_at": None,
        "base_url": base_url,
        "db_path": str(db_path),
        "controllers": [],
        "results": [],
        "summary": {
            "tools_exercised": 0,
            "passed": 0,
            "regressions": 0,
            "preexisting_failures": 0,
        },
    }

    try:
        print(f"  tmp db: {db_path}", flush=True)
        print(f"  http port: {port}", flush=True)
        admin_key = _bootstrap_unifi_api(env)
        print("  unifi-api migrate ok (admin key captured)", flush=True)

        with server_log.open("wb") as log_fh:
            server_proc = subprocess.Popen(
                [
                    "uv", "run", "--package", "unifi-api",
                    "unifi-api", "serve", "--port", str(port),
                ],
                cwd=REPO_ROOT,
                env=env,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
            )

        if not _wait_for_health(base_url, deadline_s=30.0):
            raise RuntimeError(
                f"unifi-api did not become healthy within 30s; see {server_log}"
            )
        print("  unifi-api serve ok (/v1/health 200)", flush=True)

        auth_headers = {"Authorization": f"Bearer {admin_key}"}

        # Step 1: register controllers from .env
        controller_payloads = _api_actions_controllers_from_env()
        if not controller_payloads:
            raise RuntimeError(
                "No controllers found in .env (expected UNIFI_{NETWORK,PROTECT,ACCESS}_HOST)."
            )
        product_to_controller_id: dict[str, str] = {}
        for product, payload in controller_payloads.items():
            status, body = _http_request(
                "POST", f"{base_url}/v1/controllers",
                headers=auth_headers, body=payload,
            )
            if status != 201 or not isinstance(body, dict) or not body.get("id"):
                raise RuntimeError(
                    f"failed to register {product} controller: {status} {body!r}"
                )
            product_to_controller_id[product] = body["id"]
            artifact["controllers"].append({
                "product": product,
                "id": body["id"],
                "name": body.get("name"),
                "base_url": body.get("base_url"),
            })
            print(f"  registered controller: {product} -> {body['id']}", flush=True)

        # Step 2: exercise the sample, comparing to baselines
        baselines = {p: _load_api_actions_baseline(p) for p in product_to_controller_id}
        site_for_product: dict[str, str] = {
            "network": os.environ.get("UNIFI_NETWORK_SITE") or "default",
            "protect": "default",
            "access": "default",
        }

        for product, tool_name, tool_args in API_ACTIONS_SAMPLE:
            if product not in product_to_controller_id:
                continue
            controller_id = product_to_controller_id[product]
            site = site_for_product[product]
            body = {
                "site": site,
                "controller": controller_id,
                "args": tool_args,
                "confirm": False,
            }
            t0 = time.perf_counter()
            try:
                status, response = _http_request(
                    "POST", f"{base_url}/v1/actions/{tool_name}",
                    headers=auth_headers, body=body, timeout=120.0,
                )
            except Exception as exc:
                status = 0
                response = f"{type(exc).__name__}: {exc}"
            duration_ms = int((time.perf_counter() - t0) * 1000)

            success: bool | None = None
            error: str | None = None
            summary: dict[str, Any] = {}
            if status == 200 and isinstance(response, dict):
                success = response.get("success")
                if success is False:
                    error = str(response.get("error") or "")
                summary = _summarize_action_response(response)
            else:
                success = False
                error = f"HTTP {status}: {response!r}"

            baseline_record = baselines.get(product, {}).get(tool_name)
            baseline_success = (
                baseline_record.get("success") if isinstance(baseline_record, dict) else None
            )
            baseline_count = _baseline_count(baseline_record)
            live_count = _live_count(summary)

            shape_match = isinstance(response, dict) and ("success" in response)
            count_delta: int | None = None
            if isinstance(baseline_count, int) and isinstance(live_count, int):
                count_delta = live_count - baseline_count

            # Classification:
            #   pass:          live success matches baseline (both True), shape matches.
            #   preexisting:   baseline already failed (success != True). Not a regression.
            #   regression:    baseline succeeded, but live failed.
            classification: str
            if success is True and (baseline_success is True or baseline_success is None):
                classification = "pass"
            elif baseline_success in (False, None) and success is not True:
                classification = "preexisting" if baseline_success is False else "no_baseline"
            else:
                classification = "regression"

            artifact["results"].append({
                "product": product,
                "tool": tool_name,
                "controller_id": controller_id,
                "site": site,
                "http_status": status,
                "success": success,
                "error": error,
                "duration_ms": duration_ms,
                "shape_match": shape_match,
                "live_count": live_count,
                "baseline_success": baseline_success,
                "baseline_count": baseline_count,
                "count_delta": count_delta,
                "classification": classification,
                "summary": summary,
            })

            artifact["summary"]["tools_exercised"] += 1
            if classification == "pass":
                artifact["summary"]["passed"] += 1
            elif classification == "regression":
                artifact["summary"]["regressions"] += 1
            elif classification in {"preexisting", "no_baseline"}:
                artifact["summary"]["preexisting_failures"] += 1

            print(
                f"  api-actions {classification}: {tool_name} "
                f"http={status} success={success} live_count={live_count} "
                f"baseline_count={baseline_count} ({duration_ms}ms)",
                flush=True,
            )
            if args.delay:
                time.sleep(args.delay)

    finally:
        artifact["finished_at"] = datetime.now(UTC).isoformat()
        if server_proc is not None and server_proc.poll() is None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server_proc.kill()
                server_proc.wait(timeout=5)

        report_dir = REPO_ROOT / args.report_dir / "phase2-api-actions"
        stamp = artifact["started_at"].replace(":", "").replace("+0000", "Z")
        path = report_dir / f"api-actions-{stamp}.json"
        write_json(path, artifact)
        print(f"\nReport: {path}", flush=True)

        # Best-effort cleanup. On regression keep the server log around for
        # diagnosis; on clean runs remove the whole tmp dir (DB key is
        # unique-per-run, so leftover files would only be clutter).
        regressed = artifact["summary"]["regressions"] > 0
        try:
            if regressed:
                kept_log = REPO_ROOT / args.report_dir / "phase2-api-actions" / f"server-log-{stamp}.txt"
                try:
                    if server_log.exists():
                        kept_log.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(server_log, kept_log)
                        print(f"Server log preserved at: {kept_log}", flush=True)
                except Exception:
                    pass
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

    return 1 if artifact["summary"]["regressions"] > 0 else 0


###############################################################################
# Phase: api-resources
#
# Manual-only phase. Same bootstrap as api-actions (spins up unifi-api locally,
# registers .env-configured controllers), then exercises the GET resource
# endpoints (clients, devices, networks, wlans, firewall rules, cameras,
# recordings, events, doors, users, credentials). For each resource that has a
# tool equivalent, also calls the matching action endpoint and compares the
# data payloads — the resource version wraps in {items, next_cursor,
# render_hint} and the action version wraps in {success: true, data,
# render_hint}; the inner item arrays should match (the action endpoint
# returns the full collection, the resource endpoint returns a paginated
# slice, so the comparison checks set-of-ids/MACs).
#
# Like api-actions, this phase is intentionally NOT wired into CI and serves
# as a Phase 3 release-readiness gate.
###############################################################################


# Sample of resource endpoints exercised through GET. Each entry is:
#   (product, path_template, query_extras, parity_tool_name_or_None,
#    parity_args_or_None, parity_collection_keys)
#
# - path_template uses {site} placeholder.
# - parity_tool_name: when set, the matching POST /v1/actions/{tool} call is
#   issued and the data shapes compared.
# - parity_collection_keys: the keys under the action's data payload that hold
#   the item collection — we look at each in order and use the first present.
API_RESOURCES_SAMPLE: list[tuple[str, str, dict[str, Any], str | None, dict[str, Any] | None, tuple[str, ...]]] = [
    ("network", "/v1/sites/{site}/clients",        {"limit": 10}, "unifi_list_clients",        {},                         ("clients", "items")),
    ("network", "/v1/sites/{site}/devices",        {"limit": 10}, "unifi_list_devices",        {},                         ("devices", "items")),
    ("network", "/v1/sites/{site}/networks",       {"limit": 10}, None,                         None,                       ()),
    ("network", "/v1/sites/{site}/wlans",          {"limit": 10}, None,                         None,                       ()),
    ("network", "/v1/sites/{site}/firewall/rules", {"limit": 10}, None,                         None,                       ()),
    ("protect", "/v1/sites/{site}/cameras",        {"limit": 10}, "protect_list_cameras",       {},                         ("cameras", "items")),
    ("access",  "/v1/sites/{site}/doors",          {"limit": 10}, "access_list_doors",          {},                         ("doors", "items")),
    ("access",  "/v1/sites/{site}/users",          {"limit": 10}, "access_list_users",          {},                         ("users", "items")),
]


def _items_id_set(items: Any, id_keys: tuple[str, ...] = ("id", "_id", "mac", "uuid")) -> set[str]:
    """Extract a set of stable identifiers from a list of dict items.

    Used to compare a resource-endpoint page slice to an action-endpoint full
    collection: the resource set should be a subset of the action set when
    counts agree, and the *paginated* resource slice should always be ⊆ the
    full action collection.
    """
    out: set[str] = set()
    if not isinstance(items, list):
        return out
    for entry in items:
        if not isinstance(entry, dict):
            continue
        for key in id_keys:
            value = entry.get(key)
            if value is not None and value != "":
                out.add(str(value))
                break
    return out


def _action_collection(payload: Any, candidate_keys: tuple[str, ...]) -> list[Any]:
    """Pull the collection list out of an action endpoint response.

    Handles both ``{"data": {...}}`` shapes and ``{...}`` directly. Walks the
    candidate keys in order; falls back to the first list value found at the
    top level.
    """
    if not isinstance(payload, dict):
        return []
    body = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(body, dict):
        return []
    for key in candidate_keys:
        value = body.get(key)
        if isinstance(value, list):
            return value
    # last resort: any list-of-dicts at the top level
    for value in body.values():
        if isinstance(value, list) and (not value or isinstance(value[0], dict)):
            return value
    return []


def run_api_resources_phase(args: argparse.Namespace) -> int:
    """Manual-only phase: exercise GET /v1/sites/{site}/{resource} endpoints.

    Returns 0 when every reachable resource endpoint returns 200 with a valid
    {items, next_cursor, render_hint} shape. Non-zero on a shape failure or
    HTTP 5xx. Pre-existing controller-side failures (Access UNAUTHORIZED, etc.)
    are recorded but do NOT fail the run.
    """
    print("\n=== api-resources: spinning up unifi-api locally ===", flush=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="unifi-api-resources-smoke-"))
    db_path = tmp_dir / "state.db"
    db_key = "smoke-" + datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    port = _pick_free_port()
    base_url = f"http://127.0.0.1:{port}"

    env = dict(os.environ)
    env["UNIFI_API_DB_KEY"] = db_key
    env["UNIFI_API_DB_PATH"] = str(db_path)

    started_at = datetime.now(UTC).isoformat()
    server_proc: subprocess.Popen[bytes] | None = None
    server_log = tmp_dir / "server.log"
    artifact: dict[str, Any] = {
        "phase": "api-resources",
        "started_at": started_at,
        "finished_at": None,
        "base_url": base_url,
        "db_path": str(db_path),
        "controllers": [],
        "results": [],
        "summary": {
            "endpoints_exercised": 0,
            "passed": 0,
            "shape_failures": 0,
            "controller_errors": 0,
            "skipped_no_controller": 0,
            "parity_checked": 0,
            "parity_matches": 0,
            "parity_mismatches": 0,
        },
    }

    try:
        print(f"  tmp db: {db_path}", flush=True)
        print(f"  http port: {port}", flush=True)
        admin_key = _bootstrap_unifi_api(env)
        print("  unifi-api migrate ok (admin key captured)", flush=True)

        with server_log.open("wb") as log_fh:
            server_proc = subprocess.Popen(
                [
                    "uv", "run", "--package", "unifi-api",
                    "unifi-api", "serve", "--port", str(port),
                ],
                cwd=REPO_ROOT,
                env=env,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
            )

        if not _wait_for_health(base_url, deadline_s=30.0):
            raise RuntimeError(
                f"unifi-api did not become healthy within 30s; see {server_log}"
            )
        print("  unifi-api serve ok (/v1/health 200)", flush=True)

        auth_headers = {"Authorization": f"Bearer {admin_key}"}

        # Step 1: register controllers from .env (same as api-actions).
        controller_payloads = _api_actions_controllers_from_env()
        if not controller_payloads:
            raise RuntimeError(
                "No controllers found in .env (expected UNIFI_{NETWORK,PROTECT,ACCESS}_HOST)."
            )
        product_to_controller_id: dict[str, str] = {}
        for product, payload in controller_payloads.items():
            status, body = _http_request(
                "POST", f"{base_url}/v1/controllers",
                headers=auth_headers, body=payload,
            )
            if status != 201 or not isinstance(body, dict) or not body.get("id"):
                raise RuntimeError(
                    f"failed to register {product} controller: {status} {body!r}"
                )
            product_to_controller_id[product] = body["id"]
            artifact["controllers"].append({
                "product": product,
                "id": body["id"],
                "name": body.get("name"),
                "base_url": body.get("base_url"),
            })
            print(f"  registered controller: {product} -> {body['id']}", flush=True)

        # Step 2: exercise resource endpoints.
        site_for_product: dict[str, str] = {
            "network": os.environ.get("UNIFI_NETWORK_SITE") or "default",
            "protect": "default",
            "access": "default",
        }

        for (product, path_tpl, query_extras, parity_tool, parity_args,
             parity_keys) in API_RESOURCES_SAMPLE:
            if product not in product_to_controller_id:
                artifact["summary"]["skipped_no_controller"] += 1
                print(f"  api-resources skip: {path_tpl} (no {product} controller)", flush=True)
                continue
            controller_id = product_to_controller_id[product]
            site = site_for_product[product]
            path = path_tpl.format(site=site)
            qs = "&".join(
                [f"controller={controller_id}"]
                + [f"{k}={v}" for k, v in query_extras.items()]
            )
            url = f"{base_url}{path}?{qs}"

            t0 = time.perf_counter()
            try:
                status, response = _http_request(
                    "GET", url, headers=auth_headers, timeout=120.0,
                )
            except Exception as exc:
                status = 0
                response = f"{type(exc).__name__}: {exc}"
            duration_ms = int((time.perf_counter() - t0) * 1000)

            # Resource shape: {items, next_cursor, render_hint}
            shape_match = (
                status == 200
                and isinstance(response, dict)
                and "items" in response
                and "next_cursor" in response
                and "render_hint" in response
                and isinstance(response.get("items"), list)
            )
            items = response.get("items") if isinstance(response, dict) else None
            item_count = len(items) if isinstance(items, list) else None

            classification: str
            error: str | None = None
            if shape_match:
                classification = "pass"
            elif status == 200 and isinstance(response, dict):
                classification = "shape_failure"
                error = f"missing keys / wrong types in 200 body: {sorted(response.keys())}"
            elif 500 <= (status or 0) < 600:
                classification = "shape_failure"
                error = f"HTTP {status}: {response!r}"
            elif status == 0:
                classification = "shape_failure"
                error = f"transport: {response!r}"
            else:
                # 4xx — most often controller-side: 401 from Access, 503 when
                # Protect is unreachable, etc. Recorded but not a failure.
                classification = "controller_error"
                error = f"HTTP {status}: {response!r}"

            # Parity comparison: hit the matching action endpoint and compare
            # item id sets. We treat the resource endpoint as a paginated
            # subset of the action endpoint; the resource id set should be
            # ⊆ the action id set.
            parity: dict[str, Any] | None = None
            if parity_tool and classification == "pass":
                action_body = {
                    "site": site,
                    "controller": controller_id,
                    "args": parity_args or {},
                    "confirm": False,
                }
                try:
                    a_status, a_response = _http_request(
                        "POST", f"{base_url}/v1/actions/{parity_tool}",
                        headers=auth_headers, body=action_body, timeout=120.0,
                    )
                except Exception as exc:
                    a_status = 0
                    a_response = f"{type(exc).__name__}: {exc}"

                if a_status == 200 and isinstance(a_response, dict) and a_response.get("success"):
                    action_collection = _action_collection(a_response, parity_keys)
                    resource_ids = _items_id_set(items)
                    action_ids = _items_id_set(action_collection)
                    is_subset = resource_ids.issubset(action_ids) if resource_ids else True
                    parity = {
                        "tool": parity_tool,
                        "action_http_status": a_status,
                        "action_success": True,
                        "resource_id_count": len(resource_ids),
                        "action_id_count": len(action_ids),
                        "resource_subset_of_action": is_subset,
                    }
                    artifact["summary"]["parity_checked"] += 1
                    if is_subset:
                        artifact["summary"]["parity_matches"] += 1
                    else:
                        artifact["summary"]["parity_mismatches"] += 1
                else:
                    parity = {
                        "tool": parity_tool,
                        "action_http_status": a_status,
                        "action_success": (
                            a_response.get("success")
                            if isinstance(a_response, dict) else None
                        ),
                        "note": "action endpoint failed; parity skipped",
                    }

            artifact["results"].append({
                "product": product,
                "path": path,
                "controller_id": controller_id,
                "site": site,
                "http_status": status,
                "shape_match": shape_match,
                "item_count": item_count,
                "next_cursor_present": (
                    bool(response.get("next_cursor"))
                    if isinstance(response, dict) else False
                ),
                "render_hint_present": (
                    response.get("render_hint") is not None
                    if isinstance(response, dict) else False
                ),
                "duration_ms": duration_ms,
                "classification": classification,
                "error": error,
                "parity": parity,
            })

            artifact["summary"]["endpoints_exercised"] += 1
            if classification == "pass":
                artifact["summary"]["passed"] += 1
            elif classification == "shape_failure":
                artifact["summary"]["shape_failures"] += 1
            elif classification == "controller_error":
                artifact["summary"]["controller_errors"] += 1

            parity_note = ""
            if parity:
                if "resource_subset_of_action" in parity:
                    parity_note = (
                        f" parity={'ok' if parity['resource_subset_of_action'] else 'MISMATCH'}"
                        f" (r={parity['resource_id_count']} a={parity['action_id_count']})"
                    )
                else:
                    parity_note = " parity=skip"
            print(
                f"  api-resources {classification}: {path} "
                f"http={status} items={item_count} ({duration_ms}ms){parity_note}",
                flush=True,
            )
            if args.delay:
                time.sleep(args.delay)

    finally:
        artifact["finished_at"] = datetime.now(UTC).isoformat()
        if server_proc is not None and server_proc.poll() is None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server_proc.kill()
                server_proc.wait(timeout=5)

        report_dir = REPO_ROOT / args.report_dir / "phase3-api-resources"
        stamp = artifact["started_at"].replace(":", "").replace("+0000", "Z")
        path = report_dir / f"api-resources-{stamp}.json"
        write_json(path, artifact)
        print(f"\nReport: {path}", flush=True)

        # On failure preserve the server log; otherwise tear down the tmp dir.
        failed = (
            artifact["summary"]["shape_failures"] > 0
            or artifact["summary"]["parity_mismatches"] > 0
        )
        try:
            if failed:
                kept_log = REPO_ROOT / args.report_dir / "phase3-api-resources" / f"server-log-{stamp}.txt"
                try:
                    if server_log.exists():
                        kept_log.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(server_log, kept_log)
                        print(f"Server log preserved at: {kept_log}", flush=True)
                except Exception:
                    pass
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

    if artifact["summary"]["shape_failures"] > 0:
        return 1
    if artifact["summary"]["parity_mismatches"] > 0:
        return 1
    return 0


###############################################################################
# Phase 4B: --phase api-streams
# ---------------------------------------------------------------------------
# Manual-only phase. Same bootstrap as api-actions / api-resources (spins up
# unifi-api locally, registers the .env-configured controllers), then opens an
# SSE client to ``GET /v1/streams/{product}/events?controller={cid}`` for each
# (controller × product) pair and reads frames for ~35s. Pass criterion: ≥1
# event OR ≥1 keepalive frame received within the window (the server emits a
# ``: keepalive`` comment every 30s, so even an idle controller will pass on
# the first keepalive boundary).
#
# Like api-actions / api-resources, this phase is intentionally NOT wired into
# CI and serves as the Phase 4B release-readiness gate.
###############################################################################


# Products whose stream endpoint we exercise. One row per product; the harness
# only opens the stream for products that have a registered controller from
# .env.
API_STREAMS_PRODUCTS: tuple[str, ...] = ("network", "protect", "access")


def _read_sse_window(
    base_url: str,
    path: str,
    headers: dict[str, str],
    *,
    duration_s: float,
) -> dict[str, Any]:
    """Open an SSE GET, read frames for ~duration_s, classify the result.

    Uses stdlib urllib for a streaming read. Frames are SSE blocks separated
    by a blank line (``\\n\\n``); ``: keepalive`` comments and ``event:`` /
    ``data:`` event blocks are both counted. ``select`` is used to wait for
    socket readability with a short timeout so we can re-check the wall-clock
    deadline without poisoning the underlying HTTPResponse with a socket
    timeout (which makes subsequent reads raise "cannot read from timed out
    object").
    """
    import select
    import urllib.error
    import urllib.request

    url = f"{base_url}{path}"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "text/event-stream")
    for k, v in headers.items():
        req.add_header(k, v)

    events = 0
    keepalives = 0
    first_frame_at: float | None = None
    started = time.perf_counter()
    deadline = started + duration_s

    try:
        resp = urllib.request.urlopen(req, timeout=10.0)
    except urllib.error.HTTPError as exc:
        body = b""
        try:
            if exc.fp:
                body = exc.fp.read()
        except Exception:
            pass
        return {
            "endpoint": path,
            "status": "controller_error",
            "http": exc.code,
            "body": body[:500].decode("utf-8", "replace"),
            "events": 0, "keepalives": 0, "first_frame_ms": None,
        }
    except Exception as exc:
        return {
            "endpoint": path,
            "status": "shape_failure",
            "error": f"{type(exc).__name__}: {exc}"[:200],
            "events": 0, "keepalives": 0, "first_frame_ms": None,
        }

    try:
        if resp.status != 200:
            try:
                body = resp.read()
            except Exception:
                body = b""
            return {
                "endpoint": path,
                "status": "controller_error",
                "http": resp.status,
                "body": body[:500].decode("utf-8", "replace"),
                "events": 0, "keepalives": 0, "first_frame_ms": None,
            }

        # Reach down to the underlying file object so we can select() on its
        # fileno. urllib's HTTPResponse exposes .fp (a socket file-like).
        fp = getattr(resp, "fp", None)
        try:
            fileno = fp.fileno() if fp is not None else resp.fileno()
        except Exception:
            fileno = None

        buf = b""
        while time.perf_counter() < deadline:
            remaining = deadline - time.perf_counter()
            if fileno is not None:
                try:
                    rlist, _, _ = select.select([fileno], [], [], min(1.0, remaining))
                except (ValueError, OSError):
                    # File descriptor closed underneath us.
                    break
                if not rlist:
                    continue
            try:
                # read1 returns whatever bytes are buffered without waiting
                # for more — exactly what we want for SSE.
                chunk = resp.read1(4096) if hasattr(resp, "read1") else resp.read(4096)
            except Exception as exc:
                if events + keepalives == 0:
                    return {
                        "endpoint": path,
                        "status": "shape_failure",
                        "error": f"{type(exc).__name__}: {exc}"[:200],
                        "events": events, "keepalives": keepalives,
                        "first_frame_ms": None,
                    }
                break
            if not chunk:
                # Server closed the connection.
                break
            if first_frame_at is None:
                first_frame_at = time.perf_counter()
            buf += chunk
            while b"\n\n" in buf:
                frame, _, buf = buf.partition(b"\n\n")
                if not frame:
                    continue
                if frame.startswith(b": keepalive"):
                    keepalives += 1
                elif b"event:" in frame and b"data:" in frame:
                    events += 1
    finally:
        try:
            resp.close()
        except Exception:
            pass

    passed = (events + keepalives) > 0
    first_frame_ms = (
        int((first_frame_at - started) * 1000) if first_frame_at is not None else None
    )
    return {
        "endpoint": path,
        "status": "pass" if passed else "shape_failure",
        "events": events,
        "keepalives": keepalives,
        "first_frame_ms": first_frame_ms,
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }


def run_api_streams_phase(args: argparse.Namespace) -> int:
    """Manual-only phase: exercise GET /v1/streams/{product}/events SSE.

    Returns 0 when every reachable stream endpoint receives ≥1 event or
    ≥1 keepalive within the read window. Non-zero on a shape failure (no
    frames received; HTTP 5xx; transport error). Pre-existing controller-side
    failures (HTTP 4xx that are not 401/403) are recorded as ``controller_error``
    but do NOT fail the run.
    """
    print("\n=== api-streams: spinning up unifi-api locally ===", flush=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="unifi-api-streams-smoke-"))
    db_path = tmp_dir / "state.db"
    db_key = "smoke-" + datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    port = _pick_free_port()
    base_url = f"http://127.0.0.1:{port}"

    # Per-stream read window. 35s ensures we cross the 30s server keepalive
    # boundary at least once for an idle controller; busy controllers will
    # almost always emit a real event well before that.
    window_s = 35.0

    env = dict(os.environ)
    env["UNIFI_API_DB_KEY"] = db_key
    env["UNIFI_API_DB_PATH"] = str(db_path)

    started_at = datetime.now(UTC).isoformat()
    server_proc: subprocess.Popen[bytes] | None = None
    server_log = tmp_dir / "server.log"
    artifact: dict[str, Any] = {
        "phase": "api-streams",
        "started_at": started_at,
        "finished_at": None,
        "base_url": base_url,
        "db_path": str(db_path),
        "window_s": window_s,
        "controllers": [],
        "results": [],
        "summary": {
            "endpoints_exercised": 0,
            "passed": 0,
            "shape_failures": 0,
            "controller_errors": 0,
            "skipped_no_controller": 0,
        },
    }

    try:
        print(f"  tmp db: {db_path}", flush=True)
        print(f"  http port: {port}", flush=True)
        admin_key = _bootstrap_unifi_api(env)
        print("  unifi-api migrate ok (admin key captured)", flush=True)

        with server_log.open("wb") as log_fh:
            server_proc = subprocess.Popen(
                [
                    "uv", "run", "--package", "unifi-api",
                    "unifi-api", "serve", "--port", str(port),
                ],
                cwd=REPO_ROOT,
                env=env,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
            )

        if not _wait_for_health(base_url, deadline_s=30.0):
            raise RuntimeError(
                f"unifi-api did not become healthy within 30s; see {server_log}"
            )
        print("  unifi-api serve ok (/v1/health 200)", flush=True)

        auth_headers = {"Authorization": f"Bearer {admin_key}"}

        # Step 1: register controllers from .env (same as api-actions/resources).
        controller_payloads = _api_actions_controllers_from_env()
        if not controller_payloads:
            raise RuntimeError(
                "No controllers found in .env (expected UNIFI_{NETWORK,PROTECT,ACCESS}_HOST)."
            )
        product_to_controller_id: dict[str, str] = {}
        for product, payload in controller_payloads.items():
            status, body = _http_request(
                "POST", f"{base_url}/v1/controllers",
                headers=auth_headers, body=payload,
            )
            if status != 201 or not isinstance(body, dict) or not body.get("id"):
                raise RuntimeError(
                    f"failed to register {product} controller: {status} {body!r}"
                )
            product_to_controller_id[product] = body["id"]
            artifact["controllers"].append({
                "product": product,
                "id": body["id"],
                "name": body.get("name"),
                "base_url": body.get("base_url"),
            })
            print(f"  registered controller: {product} -> {body['id']}", flush=True)

        # Step 2: exercise each (registered controller × matching product) SSE.
        for product in API_STREAMS_PRODUCTS:
            if product not in product_to_controller_id:
                artifact["summary"]["skipped_no_controller"] += 1
                artifact["results"].append({
                    "product": product,
                    "endpoint": f"/v1/streams/{product}/events",
                    "controller_id": None,
                    "classification": "skipped_no_controller",
                    "events": 0,
                    "keepalives": 0,
                    "first_frame_ms": None,
                    "error": f"no {product} controller registered from .env",
                })
                print(f"  api-streams skip: /v1/streams/{product}/events "
                      f"(no {product} controller)", flush=True)
                continue

            controller_id = product_to_controller_id[product]
            path = f"/v1/streams/{product}/events?controller={controller_id}"

            print(f"  api-streams open: {path} (window={window_s:.0f}s)...",
                  flush=True)
            outcome = _read_sse_window(
                base_url, path, auth_headers, duration_s=window_s,
            )
            classification = outcome.get("status", "shape_failure")

            artifact["results"].append({
                "product": product,
                "endpoint": outcome.get("endpoint", path),
                "controller_id": controller_id,
                "classification": classification,
                "events": outcome.get("events", 0),
                "keepalives": outcome.get("keepalives", 0),
                "first_frame_ms": outcome.get("first_frame_ms"),
                "duration_ms": outcome.get("duration_ms"),
                "http": outcome.get("http"),
                "body": outcome.get("body"),
                "error": outcome.get("error"),
            })

            artifact["summary"]["endpoints_exercised"] += 1
            if classification == "pass":
                artifact["summary"]["passed"] += 1
            elif classification == "controller_error":
                artifact["summary"]["controller_errors"] += 1
            else:
                artifact["summary"]["shape_failures"] += 1

            print(
                f"  api-streams {classification}: /v1/streams/{product}/events "
                f"events={outcome.get('events', 0)} "
                f"keepalives={outcome.get('keepalives', 0)} "
                f"first_frame_ms={outcome.get('first_frame_ms')}",
                flush=True,
            )
            if args.delay:
                time.sleep(args.delay)

    finally:
        artifact["finished_at"] = datetime.now(UTC).isoformat()
        if server_proc is not None and server_proc.poll() is None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server_proc.kill()
                server_proc.wait(timeout=5)

        report_dir = REPO_ROOT / args.report_dir / "phase4b-api-streams"
        stamp = artifact["started_at"].replace(":", "").replace("+0000", "Z")
        out_path = report_dir / f"api-streams-{stamp}.json"
        write_json(out_path, artifact)
        print(f"\nReport: {out_path}", flush=True)

        # On failure preserve the server log; otherwise tear down the tmp dir.
        failed = artifact["summary"]["shape_failures"] > 0
        try:
            if failed:
                kept_log = (
                    REPO_ROOT / args.report_dir / "phase4b-api-streams"
                    / f"server-log-{stamp}.txt"
                )
                try:
                    if server_log.exists():
                        kept_log.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(server_log, kept_log)
                        print(f"Server log preserved at: {kept_log}", flush=True)
                except Exception:
                    pass
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

    if artifact["summary"]["shape_failures"] > 0:
        return 1
    return 0


def main() -> int:
    args = parse_args()
    if args.phase == "api-actions":
        return run_api_actions_phase(args)
    if args.phase == "api-resources":
        return run_api_resources_phase(args)
    if args.phase == "api-streams":
        return run_api_streams_phase(args)
    if args.server == "all":
        return run_all_servers(args)
    return asyncio.run(run_one(args))


if __name__ == "__main__":
    raise SystemExit(main())
