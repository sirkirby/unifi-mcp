"""Meta-tools registration helper.

Provides a unified way to register meta-tools (tool_index, execute, batch,
batch_status, batch_cancel) that work in both MCP server mode and dev console mode.

Generic version extracted from the network app. All app-specific references
(like TOOL_MODULE_MAP) are injected as parameters rather than imported.

Each server uses its own prefix so tools are distinguishable when multiple
servers are loaded simultaneously:
- Network: ``unifi_tool_index``, ``unifi_execute``, ...
- Protect: ``protect_tool_index``, ``protect_execute``, ...
- Access:  ``access_tool_index``, ``access_execute``, ...
"""

import inspect
import logging
import time
import uuid
from typing import TYPE_CHECKING, Callable, List, Literal

from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations
from pydantic import SkipValidation
from unifi_core.operation_gate import signal_admitted

from unifi_mcp_shared.response_serialization import normalize_call_tool_result
from unifi_mcp_shared.tool_index import normalize_tool_annotations

if TYPE_CHECKING:
    from unifi_mcp_shared.lazy_tools import LazyToolLoader

logger = logging.getLogger(__name__)

META_TOOL_SUFFIXES: tuple[str, ...] = (
    "_tool_index",
    "_execute",
    "_batch",
    "_batch_status",
    "_batch_cancel",
    "_load_tools",
    "_get_support_bundle",
)

# Job states a batch job reports; ``position`` accompanies ``queued``.
BATCH_JOB_STATUSES: tuple[str, ...] = ("queued", "running", "done", "error", "cancelled", "unknown")

BATCH_ORDERING_NOTE = (
    "Writes execute one at a time in submission order; reads run concurrently, up to a cap. "
    "Queued jobs can be cancelled. Arguments are fixed at submission, and a batch does not stop on failure."
)


def _accepts_after(start_async_tool: Callable) -> bool:
    """Whether an injected job starter can chain a job after another (newer cores can)."""
    try:
        parameters = inspect.signature(start_async_tool).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.name == "after" or p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters)


def _default_cancel_job() -> Callable:
    from unifi_core.jobs import cancel_job

    return cancel_job


def is_meta_tool(name: str) -> bool:
    """Return True if ``name`` is one of the shared server-control meta-tools."""
    return name.endswith(META_TOOL_SUFFIXES)


# Default domain hints per prefix
_DEFAULT_DOMAIN_HINTS = {
    "unifi": "WiFi networks, clients, devices, switches, APs, firewall, VPN, routing, and statistics",
    "protect": "security cameras, recordings, snapshots, motion events, live views, and NVR management",
    "access": "door locks, access readers, credentials, visitors, access policies, and entry events",
    "sitemanager": "hosts, sites and devices across consoles, ISP metrics, and SD-WAN status from UniFi Site Manager",
    "drive": "NAS storage pools, RAID and disk health, shared drives, and SMB/NFS file services on UniFi Drive",
    "innerspace": "floor plans, walls, wall types and device placement from UniFi InnerSpace",
}


