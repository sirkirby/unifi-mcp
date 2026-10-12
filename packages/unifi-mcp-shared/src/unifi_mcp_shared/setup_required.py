"""Setup-required startup: serve MCP without a controller host.

A server whose controller host is not configured still answers ``initialize``
so the client shows it as connected and the model learns why it has no tools.
It registers one read-only status tool and nothing that can reach a controller:
no controller tools, no connection manager initialization, no event listener.
Credentials that are configured without a host are therefore never sent
anywhere, which is the property the earlier startup refusal protected.

Some clients (Claude Code) add server ``instructions`` to the model context;
others (Codex) do not, so the same text is also returned by the status tool.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.types import ToolAnnotations

from unifi_mcp_shared.settings_file import SETTINGS_FILE_VAR, SettingsFileReport


def controller_host_configured(cfg: Any) -> bool:
    """Whether the loaded config names a controller host."""
    try:
        return bool(str(cfg.unifi.get("host", "") or "").strip())
    except Exception:
        return False


def setup_required_message(*, plugin_name: str, env_prefix: str, report: SettingsFileReport | None) -> str:
    """The client-neutral setup guidance for an unconfigured server.

    Names variables and the settings file's state, never a value or path, since
    it is sent to the client.
    """
    product = env_prefix.lower()
    var = f"UNIFI_{env_prefix}_"
    lines = [
        f"The {plugin_name} MCP server is not configured: no controller host is set. It is running in "
        "setup mode with no controller tools and makes no controller connections.",
        "",
        "To configure it:",
        f"- Claude Code: run /{plugin_name}:{plugin_name}-setup. It also migrates settings an older plugin "
        "version saved in .claude/settings.local.json.",
        f"- Codex or OpenClaw: run the {plugin_name}-setup skill. It writes ~/.config/unifi-mcp/{product}.env, "
        f"which this server reads through {SETTINGS_FILE_VAR}.",
        f"- Any other launcher: set {var}HOST, {var}USERNAME and {var}PASSWORD in the server's environment, "
        f"or put them in a file named by {SETTINGS_FILE_VAR}.",
    ]
    if report is not None and report.state == "missing":
        lines.append(f"The file named by {SETTINGS_FILE_VAR} does not exist yet; setup creates it.")
    elif report is not None and report.state == "ignored":
        lines.append(f"The file named by {SETTINGS_FILE_VAR} was ignored; the server log says why.")
    lines += [
        "",
        "Then load the new settings:",
        "- Claude Code: run /reload-plugins or start a new session. /mcp reconnect does not load new plugin options.",
        "- Codex: restart Codex or start a new session.",
        "- OpenClaw: start a new session or run openclaw gateway restart.",
        "- Standalone: restart the server.",
        "",
        "Any other UniFi plugins you have installed (Network, Protect, Access) need the same setup or migration.",
    ]
    return "\n".join(lines)


async def serve_setup_required(
    *,
    server: Any,
    config: Any,
    plugin_name: str,
    env_prefix: str,
    tool_prefix: str,
    default_port: int,
    logger: logging.Logger,
) -> None:
    """Run the server's transports in setup mode until the client disconnects."""
    from unifi_mcp_shared import bootstrap
    from unifi_mcp_shared.transport import resolve_http_config, run_transports

    message = setup_required_message(plugin_name=plugin_name, env_prefix=env_prefix, report=bootstrap._SETTINGS_REPORT)
    for line in message.splitlines():
        logger.warning("[setup] %s", line)
    report = bootstrap._SETTINGS_REPORT
    if report is not None and report.state in {"missing", "ignored"}:
        logger.warning("[setup] %s names %s.", SETTINGS_FILE_VAR, report.path)

    server._lowlevel_server.instructions = message
    settings_state = report.state if report is not None else "unset"

    @server.tool(
        name=f"{tool_prefix}_setup_status",
        description=(
            f"Report why the {plugin_name} server has no controller tools, how to configure it and how to "
            "load the new settings. Call this when the server's tools are missing."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    )
    async def setup_status() -> dict[str, Any]:
        return {
            "success": True,
            "data": {"configured": False, "settings_file": settings_state, "message": message},
        }

    http_enabled, http_transport, host, port = resolve_http_config(
        config.server, default_port=default_port, logger=logger
    )
    await run_transports(
        server=server,
        http_enabled=http_enabled,
        host=host,
        port=port,
        http_transport=http_transport,
        logger=logger,
    )
