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
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from generate_support_skills import PRODUCTS as SKILL_PRODUCTS
from generate_support_skills import render as render_support_skill
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
    require(not env.get("CONFIG_PATH") and not (root / "config/config.yaml").exists(), "custom_config_unsupported")
    for key in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    env.update(
        {
            "PYTHONNOUSERSITE": "1",
            "PYTHONSAFEPATH": "1",
            "PYTHON_DOTENV_DISABLED": "1",
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
        if not key.startswith("UNIFI_") or not value:
            continue
        if any(part in key for part in ("HOST", "USERNAME", "PASSWORD", "API_KEY", "TOKEN")):
            require(len(value) >= 4, "short_private_canary")
            raw = value.encode()
            canaries.update((raw, hashlib.sha256(raw).hexdigest().encode(), base64.b64encode(raw)))
            canaries.update(json.dumps(value, ensure_ascii=ascii_only)[1:-1].encode() for ascii_only in (True, False))
    return canaries


def contains_private_canary(value: Any, canaries: set[bytes]) -> bool:
    """Inspect decoded values, framing tokens to avoid public-name collisions."""
    if isinstance(value, dict):
        return any(contains_private_canary(item, canaries) for pair in value.items() for item in pair)
    if isinstance(value, list):
        return any(contains_private_canary(item, canaries) for item in value)
    if not isinstance(value, str):
        return False
    # MCP text content can itself contain JSON, including escaped credentials.
    try:
        decoded = json.loads(value)
    except (ValueError, RecursionError):
        decoded = None
    if decoded is not None and contains_private_canary(decoded, canaries):
        return True
    return any(re.search(r"(?<![\w.-])" + re.escape(canary.decode()) + r"(?![\w.-])", value) for canary in canaries)


def validate_bundle(
    payload: Any, product: str, mode: str, probe: str, canaries: set[bytes], version: str | None
) -> int:
    require(isinstance(payload, dict) and payload.get("success") is True, "bundle_success")
    raw = json.dumps(payload, sort_keys=True).encode()
    require(len(raw) <= 32768, "envelope_size")
    require(not contains_private_canary(payload, canaries), "private_canary")
    require(set(payload) == {"success", "data"}, "envelope_schema")
    try:
        bundle = SupportBundle.model_validate(payload.get("data"))
    except ValueError:
        raise SupportSmokeError("bundle_schema") from None
    require(
        json.dumps(payload["data"], sort_keys=True) == json.dumps(bundle.model_dump(mode="json"), sort_keys=True),
        "complete_wire_schema",
    )
    require(bundle.product == product and bundle.probe.probe == probe, "product_probe_identity")
    require(bundle.runtime.registration_mode == mode, "registration_mode")
    require(bundle.runtime.content_mode == "dual", "adaptive_content_mode")
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
    definition = next(item for item in SKILL_PRODUCTS if item.slug == product)
    require(skill == render_support_skill(definition), "plugin_support_skill")
    require(codex["mcpServers"] == "./.mcp.json", "plugin_mcp_path")
    name = f"unifi-{product}"
    mcp_manifest = json.loads((folder / ".mcp.json").read_text())
    launcher = mcp_manifest["mcpServers"][name]
    expected_args = ["--python-preference", "system", f"unifi-{product}-mcp=={version}"]
    for config in (launcher, claude["mcpServers"][name]):
        require(config["command"] == "uvx" and config["args"] == expected_args, "plugin_launcher_alignment")
    # The repository artifacts are trusted, unlike --support-plugin-root. Allow
    # release-version changes only; reject extra servers, transports, hooks, and
    # every other host behavior that our manual stdio launch would not exercise.
    trusted_folder = Path(__file__).resolve().parents[1] / "plugins" / name
    expected_env = {}
    for filename, supplied in (
        (".codex-plugin/plugin.json", codex),
        (".claude-plugin/plugin.json", claude),
        (".mcp.json", mcp_manifest),
    ):
        expected = json.loads((trusted_folder / filename).read_text())
        if "version" in expected:
            expected["version"] = version
        if filename != ".codex-plugin/plugin.json":
            expected["mcpServers"][name]["args"] = expected_args
            expected_env = expected["mcpServers"][name]["env"]
            require(supplied["mcpServers"][name].get("env") == expected_env, "plugin_env_alignment")
        require(supplied == expected, "plugin_manifest_alignment")
    # Resolve the checked-in plugin environment exactly as a host would.
    inherited = dict(env)
    for key, expression in expected_env.items():
        match = re.fullmatch(r"\$\{([A-Z_]+):-([^}]*)\}", expression)
        require(match is not None, "plugin_env_expression")
        env[key] = inherited.get(match[1]) or match[2]
    return "uvx", expected_args, version


async def exercise_session(
    client: Any,
    product: str,
    mode: str,
    env: dict[str, str],
    version: str | None,
    before_probes: Callable[[], None] | None = None,
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
    if before_probes is not None:
        before_probes()

    async def call(arguments: dict[str, Any]) -> Any:
        result = await client.call_tool(name, arguments)
        require(INVALID_PROBE not in result.model_dump_json(), "invalid_input_echo")
        require(not contains_private_canary(json.loads(result.model_dump_json()), canaries), "mcp_private_canary")
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
        launch_root = Path(cache) / "cwd"
        launch_root.mkdir()
        for product in products:
            for mode in MODES:
                try:
                    env = support_environment(root, mode)
                    version = None
                    command, arguments = sys.executable, ["-m", f"unifi_{product}_mcp.main"]
                    if plugin_root is not None:
                        command, arguments, version = plugin_command(plugin_root, product, env)
                        env["UV_CACHE_DIR"] = cache
                    private_canaries(env)  # Reject unsupported short canaries before starting a server.
                    parameters = StdioServerParameters(command=command, args=arguments, env=env, cwd=launch_root)
                    with tempfile.TemporaryFile(mode="w+") as stderr:
                        probe_log_start = 0

                        def mark_probe_logs() -> None:
                            nonlocal probe_log_start
                            stderr.flush()
                            stderr.seek(0, 2)
                            probe_log_start = stderr.tell()

                        async with asyncio.timeout(180):
                            async with stdio_client(parameters, errlog=stderr) as streams:
                                async with ClientSession(*streams, read_timeout_seconds=90) as client:
                                    record = await exercise_session(
                                        client, product, mode, env, version, before_probes=mark_probe_logs
                                    )
                        stderr.seek(0)
                        log = stderr.read(1_048_577)
                        require(len(log) <= 1_048_576, "bounded_process_log")
                        require(INVALID_PROBE not in log, "invalid_input_log_echo")
                        # Ordinary startup diagnostics are not shareable support
                        # output. Check all logs after catalog discovery, including
                        # shutdown, without persisting either part in the report.
                        stderr.seek(probe_log_start)
                        require(
                            not contains_private_canary(stderr.read(), private_canaries(env)),
                            "probe_log_private_canary",
                        )
                    records.append(record)
                    print(f"support {product} {mode}: passed", flush=True)
                except Exception:
                    # Do not retry auth failures or serialize exceptions/ExceptionGroups.
                    records.append({"product": product, "mode": mode, "status": "failed"})
                    print(f"support {product} {mode}: failed (details suppressed for privacy)", flush=True)
                    return {"success": False, "records": records}
    return {"success": True, "records": records}