def _duration_bucket(duration_ms: float) -> str:
    if duration_ms < 100:
        return "under_100ms"
    if duration_ms < 1_000:
        return "100ms_1s"
    if duration_ms < 5_000:
        return "1s_5s"
    return "over_5s"


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
    *,
    support_bundle_handler: Callable | None = None,
    cancel_job: Callable | None = None,
) -> None:
    """Register meta-tools with the MCP server.

    Tools registered (using the configured prefix):
    - {prefix}_tool_index: Discover available tools
    - {prefix}_execute: Execute a single tool (returns result directly)
    - {prefix}_batch: Start several tools as jobs (returns job IDs)
    - {prefix}_batch_status: Check batch job progress
    - {prefix}_batch_cancel: Cancel batch jobs that have not started their change
    - {prefix}_get_support_bundle: Generate privacy-bounded support evidence

    Meta tools register with the plain ``tool_decorator``, never through
    ``permissioned_tool``, so they never enter a controller operation gate.
    Run as a batch job, the ones that reach no domain tool signal admission
    at once; ``*_execute`` is admitted by the domain tool it runs.

    Args:
        server: FastMCP server instance (for call_tool access)
        tool_decorator: The decorator function to register tools (@server.tool)
        tool_index_handler: Handler function for tool_index
        start_async_tool: Function to start async jobs
        get_job_status: Function to get job status
        register_tool: Function to register in tool index
        support_bundle_handler: Optional runtime callback. Omit for legacy apps
            that do not expose support bundles.
        cancel_job: Cancels one job by id (``unifi_core.jobs.cancel_job`` when
            omitted, which serves jobs in the process-wide job store).
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
    cancel_name = f"{prefix}_batch_cancel"
    support_name = f"{prefix}_get_support_bundle"
    cancel_job = cancel_job or _default_cancel_job()
    chain_jobs = _accepts_after(start_async_tool)

    hint = domain_hint or _DEFAULT_DOMAIN_HINTS.get(prefix, "controller management")
    idx_title = f"{server_label} Tool Index"
    exec_title = f"{server_label} Execute Tool"
    batch_title = f"{server_label} Batch Execute"
    status_title = f"{server_label} Batch Status"
    cancel_title = f"{server_label} Batch Cancel"
    support_title = f"{server_label} Support Bundle"
    read_annotations = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    action_annotations = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )
    cancel_annotations = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    # =========================================================================
    # SUPPORT: {prefix}_get_support_bundle
    # This uses the original server decorator and a dedicated safe audit line;
    # it must never pass through ordinary diagnostic argument/result logging.
    # =========================================================================
    if support_bundle_handler is not None:

        @tool_decorator(
            name=support_name,
            title=support_title,
            description=(
                f"Generate a sanitized, reviewable {server_label} support bundle. "
                "The default summary is local/cache-only. Live connectivity or resource-shape probes "
                "are bounded and may be unavailable for this product. The result excludes raw logs, "
                "credentials, controller payload values, and arbitrary exception text. Review the "
                "bundle before sharing it publicly."
            ),
            annotations=read_annotations,
        )
        async def _support_bundle_wrapper(
            probe: SkipValidation[Literal["summary", "connectivity", "resource_shape"]] = "summary",
            resource: SkipValidation[str | None] = None,
        ) -> dict:
            # Never queues at a controller gate: a batch may start its next job.
            signal_admitted()
            # Preserve the advertised schema, but validate only inside the service's
            # privacy boundary: Pydantic errors otherwise echo rejected input values.
            try:
                correlation_id = uuid.uuid4().hex
                started = time.monotonic()
                result = await support_bundle_handler(probe=probe, resource=resource)
                if not isinstance(result, dict):
                    result = {"success": False, "error": "Failed to generate support bundle."}
                outcome = "success" if result.get("success") is True else "failed"
                duration_bucket = _duration_bucket((time.monotonic() - started) * 1000)
            except Exception:
                result = {"success": False, "error": "Failed to generate support bundle."}
                correlation_id = uuid.uuid4().hex
                outcome = "failed"
                duration_bucket = "unknown"
            safe_probe = (
                probe
                if isinstance(probe, str) and probe in {"summary", "connectivity", "resource_shape"}
                else "invalid"
            )
            logger.info(
                "Support bundle audit correlation_id=%s probe=%s outcome=%s duration=%s",
                correlation_id,
                safe_probe,
                outcome,
                duration_bucket,
            )
            return result

        register_tool(
            name=support_name,
            title=support_title,
            description=(
                f"Generate sanitized {server_label} support evidence for user review. "
                "Summary is local/cache-only; live probes are bounded and explicitly allowlisted."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "probe": {
                        "type": "string",
                        "enum": ["summary", "connectivity", "resource_shape"],
                        "default": "summary",
                    },
                    "resource": {"type": ["string", "null"], "default": None},
                },
            },
            output_schema={
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "data": {"type": "object"},
                    "error": {"type": "string"},
                },
                "required": ["success"],
            },
            annotations=normalize_tool_annotations(read_annotations),
        )

    # =========================================================================
    # DISCOVERY: {prefix}_tool_index
    # =========================================================================
    @tool_decorator(
        name=idx_name,
        title=idx_title,
        description=(
            f"Model-friendly discovery extension for {server_label} tools. "
            f"This server manages {hint}. "
            "Standard MCP clients should use tools/list first; this compact index is an "
            "optional UniFi extension for filtered discovery. In meta_only mode, it "
            "starts with only meta-tools; domain entries appear after their module has "
            "been executed. "
            f"Returns names and descriptions by default. "
            f"Use 'category' to filter by area (e.g. clients, firewall, devices), "
            f"'search' for keyword matching, 'name' for exact lookup, or 'include_schemas' for full schemas. "
            f"After finding the right tool, use {exec_name} to run it."
        ),
        annotations=read_annotations,
    )
    async def _tool_index_wrapper(
        category: str | None = None,
        search: str | None = None,
        include_schemas: bool = False,
        name: str | None = None,
    ) -> dict:
        signal_admitted()
        args = {}
        if name is not None:
            args["name"] = name
        if category is not None:
            args["category"] = category
        if search is not None:
            args["search"] = search
        if include_schemas:
            args["include_schemas"] = include_schemas
        return await tool_index_handler(args or None)

    register_tool(
        name=idx_name,
        title=idx_title,
        description=(
            f"Discover {server_label} tools ({hint}) through the compact tool index. "
            "The catalog is manifest-backed in lazy mode; in meta-only mode it starts with "
            "registered meta-tools and expands after domain modules execute. "
            "Standard MCP clients should prefer tools/list when it exposes the needed tools."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Exact, case-sensitive tool name. Cannot be combined with category or search. "
                        "Unknown names return an empty index."
                    ),
                },
                "category": {
                    "type": "string",
                    "description": (
                        "Filter to one category. Valid values are returned in the 'categories' field of every response."
                    ),
                },
                "search": {
                    "type": "string",
                    "description": (
                        "Case-insensitive token search over tool names and descriptions. "
                        "Ignores common words and one-character terms; multi-word queries require at least half "
                        "of usable terms (minimum two). Terms of four or more characters also match token prefixes. "
                        "Results are ranked by exact phrase and name matches, with at most 20 returned. "
                        "An empty string applies no filter; a non-empty query with no usable terms returns no tools."
                    ),
                },
                "include_schemas": {
                    "type": "boolean",
                    "description": (
                        "Include full input/output schemas per tool. "
                        "Defaults to false — set true with a name, category or search filter "
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
                "filtered": {"type": "boolean", "description": "True when name, category or search filter was applied"},
            },
        },
        annotations=normalize_tool_annotations(read_annotations),
    )

    # =========================================================================
    # SINGLE EXECUTION: {prefix}_execute
    # =========================================================================
    @tool_decorator(
        name=exec_name,
        title=exec_title,
        description=(
            f"Execute a named {server_label} tool. "
            f"This server manages {hint}. "
            f"In lazy mode, use {idx_name} to discover domain tool names. In meta_only "
            "mode, the domain tool name must already be known. "
            "This is an indirect execution wrapper for lazy/meta-only workflows; "
            "standard MCP clients may call directly registered tools with tools/call. "
            f"For bulk/parallel operations, use {batch_name} instead."
        ),
        annotations=action_annotations,
    )
    async def execute_handler(tool: str, arguments: dict | None = None, ctx: Context | None = None) -> dict:
        """Execute a tool synchronously."""
        if arguments is None:
            arguments = {}

        try:
            result = await server.call_tool(tool, arguments, context=ctx)
            return normalize_call_tool_result(result)
        except Exception as e:
            logger.error("Error executing tool '%s': %s", tool, e, exc_info=True)
            return {"error": f"Failed to execute tool: {str(e)}"}

    register_tool(
        name=exec_name,
        title=exec_title,
        description=(f"Execute a {server_label} tool ({hint}) by name for lazy/meta-only workflows."),
        input_schema={
            "type": "object",
            "required": ["tool"],
            "properties": {
                "tool": {
                    "type": "string",
                    "description": (
                        f"Domain tool name (e.g. '{prefix}_list_*'); discover it through {idx_name} in lazy mode"
                    ),
                },
                "arguments": {
                    "type": ["object", "null"],
                    "description": "Tool parameters matching the domain tool's input schema",
                },
            },
        },
        output_schema={
            "type": "object",
            "description": f"Result from the executed {server_label} tool",
        },
        annotations=normalize_tool_annotations(action_annotations),
    )

    # =========================================================================
    # BATCH EXECUTION: {prefix}_batch
    # =========================================================================
    @tool_decorator(
        name=batch_name,
        title=batch_title,
        description=(
            f"Run several {server_label} tools as background jobs through an indirect execution wrapper. "
            f"{BATCH_ORDERING_NOTE} "
            f"Use {idx_name} to discover tool names in lazy mode when they are not directly registered. "
            f"Returns job IDs for each operation. Use {status_name} to check progress and get results, "
            f"and {cancel_name} to cancel queued jobs. "
            f"For single operations, use {exec_name} instead (returns result directly)."
        ),
        annotations=action_annotations,
    )
    async def batch_handler(operations: List[dict], ctx: Context | None = None) -> dict:
        """Start each operation as a job, each joining the controller's queue after the one before."""
        if not operations:
            return {"error": "No operations specified", "jobs": []}

        jobs = []
        errors = []
        # Each job starts once the job before it has joined the controller's
        # gate (or finished), so writes queue in submission order whatever
        # each one awaits first. The jobs are all created now; this call
        # returns at once.
        previous_job_id: str | None = None

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
                        result = await server.call_tool(t, a, context=ctx)
                        return normalize_call_tool_result(result)

                    return _execute

                executor = await _make_executor(tool, arguments)
                if chain_jobs and previous_job_id is not None:
                    job_result = await start_async_tool(executor, {}, after=previous_job_id)
                else:
                    job_result = await start_async_tool(executor, {})
                if isinstance(job_result.get("jobId"), str):
                    previous_job_id = job_result["jobId"]

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
        title=batch_title,
        description=(
            f"Run several {server_label} tools as background jobs through the indirect execution wrapper. "
            f"{BATCH_ORDERING_NOTE} Returns job IDs; use {status_name} to check progress and "
            f"{cancel_name} to cancel queued jobs."
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
                                "description": (
                                    f"Tool name from {idx_name} in lazy mode, or a known domain tool name "
                                    "in meta-only mode"
                                ),
                            },
                            "arguments": {
                                "type": "object",
                                "description": "Tool parameters matching the domain tool's input schema",
                            },
                        },
                    },
                    "description": (
                        f"Array of {{tool, arguments}} objects using names from {idx_name} in lazy mode, "
                        "or known domain tool names in meta-only mode"
                    ),
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
        annotations=normalize_tool_annotations(action_annotations),
    )

    # =========================================================================
    # BATCH STATUS: {prefix}_batch_status
    # =========================================================================
    @tool_decorator(
        name=status_name,
        title=status_title,
        description=(
            f"Check status of {server_label} operations started with {batch_name}. "
            f"Returns status ('queued' with its queue position, 'running', 'done', 'error' or 'cancelled'), "
            f"result (if done), or error (if failed). "
            f"Can check multiple jobs at once by passing an array of job IDs."
        ),
        annotations=read_annotations,
    )
    async def batch_status_handler(jobId: str = None, jobIds: List[str] = None) -> dict:
        """Check status of one or more jobs."""
        signal_admitted()
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
        title=status_title,
        description=(
            f"Check status of {server_label} batch operations. Returns status (with the queue position "
            "while queued), result (if done), or error (if failed)."
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
                    "enum": list(BATCH_JOB_STATUSES),
                    "description": (
                        "Current job status. 'queued' waits for an earlier job or its write turn; "
                        "'cancelled' never ran."
                    ),
                },
                "position": {
                    "type": ["integer", "null"],
                    "description": (
                        "While queued: write operations ahead of this job (1 = next; 0 = starting). "
                        "Null while it waits for an earlier job in its batch."
                    ),
                },
                "result": {"description": "Job result (present when status is 'done')"},
                "error": {"type": "string", "description": "Error message (present when status is 'error')"},
                "jobs": {
                    "type": "array",
                    "description": "Status of multiple jobs (when using jobIds parameter)",
                },
            },
        },
        annotations=normalize_tool_annotations(read_annotations),
    )

    # =========================================================================
    # BATCH CANCEL: {prefix}_batch_cancel
    # =========================================================================
    @tool_decorator(
        name=cancel_name,
        title=cancel_title,
        description=(
            f"Cancel {server_label} jobs started with {batch_name} that have not started their change. "
            "A queued job is withdrawn and never runs. A running or finished job is not cancelled: "
            "a change already sent to the controller cannot be recalled. "
            "Pass one jobId or an array of jobIds."
        ),
        annotations=cancel_annotations,
    )
    async def batch_cancel_handler(jobId: str = None, jobIds: List[str] = None) -> dict:
        """Cancel one or more queued jobs."""
        signal_admitted()

        async def _cancel(job_id: str) -> dict:
            try:
                outcome = await cancel_job(job_id)
            except Exception as e:
                logger.error("Error cancelling job '%s': %s", job_id, e, exc_info=True)
                return {"jobId": job_id, "cancelled": False, "status": "unknown", "reason": str(e)}
            return {"jobId": job_id, **outcome}

        if jobId and not jobIds:
            return await _cancel(jobId)
        if jobIds:
            return {"jobs": [await _cancel(job_id) for job_id in jobIds]}
        return {"error": "Provide jobId or jobIds parameter"}

    cancel_outcome_schema = {
        "type": "object",
        "properties": {
            "jobId": {"type": "string"},
            "cancelled": {"type": "boolean", "description": "True when the job was withdrawn before it ran"},
            "status": {"type": "string", "enum": list(BATCH_JOB_STATUSES), "description": "Status after the call"},
            "reason": {"type": "string", "description": "Why the job was not cancelled"},
        },
    }
    register_tool(
        name=cancel_name,
        title=cancel_title,
        description=(
            f"Cancel queued {server_label} batch jobs. Jobs already running or finished are reported, not cancelled."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "jobId": {"type": "string", "description": "Single job ID to cancel"},
                "jobIds": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Multiple job IDs to cancel at once",
                },
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                **cancel_outcome_schema["properties"],
                "jobs": {
                    "type": "array",
                    "items": cancel_outcome_schema,
                    "description": "Outcome per job (when using jobIds parameter)",
                },
                "error": {"type": "string"},
            },
        },
        annotations=normalize_tool_annotations(cancel_annotations),
    )

    names = [idx_name, exec_name, batch_name, status_name, cancel_name]
    if support_bundle_handler is not None:
        names.append(support_name)
    logger.info("Registered meta-tools: %s", ", ".join(names))


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

    This enables direct tool access for MCP clients that support
    notifications/tools/list_changed. Most users should use {prefix}_execute
    instead - it works with all clients.

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
    load_name = f"{prefix}_load_tools"
    exec_name = f"{prefix}_execute"
    hint = domain_hint or _DEFAULT_DOMAIN_HINTS.get(prefix, "controller management")
    load_title = f"{server_label} Load Tools"
    load_annotations = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    @tool_decorator(
        name=load_name,
        title=load_title,
        description=(
            f"Load {server_label} tools ({hint}) into the standard MCP tools/list surface. "
            "This is an advanced UniFi extension for lazy mode clients that support "
            "notifications/tools/list_changed. "
            f"Clients that do not refresh tool lists should use {exec_name} instead."
        ),
        annotations=load_annotations,
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
                await ctx.notify_tools_changed()
                logger.info("Sent notifications/tools/list_changed after loading: %s", loaded)
            except Exception as e:
                logger.warning("Failed to send tool_list_changed notification: %s", e)

        return {
            "loaded": loaded,
            "errors": errors if errors else None,
            "message": f"Loaded {len(loaded)} tool(s). Client should refresh tool list.",
        }

    register_tool(
        name=load_name,
        title=load_title,
        description=(
            f"Load {server_label} tools ({hint}) for direct MCP access. "
            "Advanced lazy-mode extension that emits notifications/tools/list_changed when tools are loaded."
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
        annotations=normalize_tool_annotations(load_annotations),
    )

    logger.info("Registered %s meta-tool for dynamic tool loading", load_name)
