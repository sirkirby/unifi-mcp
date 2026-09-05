"""Explicit, read-only support acceptance over the real MCP stdio boundary.

Reports contain fixed checks, sizes, and product/mode enums only. Raw responses,
credentials, child-process diagnostics, and exceptions are never persisted.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from unifi_core.support_bundle import SupportBundle

PRODUCTS = ("network", "protect", "access")
MODES = ("lazy", "eager", "meta_only")
INVALID_PROBE = "support-smoke-private-input-canary"


class SupportSmokeError(ValueError):
    """A fixed, non-sensitive acceptance check failed."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise SupportSmokeError(code)


def support_environment(root: Path, mode: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update({key: value for key, value in dotenv_values(root / ".env").items() if value is not None})
    env.update(
        {
            "UNIFI_TOOL_REGISTRATION_MODE": mode,
            "UNIFI_TOOL_PERMISSION_MODE": "confirm",
            "UNIFI_AUTO_CONFIRM": "false",
            "UNIFI_MCP_HTTP_ENABLED": "false",
            "UNIFI_MCP_DIAGNOSTICS": "false",
            "UNIFI_MCP_LOG_LEVEL": "ERROR",
            "UNIFI_REDACT_SENSITIVE_FIELDS": "false",
            "PROTECT_WEBSOCKET_ENABLED": "false",
            "ACCESS_WEBSOCKET_ENABLED": "false",
        }
    )
    for product in PRODUCTS:
        env[f"UNIFI_{product.upper()}_TOOL_REGISTRATION_MODE"] = mode
        env[f"UNIFI_{product.upper()}_TOOL_PERMISSION_MODE"] = "confirm"
        env[f"UNIFI_{product.upper()}_REDACT_SENSITIVE_FIELDS"] = "false"
        env[f"UNIFI_{product.upper()}_MCP_CONTENT_MODE"] = "adaptive"
    return env


def private_canaries(env: dict[str, str]) -> set[bytes]:
    canaries = set()
    for key, value in env.items():
        if not key.startswith("UNIFI_") or len(value) < 4:
            continue
        if any(part in key for part in ("HOST", "USERNAME", "PASSWORD", "API_KEY", "TOKEN")):
            raw = value.encode()
            canaries.update((raw, hashlib.sha256(raw).hexdigest().encode(), base64.b64encode(raw)))
    return canaries


def validate_bundle(
    payload: Any, product: str, mode: str, probe: str, canaries: set[bytes], version: str | None
) -> int:
    require(isinstance(payload, dict) and payload.get("success") is True, "bundle_success")
    raw = json.dumps(payload, sort_keys=True).encode()
    require(len(raw) <= 32768, "envelope_size")
    require(not any(canary in raw for canary in canaries), "private_canary")
    require(set(payload) == {"success", "data"}, "envelope_schema")
    try:
        bundle = SupportBundle.model_validate(payload.get("data"))
    except ValueError:
        raise SupportSmokeError("bundle_schema") from None
    require(bundle.product == product and bundle.probe.probe == probe, "product_probe_identity")
    require(bundle.runtime.registration_mode == mode, "registration_mode")
    require(bundle.connection.connected is True, "connected")
    require(bundle.server.package == f"unifi-{product}-mcp", "package_identity")
    require(version is None or bundle.server.version == version, "plugin_package_version")
    require("response_redaction_disabled" in bundle.server.feature_flags, "redaction_override_exercised")
    if probe == "connectivity":
        require(bundle.probe.outcome == "success", "connectivity_outcome")
    return len(raw)


def plugin_command(root: Path, product: str, env: dict[str, str]) -> tuple[str, list[str], str]:
    """Validate packaged skills/pins and use only the standard uvx launcher."""
    folder = root / "plugins" / f"unifi-{product}"
    codex = json.loads((folder / ".codex-plugin/plugin.json").read_text())
    claude = json.loads((folder / ".claude-plugin/plugin.json").read_text())
    version = codex["version"]
    require(isinstance(version, str) and re.fullmatch(r"\d+\.\d+\.\d+", version) is not None, "plugin_version")
    require(claude["version"] == version, "plugin_version_alignment")
    skill_root = (folder / codex["skills"]).resolve()
    require(skill_root.is_relative_to(folder.resolve()), "plugin_skill_root")
    skill = (skill_root / f"unifi-{product}-support/SKILL.md").read_text()
    prefix = "unifi" if product == "network" else product
    require(
        f"name: unifi-{product}-support" in skill and f"{prefix}_get_support_bundle" in skill, "plugin_support_skill"
    )
    require(codex["mcpServers"] == "./.mcp.json", "plugin_mcp_path")
    name = f"unifi-{product}"
    launcher = json.loads((folder / ".mcp.json").read_text())["mcpServers"][name]
    expected_args = ["--python-preference", "system", f"unifi-{product}-mcp=={version}"]
    for config in (launcher, claude["mcpServers"][name]):
        require(config["command"] == "uvx" and config["args"] == expected_args, "plugin_launcher_alignment")
    # Resolve the checked-in plugin environment exactly as a host would.
    for key, expression in launcher.get("env", {}).items():
        match = re.fullmatch(r"\$\{([A-Z_]+):-([^}]*)\}", expression)
        require(match is not None, "plugin_env_expression")
        env[key] = env.get(match[1]) or match[2]
    return "uvx", expected_args, version


async def exercise_session(
    client: Any, product: str, mode: str, env: dict[str, str], version: str | None
) -> dict[str, Any]:
    prefix = "unifi" if product == "network" else product
    name = f"{prefix}_get_support_bundle"
    await client.initialize()
    tools = (await client.list_tools()).tools
    matches = [tool for tool in tools if tool.name == name]
    require(len(matches) == 1, "catalog_visibility")
    tool = matches[0]
    require(tool.annotations is not None and tool.annotations.read_only_hint is True, "readonly_annotation")
    require(
        tool.input_schema["properties"]["probe"]["enum"] == ["summary", "connectivity", "resource_shape"],
        "probe_schema",
    )
    canaries = private_canaries(env)

    async def call(arguments: dict[str, Any]) -> Any:
        result = await client.call_tool(name, arguments)
        require(INVALID_PROBE not in result.model_dump_json(), "invalid_input_echo")
        require(not any(canary in result.model_dump_json().encode() for canary in canaries), "mcp_private_canary")
        require(not result.is_error, "mcp_result")
        if isinstance(getattr(result, "structured_content", None), dict):
            return result.structured_content
        return json.loads(result.content[0].text)

    sizes = {}
    for probe in ("summary", "connectivity"):
        sizes[probe] = validate_bundle(await call({"probe": probe}), product, mode, probe, canaries, version)
    cooldown = await call({"probe": "connectivity"})
    require(
        cooldown.get("success") is False
        and cooldown.get("error") == "Failed to generate support bundle: this live probe is in cooldown.",
        "cooldown",
    )
    invalid = await call({"probe": INVALID_PROBE})
    require(invalid.get("success") is False, "invalid_probe_rejected")
    validate_bundle(await call({"probe": "summary"}), product, mode, "summary", canaries, version)
    return {"product": product, "mode": mode, "status": "passed", "bytes": sizes}


async def run_support_phase(server: str, root: Path, plugin_root: Path | None = None) -> dict[str, Any]:
    products = PRODUCTS if server == "all" else (server,)
    require(all(product in PRODUCTS for product in products), "product_argument")
    records = []
    # One fresh cache for plugin launchers proves resolution outside the user's cache.
    with tempfile.TemporaryDirectory(prefix="unifi-support-install-") as cache:
        for product in products:
            for mode in MODES:
                try:
                    env = support_environment(root, mode)
                    version = None
                    command, arguments = sys.executable, ["-m", f"unifi_{product}_mcp.main"]
                    if plugin_root is not None:
                        command, arguments, version = plugin_command(plugin_root, product, env)
                        env["UV_CACHE_DIR"] = cache
                    parameters = StdioServerParameters(command=command, args=arguments, env=env, cwd=root)
                    with tempfile.TemporaryFile(mode="w+") as stderr:
                        async with asyncio.timeout(180):
                            async with stdio_client(parameters, errlog=stderr) as streams:
                                async with ClientSession(*streams, read_timeout_seconds=90) as client:
                                    record = await exercise_session(client, product, mode, env, version)
                        stderr.seek(0)
                        log = stderr.read(1_048_577)
                        require(len(log) <= 1_048_576, "bounded_process_log")
                        require(INVALID_PROBE not in log, "invalid_input_log_echo")
                    records.append(record)
                    print(f"support {product} {mode}: passed", flush=True)
                except Exception:
                    # Do not retry auth failures or serialize exceptions/ExceptionGroups.
                    records.append({"product": product, "mode": mode, "status": "failed"})
                    print(f"support {product} {mode}: failed (details suppressed for privacy)", flush=True)
                    return {"success": False, "records": records}
    return {"success": True, "records": records}
