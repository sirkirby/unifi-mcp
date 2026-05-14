from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

# Defer heavy imports until runtime is needed to provide clearer errors
logger = None  # type: ignore


def _print(title: str = "", obj: Any = None) -> None:
    if title:
        print(f"\n=== {title} ===")
    if obj is not None:
        try:
            print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))
        except Exception:
            print(str(obj))


async def _ensure_connected(connection_manager) -> bool:
    ok = await connection_manager.initialize()
    if not ok:
        logger.error("Unable to establish UniFi Access connection. Check your config/credentials.")
        return False

    print("Connected to UniFi Access controller.")
    return True


async def _list_tools(server) -> List[Any]:
    """List all registered tools from the MCP server."""
    try:
        tools = await server.list_tools()
        return tools
    except Exception as exc:
        logger.error("Failed to list tools: %s", exc)
        return []


def _get_all_tools_from_index() -> List[Dict[str, Any]]:
    """Get all tools from the tool index, regardless of permission status."""
    try:
        from unifi_access_mcp.tool_index import get_tool_index

        index = get_tool_index()
        return index.get("tools", [])
    except Exception as exc:
        logger.error("Failed to get tool index: %s", exc)
        return []


async def _list_all_tools_with_status(server) -> List[tuple[Dict[str, Any], bool]]:
    """List all tools with their enabled/disabled status."""
    all_tools = _get_all_tools_from_index()
    enabled_tools = await _list_tools(server)
    enabled_names = {tool.name for tool in enabled_tools}

    tools_with_status = []
    for tool in all_tools:
        tool_name = tool.get("name", "")
        is_enabled = tool_name in enabled_names
        tools_with_status.append((tool, is_enabled))

    return tools_with_status


