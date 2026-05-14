"""Meta-tools registration helper.

Provides a unified way to register meta-tools (tool_index, execute, batch, job_status)
that work in both MCP server mode and dev console mode.

Generic version extracted from the network app. All app-specific references
(like TOOL_MODULE_MAP) are injected as parameters rather than imported.

Each server uses its own prefix so tools are distinguishable when multiple
servers are loaded simultaneously:
- Network: ``unifi_tool_index``, ``unifi_execute``, ...
- Protect: ``protect_tool_index``, ``protect_execute``, ...
- Access:  ``access_tool_index``, ``access_execute``, ...
"""

import logging
from typing import TYPE_CHECKING, Callable, List

from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from unifi_mcp_shared.lazy_tools import LazyToolLoader

logger = logging.getLogger(__name__)

# Default domain hints per prefix
_DEFAULT_DOMAIN_HINTS = {
    "unifi": "WiFi networks, clients, devices, switches, APs, firewall, VPN, routing, and statistics",
    "protect": "security cameras, recordings, snapshots, motion events, live views, and NVR management",
    "access": "door locks, access readers, credentials, visitors, access policies, and entry events",
}


def register_meta_tools(
    server,
    tool_decorator: Callable,
    tool_index_handler: Callable,
    start_async_tool: Callable,
    get_job_status: Callable,
    register_tool: Callable,
    prefix: str = "unifi",
    server_label: str = "UniFi Network",
    domain_hint: str | None = None,
) -> None:
    """Register meta-tools with the MCP server.

    Tools registered (using the configured prefix):
    - {prefix}_tool_index: Discover available tools
    - {prefix}_execute: Execute a single tool (returns result directly)
    - {prefix}_batch: Execute multiple tools in parallel (returns job IDs)
    - {prefix}_batch_status: Check batch job progress

    Args:
        server: FastMCP server instance (for call_tool access)
        tool_decorator: The decorator function to register tools (@server.tool)
        tool_index_handler: Handler function for tool_index
        start_async_tool: Function to start async jobs
        get_job_status: Function to get job status
        register_tool: Function to register in tool index
        prefix: Tool name prefix (e.g. "unifi", "protect", "access").
        server_label: Human-readable server name for descriptions
                      (e.g. "UniFi Network", "UniFi Protect").
        domain_hint: Short description of the tool domain for LLM context.
                     Falls back to a built-in default per prefix.
    """
    idx_name = f"{prefix}_tool_index"
    exec_name = f"{prefix}_execute"
    batch_name = f"{prefix}_batch"
    status_name = f"{prefix}_batch_status"

    hint = domain_hint or _DEFAULT_DOMAIN_HINTS.get(prefix, "controller management")

    # =========================================================================
    # DISCOVERY: {prefix}_tool_index
    # =========================================================================
    @tool_decorator(
        name=idx_name,
        description=(
            f"Discover available {server_label} tools. "
            f"This server manages {hint}. "
            f"CALL THIS FIRST to find the right tool for your task. "
            f"Returns names and descriptions by default (~38K chars). "
            f"Use 'category' to filter by area (e.g. clients, firewall, devices), "
            f"'search' for keyword matching, or 'include_schemas' for full parameter schemas. "
            f"After finding the right tool, use {exec_name} to run it."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def _tool_index_wrapper(
        category: str | None = None,
        search: str | None = None,
        include_schemas: bool = False,
    ) -> dict:
        args = {}
        if category is not None:
            args["category"] = category
        if search is not None:
            args["search"] = search
        if include_schemas:
            args["include_schemas"] = include_schemas
        return await tool_index_handler(args or None)

    register_tool(
        name=idx_name,
        description=(
            f"Discover {server_label} tools ({hint}). "
            f"Filter with category/search; use include_schemas for full parameter details."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": (
                        "Filter to one category. Valid values are returned in the 'categories' field of every response."
                    ),
                },
                "search": {
                    "type": "string",
                    "description": "Case-insensitive substring match against tool name and description.",
                },
                "include_schemas": {
                    "type": "boolean",
                    "description": (
                        "Include full input/output schemas per tool. "
                        "Defaults to false — set true with a category or search filter "
                        "to get parameter details for specific tools."
                    ),
                    "default": False,
                },
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "tools": {
                    "type": "array",
                    "description": "Matching tools with name and description (plus schemas if include_schemas)",
                },
                "count": {"type": "integer", "description": "Number of tools returned"},
                "categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "All available category names (use as values for the category filter)",
                },
                "filtered": {"type": "boolean", "description": "True when category or search filter was applied"},
            },
        },
    )

    # =========================================================================
    # SINGLE EXECUTION: {prefix}_execute
    # =========================================================================
    @tool_decorator(
        name=exec_name,
        description=(
            f"Execute a {server_label} tool discovered via {idx_name}. "
            f"This server manages {hint}. "
            f"WORKFLOW: Call {idx_name} first to find the right tool, then execute it here. "
            f"For bulk/parallel operations, use {batch_name} instead."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def execute_handler(tool: str, arguments: dict = None) -> dict:
        """Execute a tool synchronously."""
        if arguments is None:
            arguments = {}

        try:
            result = await server.call_tool(tool, arguments)
            return result
        except Exception as e:
            logger.error("Error executing tool '%s': %s", tool, e, exc_info=True)
            return {"error": f"Failed to execute tool: {str(e)}"}

    register_tool(
        name=exec_name,
        description=(f"Execute a {server_label} tool ({hint}). Call {idx_name} first to discover tools."),
        input_schema={
            "type": "object",
            "required": ["tool"],
            "properties": {
                "tool": {
                    "type": "string",
                    "description": f"Tool name from {idx_name} (e.g. '{prefix}_list_*')",
                },
                "arguments": {
                    "type": "object",
                    "description": "Tool parameters matching the schema from the tool index",
                },
            },
        },
        output_schema={
            "type": "object",
            "description": f"Result from the executed {server_label} tool",
        },
    )

    # =========================================================================
    # BATCH EXECUTION: {prefix}_batch
    # =========================================================================
    @tool_decorator(
        name=batch_name,
        description=(
            f"Execute multiple {server_label} tools in parallel. "
            f"WORKFLOW: Call {idx_name} first to discover tools, then batch execute them here. "
            f"Returns job IDs for each operation. Use {status_name} to check progress and get results. "
            f"For single operations, use {exec_name} instead (returns result directly)."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def batch_handler(operations: List[dict]) -> dict:
        """Execute multiple operations in parallel."""
        if not operations:
            return {"error": "No operations specified", "jobs": []}

        jobs = []
        errors = []

        for i, op in enumerate(operations):
            tool = op.get("tool")
            arguments = op.get("arguments", {})

            if not tool:
                errors.append({"index": i, "error": "Missing 'tool' field"})
                continue

            try:
                # Create a closure that captures the current tool and arguments
                async def _make_executor(t, a):
                    async def _execute():
                        return await server.call_tool(t, a)

                    return _execute

                executor = await _make_executor(tool, arguments)
                job_result = await start_async_tool(executor, {})

                jobs.append(
                    {
                        "index": i,
                        "tool": tool,
                        "jobId": job_result.get("jobId"),
                    }
                )
            except Exception as e:
                logger.error("Error starting batch operation %d (%s): %s", i, tool, e, exc_info=True)
                errors.append({"index": i, "tool": tool, "error": str(e)})

        return {
            "jobs": jobs,
            "errors": errors if errors else None,
            "message": f"Started {len(jobs)} operation(s). Use {status_name} to check progress.",
        }

    register_tool(
        name=batch_name,
        description=(
            f"Execute multiple {server_label} tools in parallel. Returns job IDs; use {status_name} to check progress."
        ),
        input_schema={
            "type": "object",
            "required": ["operations"],
            "properties": {
                "operations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["tool"],
                        "properties": {
                            "tool": {
                                "type": "string",
                                "description": f"Tool name from {idx_name}",
                            },
                            "arguments": {
                                "type": "object",
                                "description": "Tool parameters matching the schema from the tool index",
                            },
                        },
                    },
                    "description": f"Array of {{tool, arguments}} objects using tool names from {idx_name}",
                },
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "jobs": {
                    "type": "array",
                    "description": "Started jobs with index, tool name, and jobId",
                    "items": {
                        "type": "object",
                        "properties": {
                            "index": {"type": "integer"},
                            "tool": {"type": "string"},
                            "jobId": {"type": "string"},
                        },
                    },
                },
                "errors": {
                    "type": "array",
                    "description": "Errors for operations that failed to start",
                },
                "message": {"type": "string"},
            },
        },
    )

    # =========================================================================
    # BATCH STATUS: {prefix}_batch_status
    # =========================================================================
    @tool_decorator(
        name=status_name,
        description=(
            f"Check status of {server_label} operations started with {batch_name}. "
            f"Returns status ('running', 'done', 'error'), result (if done), or error (if failed). "
            f"Can check multiple jobs at once by passing an array of job IDs."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def batch_status_handler(jobId: str = None, jobIds: List[str] = None) -> dict:
        """Check status of one or more jobs."""
        # Handle single job ID
        if jobId and not jobIds:
            try:
                status = await get_job_status(jobId)
                return status
            except Exception as e:
                logger.error("Error getting job status for '%s': %s", jobId, e, exc_info=True)
                return {"status": "error", "error": str(e)}

        # Handle multiple job IDs
        if jobIds:
            results = []
            for jid in jobIds:
                try:
                    status = await get_job_status(jid)
                    results.append({"jobId": jid, **status})
                except Exception as e:
                    results.append({"jobId": jid, "status": "error", "error": str(e)})
            return {"jobs": results}

        return {"error": "Provide jobId or jobIds parameter"}

    register_tool(
        name=status_name,
        description=(
            f"Check status of {server_label} batch operations. Returns status, result (if done), or error (if failed)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "jobId": {"type": "string", "description": "Single job ID to check"},
                "jobIds": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Multiple job IDs to check at once",
                },
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["running", "done", "error", "unknown"],
                    "description": "Current job status",
                },
                "result": {"description": "Job result (present when status is 'done')"},
                "error": {"type": "string", "description": "Error message (present when status is 'error')"},
                "jobs": {
                    "type": "array",
                    "description": "Status of multiple jobs (when using jobIds parameter)",
                },
            },
        },
    )

    logger.info("Registered meta-tools: %s, %s, %s, %s", idx_name, exec_name, batch_name, status_name)


def register_load_tools(
    server,
    tool_decorator: Callable,
    lazy_loader: "LazyToolLoader",
    register_tool: Callable,
    tool_module_map: dict,
    prefix: str = "unifi",
    server_label: str = "UniFi Network",
    domain_hint: str | None = None,
) -> None:
    """Register load_tools for dynamic tool loading (capable clients only).

    This enables direct tool access for MCP clients that support tool_list_changed notifications.
    Most users should use {prefix}_execute instead - it works with all clients.

    Args:
        server: FastMCP server instance
        tool_decorator: The decorator function to register tools
        lazy_loader: LazyToolLoader instance
        register_tool: Function to register in tool index
        tool_module_map: Mapping of tool names to their module paths
        prefix: Tool name prefix (e.g. "unifi", "protect", "access").
        server_label: Human-readable server name for descriptions.
        domain_hint: Short description of the tool domain for LLM context.
    """
    from mcp.server.fastmcp import Context

    load_name = f"{prefix}_load_tools"
    exec_name = f"{prefix}_execute"
    hint = domain_hint or _DEFAULT_DOMAIN_HINTS.get(prefix, "controller management")

    @tool_decorator(
        name=load_name,
        description=(
            f"Load {server_label} tools ({hint}) for direct MCP access (advanced). "
            f"Most users should use {exec_name} instead - it works with all clients. "
            f"This tool is for MCP clients that support tool_list_changed notifications. "
            f"After loading, the client is notified to refresh its tool list."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def load_tools_handler(tools: List[str], ctx: Context) -> dict:
        """Load specific tools and notify the client."""
        if not tools:
            return {"error": "No tools specified", "loaded": [], "errors": []}

        loaded = []
        errors = []

        for tool_name in tools:
            if tool_name not in tool_module_map:
                errors.append({"tool": tool_name, "error": "Unknown tool"})
                continue

            try:
                success = await lazy_loader.load_tool(tool_name)
                if success:
                    loaded.append(tool_name)
                else:
                    errors.append({"tool": tool_name, "error": "Failed to load"})
            except Exception as e:
                logger.error("Error loading tool '%s': %s", tool_name, e, exc_info=True)
                errors.append({"tool": tool_name, "error": str(e)})

        if loaded:
            try:
                await ctx.session.send_tool_list_changed()
                logger.info("Sent tool_list_changed notification after loading: %s", loaded)
            except Exception as e:
                logger.warning("Failed to send tool_list_changed notification: %s", e)

        return {
            "loaded": loaded,
            "errors": errors if errors else None,
            "message": f"Loaded {len(loaded)} tool(s). Client should refresh tool list.",
        }

    register_tool(
        name=load_name,
        description=(
            f"Load {server_label} tools ({hint}) for direct MCP access. "
            f"Advanced - most users should use {exec_name} instead."
        ),
        input_schema={
            "type": "object",
            "required": ["tools"],
            "properties": {
                "tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": f"Tool names to load (from {prefix}_tool_index)",
                },
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "loaded": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Successfully loaded tool names",
                },
                "errors": {
                    "type": "array",
                    "description": "Errors for tools that failed to load",
                },
                "message": {"type": "string", "description": "Summary message"},
            },
        },
    )

    logger.info("Registered %s meta-tool for dynamic tool loading", load_name)