def _prompt(prompt: str, default: Optional[str] = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val if val else (default or "")


def _coerce_value(val: str, schema: Optional[Dict[str, Any]]) -> Any:
    if schema is None:
        return val
    t = schema.get("type") if isinstance(schema, dict) else None
    if val == "" and schema.get("default") is not None:
        return schema["default"]
    if t == "boolean":
        return val.strip().lower() in {"1", "true", "yes", "on"}
    if t == "integer":
        try:
            return int(val)
        except Exception:
            return val
    if t == "number":
        try:
            return float(val)
        except Exception:
            return val
    if t in {"array", "object"}:
        try:
            parsed = json.loads(val)
            return parsed
        except Exception:
            return val
    return val


def _parse_args_with_schema(params_schema: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    print("Enter JSON arguments (single line). Press Enter for guided prompts.")
    hint = None
    if params_schema and isinstance(params_schema, dict):
        hint = {
            "properties": params_schema.get("properties", {}),
            "required": params_schema.get("required", []),
        }
    if hint:
        try:
            print("Hint (not validated):")
            print(json.dumps(hint, indent=2, ensure_ascii=False, default=str))
        except Exception:
            pass
    line = input("> ").strip()

    if line.startswith("{") or line.startswith("["):
        try:
            data = json.loads(line)
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.error("Invalid JSON: %s. Proceeding to guided prompts.", exc)

    if line and params_schema:
        req = params_schema.get("required", []) or []
        props = params_schema.get("properties", {}) or {}
        if isinstance(req, list) and len(req) == 1 and isinstance(props, dict) and req[0] in props:
            only_key = req[0]
            coerced = _coerce_value(line, props.get(only_key))
            return {only_key: coerced}

    args: Dict[str, Any] = {}
    if params_schema and isinstance(params_schema, dict):
        props = params_schema.get("properties", {}) or {}
        required = params_schema.get("required", []) or []
        for key in required:
            sch = props.get(key) if isinstance(props, dict) else None
            default = sch.get("default") if isinstance(sch, dict) else None
            val = _prompt(f"{key}", str(default) if default is not None else None)
            args[key] = _coerce_value(val, sch)
        return args

    return {}


async def _invoke_tool(server, tool) -> None:
    name = tool.name
    desc = tool.description or ""
    input_schema = getattr(tool, "inputSchema", None) or {}
    schema_props = input_schema.get("properties", {}) if isinstance(input_schema, dict) else {}
    _print("Tool", {"name": name, "description": desc})

    args: Dict[str, Any] = {}
    args = _parse_args_with_schema(input_schema if isinstance(input_schema, dict) else None)

    if "confirm" in schema_props:
        if "confirm" not in args or args.get("confirm") is False:
            print("\n  DEV CONSOLE: Auto-setting confirm=true for testing")
            print("   (In production, LLMs must explicitly confirm operations)\n")
            args["confirm"] = True

    _print("Invoking", {"tool": name, "args": args})

    try:
        result = await server.call_tool(name, args)
        _print("Result", result)
    except Exception as exc:
        logger.error("Tool execution failed: %s", exc)


async def main_async() -> None:
    global logger
    try:
        from unifi_access_mcp.bootstrap import logger as _logger

        logger = _logger
    except Exception:

        class _Fallback:
            def info(self, *a, **k):
                print(*a)

            def warning(self, *a, **k):
                print(*a)

            def error(self, *a, **k):
                print(*a)

        logger = _Fallback()  # type: ignore

    logger.info("Access Developer console starting...")

    try:
        import unifi_access_mcp.main  # noqa: F401, E402
        from unifi_access_mcp.jobs import get_job_status, start_async_tool  # noqa: E402
        from unifi_access_mcp.runtime import connection_manager, server  # noqa: E402
        from unifi_access_mcp.tool_index import register_tool, tool_index_handler  # noqa: E402
        from unifi_mcp_shared.meta_tools import register_meta_tools  # noqa: E402
        from unifi_mcp_shared.tool_loader import auto_load_tools  # noqa: E402
    except ModuleNotFoundError as e:
        if str(e).startswith("No module named 'mcp'"):
            print("\nERROR: Python MCP SDK not found (module 'mcp').")
            print("Fix:")
            print("  - Activate the project venv: source venv/bin/activate")
            print("  - Or install the SDK: pip install mcp  # or: uv pip install mcp")
            print("  - Then run: python devtools/dev_console.py\n")
            return
        raise

    try:
        auto_load_tools(base_package="unifi_access_mcp.tools")

        register_meta_tools(
            server=server,
            tool_decorator=server.tool,
            tool_index_handler=tool_index_handler,
            start_async_tool=start_async_tool,
            get_job_status=get_job_status,
            register_tool=register_tool,
            prefix="access",
            server_label="UniFi Access",
        )

        if not await _ensure_connected(connection_manager):
            return

        print("\n" + "=" * 70)
        print("UniFi Access MCP - Developer Console")
        print("=" * 70)
        print("  This console shows ALL tools, including those disabled by permissions.")
        print("  Disabled tools are marked with [DISABLED] and cannot be executed.")
        print("  To enable them, edit permissions in src/config/config.yaml")
        print("")
        print("  Example commands to try:")
        print("    - access_list_doors: List all doors")
        print("    - access_list_events: List recent access events")
        print("    - access_get_system_info: Get Access system information")
        print("    - access_list_devices: List Access hardware devices")
        print("=" * 70 + "\n")

        tools_with_status = await _list_all_tools_with_status(server)
        if not tools_with_status:
            print("No tools found in tool index.")
            return

        enabled_tools = [(tool, idx) for idx, (tool, enabled) in enumerate(tools_with_status, start=1) if enabled]
        disabled_tools = [(tool, idx) for idx, (tool, enabled) in enumerate(tools_with_status, start=1) if not enabled]

        def _show_tool_list():
            print(f"\n{'=' * 70}")
            print(f"Available Tools ({len(enabled_tools)} enabled, {len(disabled_tools)} disabled)")
            print(f"{'=' * 70}")

            for idx, (tool, enabled) in enumerate(tools_with_status, start=1):
                status = "[OK]" if enabled else "[DISABLED]"
                name = tool.get("name", "unknown")
                desc = tool.get("description", "")
                print(f"  {idx:3d}. {status:15s} {name} - {desc}")

            print(f"\n  {0:3d}. Exit")

            if disabled_tools:
                print(f"\n  Tip: {len(disabled_tools)} tools are disabled by permissions.")
                print("   Edit permissions in src/config/config.yaml to enable them.")

        _show_tool_list()

        while True:
            choice = _prompt("\nSelect tool [0=exit, l=list]", "0").strip().lower()

            if choice in ("l", "list"):
                _show_tool_list()
                continue

            if not choice.isdigit():
                print("Enter a tool number, 'l' to list tools, or 0 to exit.")
                continue
            num = int(choice)
            if num == 0:
                print("Goodbye.")
                return

            if 1 <= num <= len(tools_with_status):
                tool, is_enabled = tools_with_status[num - 1]
                if not is_enabled:
                    print(f"\n  Tool '{tool.get('name')}' is DISABLED by permissions.")
                    print("   This tool cannot be executed until permissions are enabled.")
                    print("   Edit src/config/config.yaml to enable specific permissions.")
                    continue

                tool_name = tool.get("name")
                enabled_tool_list = await _list_tools(server)
                actual_tool = next((t for t in enabled_tool_list if t.name == tool_name), None)

                if actual_tool:
                    await _invoke_tool(server, actual_tool)
                else:
                    print(f"Error: Could not find enabled tool '{tool_name}'")
            else:
                print("Out of range.")
    finally:
        await connection_manager.close()


def main() -> None:
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\nExiting.")


if __name__ == "__main__":
    main()
