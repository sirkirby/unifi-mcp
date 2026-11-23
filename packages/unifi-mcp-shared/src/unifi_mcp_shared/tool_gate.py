"""Run each domain tool call through its controller's operation gate.

``unifi_core.operation_gate`` holds the primitive: one gate per controller
application, with exclusive first-in-first-out writes and capped shared reads.
This module decides, per tool call, which mode the call needs and enters it as
the outermost layer around the registered tool, outside the apps' connection
wait. Meta tools never pass through here: they register with the plain tool
decorator, so ``*_execute`` and ``*_batch`` reach the gate only through the
domain tool they run.

A call is a **write** when the tool's ``permission_action`` is create, update
or delete, unless the tool declares ``confirm`` and the call resolves it to
False (a preview), after bypass mode would inject ``confirm=True``. Everything
else is a **read**. A call the policy gate will deny takes no gate: it never
reaches the controller.

Direct calls wait at most the server's direct-call wait budget for their turn;
calls made by a batch job wait as long as the queue keeps moving. A call that
cannot get its turn returns the tool error contract with the busy reason,
having sent nothing to the controller.

A write whose controller request is cut off at its hold budget fails with
``mutation_applied``: ``false`` when nothing of it was sent, ``null`` when the
change may have reached the controller. The gate records the cut-off on the
write ticket, so this holds even when the tool caught the timeout; a tool
that reports ``mutation_applied`` itself is left as it is.

Every domain tool signals its admission to a batch job runner, gate or not: a
server that wires no gate provider gets an admission-only wrapper, so its batch
jobs, which start one after another once the job before is admitted, still run
side by side. A read job waiting for a read slot reports ``running`` and cannot
be cancelled; only a write waiting for its turn shows ``queued``.

Settings come from the environment, server level first, then shared:

    UNIFI_<SERVER>_WRITE_HOLD_SECONDS  / UNIFI_WRITE_HOLD_SECONDS   (default 120)
    UNIFI_<SERVER>_CALL_WAIT_SECONDS   / UNIFI_CALL_WAIT_SECONDS    (default 25)
    UNIFI_<SERVER>_READ_CONCURRENCY    / UNIFI_READ_CONCURRENCY     (default 8)

A value that does not parse or is out of bounds refuses startup (exit code 7),
unlike the preview-token TTL, which is clamped: a lock budget set wrong is a
misconfiguration to fix, not a value to guess at.

The guarantee is per server process.
"""

from __future__ import annotations

import inspect
import logging
import math
import os
from functools import wraps
from typing import Any, Callable, Literal, NoReturn

from unifi_core.jobs import current_job_id
from unifi_core.operation_gate import (
    ControllerBusyError,
    GateSettings,
    OperationGate,
    WriteRequestTimeout,
    WriteTicket,
    signal_admitted,
)

from unifi_mcp_shared.bootstrap import resolve_env
from unifi_mcp_shared.call_arguments import caller_supplied

GateProvider = Callable[[], OperationGate | None]
OperationMode = Literal["write", "read"]

MUTATING_ACTIONS = frozenset({"create", "update", "delete"})

# Startup refusal for a gate setting that does not parse or is out of bounds.
EXIT_GATE_SETTINGS_INVALID = 7

HOLD_KEY = "write_hold_seconds"
WAIT_KEY = "call_wait_seconds"
READ_CAP_KEY = "read_concurrency"

HOLD_BOUNDS = (10.0, 3_600.0)
WAIT_BOUNDS = (1.0, 3_600.0)
READ_CAP_BOUNDS = (1, 64)


def _source(key: str, env_prefix: str) -> str:
    """The variable a resolved value came from, for the error message."""
    server_level = f"UNIFI_{env_prefix.upper()}_{key.upper()}"
    return server_level if os.getenv(server_level) else f"UNIFI_{key.upper()}"


def _refuse(logger: logging.Logger, variable: str, value: str, expected: str) -> NoReturn:
    logger.error("%s=%r is not valid: expected %s. Fix or unset it to start the server.", variable, value, expected)
    raise SystemExit(EXIT_GATE_SETTINGS_INVALID)


def _seconds(key: str, env_prefix: str, default: float, bounds: tuple[float, float], logger: logging.Logger) -> float:
    raw = resolve_env(key, env_prefix=env_prefix, logger=logger)
    if raw is None:
        return default
    expected = f"a number of seconds from {bounds[0]:g} to {bounds[1]:g}"
    try:
        value = float(raw.strip())
    except ValueError:
        _refuse(logger, _source(key, env_prefix), raw, expected)
    if not math.isfinite(value) or not bounds[0] <= value <= bounds[1]:
        _refuse(logger, _source(key, env_prefix), raw, expected)
    return value


def _count(key: str, env_prefix: str, default: int, bounds: tuple[int, int], logger: logging.Logger) -> int:
    raw = resolve_env(key, env_prefix=env_prefix, logger=logger)
    if raw is None:
        return default
    expected = f"a whole number from {bounds[0]} to {bounds[1]}"
    text = raw.strip()
    # ASCII digits only: str.isdigit() also accepts "²", which int() refuses.
    if not (text.isascii() and text.isdigit()):
        _refuse(logger, _source(key, env_prefix), raw, expected)
    value = int(text)
    if not bounds[0] <= value <= bounds[1]:
        _refuse(logger, _source(key, env_prefix), raw, expected)
    return value


def gate_settings_from_env(env_prefix: str, *, logger: logging.Logger) -> GateSettings:
    """Build a server's :class:`GateSettings` from its environment.

    ``env_prefix`` is the server's variable prefix without ``UNIFI_``
    (``"NETWORK"``, ``"PROTECT"``). Each setting is read at the server level,
    then the shared level; an empty variable counts as unset. A value that
    does not parse or is out of bounds refuses startup with a message naming
    the variable.
    """
    env_prefix = env_prefix.upper()
    defaults = GateSettings()
    settings = GateSettings(
        hold_budget_seconds=_seconds(HOLD_KEY, env_prefix, defaults.hold_budget_seconds, HOLD_BOUNDS, logger),
        direct_call_wait_seconds=_seconds(WAIT_KEY, env_prefix, defaults.direct_call_wait_seconds, WAIT_BOUNDS, logger),
        read_cap=_count(READ_CAP_KEY, env_prefix, defaults.read_cap, READ_CAP_BOUNDS, logger),
    )
    if settings != defaults:
        logger.info(
            "Controller operation gate: writes may hold %.0fs, direct calls wait %.0fs, %d concurrent reads",
            settings.hold_budget_seconds,
            settings.direct_call_wait_seconds,
            settings.read_cap,
        )
    return settings


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def make_call_classifier(
    *,
    action: str | None,
    parameters: Any,
    bypass_mode: Callable[[], bool],
    policy_allows: Callable[[], bool] = lambda: True,
) -> Callable[[dict[str, Any]], OperationMode | None]:
    """Build the per-call mode decision for one tool.

    Returns ``"write"``, ``"read"``, or ``None`` when the call takes no gate
    (the policy gate will deny it before anything is sent). ``parameters`` is
    the tool function's signature parameters; ``bypass_mode`` reports whether
    bypass mode would inject ``confirm=True``.
    """
    mutating = isinstance(action, str) and action.lower() in MUTATING_ACTIONS
    confirm = parameters.get("confirm") if parameters is not None else None
    confirm_default = (
        bool(confirm.default) if confirm is not None and confirm.default is not inspect.Parameter.empty else False
    )

    def classify(kwargs: dict[str, Any]) -> OperationMode | None:
        if not mutating:
            return "read"
        if not policy_allows():
            return None
        if confirm is not None:
            # Over MCP the kwargs carry every default, so an omitted confirm
            # must be told apart by what the caller sent.
            if caller_supplied("confirm", kwargs):
                resolved = bool(kwargs.get("confirm"))
            else:
                resolved = True if bypass_mode() else confirm_default
            if not resolved:
                return "read"
        return "write"

    return classify


# ---------------------------------------------------------------------------
# The wrapper
# ---------------------------------------------------------------------------


def gate_tool_call(
    func: Callable[..., Any],
    *,
    tool_name: str,
    gate_provider: GateProvider,
    classify: Callable[[dict[str, Any]], OperationMode | None],
) -> Callable[..., Any]:
    """Wrap one registered tool function so each call enters the gate first.

    With no gate (the provider returns ``None``) or no mode, the call runs
    as before and tells a batch job runner it is admitted. ``CancelledError``
    always propagates, so a queued batch job can be cancelled.
    """

    @wraps(func)
    async def gated_call(*args: Any, **kwargs: Any) -> Any:
        gate = gate_provider()
        mode = classify(kwargs) if gate is not None else None
        if gate is None or mode is None:
            signal_admitted()
            return await func(*args, **kwargs)
        wait_budget = None if current_job_id() is not None else gate.settings.direct_call_wait_seconds
        enter = gate.write if mode == "write" else gate.read
        entered = False
        try:
            async with enter(wait_budget=wait_budget, label=tool_name) as ticket:
                entered = True
                if not isinstance(ticket, WriteTicket):
                    return await func(*args, **kwargs)
                try:
                    result = await func(*args, **kwargs)
                except WriteRequestTimeout as exc:
                    cut_off = ticket.cut_off or exc
                    return {
                        "success": False,
                        "error": f"Failed to run {tool_name}: {cut_off}",
                        "mutation_applied": None if cut_off.request_sent else False,
                    }
                return _with_cut_off_outcome(result, ticket.cut_off, tool_name)
        except ControllerBusyError as exc:
            if entered:
                raise
            refusal: dict[str, Any] = {"success": False, "error": f"Failed to run {tool_name}: {exc}"}
            if mode == "write":
                # Nothing was sent: the confirmed change certainly did not take effect.
                refusal["mutation_applied"] = False
            return refusal

    return gated_call


def _with_cut_off_outcome(result: Any, cut_off: WriteRequestTimeout | None, tool_name: str) -> Any:
    """Add the cut-off's outcome and guidance to a failed write the tool reported without one."""
    if cut_off is None or not isinstance(result, dict) or result.get("success") is not False:
        return result
    if "mutation_applied" in result:
        return result
    guidance = str(cut_off)
    error = result.get("error")
    reported = dict(result)
    if not isinstance(error, str) or not error:
        reported["error"] = f"Failed to run {tool_name}: {guidance}"
    elif guidance not in error:
        reported["error"] = f"{error} {guidance}"
    reported["mutation_applied"] = None if cut_off.request_sent else False
    return reported


def _no_gate() -> None:
    return None


def admission_tool_decorator(tool_decorator: Callable[..., Any], *, tool_name: str) -> Callable[..., Any]:
    """A ``tool(...)`` decorator that only signals batch admission: for a server with no gate."""
    return gating_tool_decorator(
        tool_decorator, tool_name=tool_name, gate_provider=_no_gate, classify=lambda _kwargs: None
    )


def gating_tool_decorator(
    tool_decorator: Callable[..., Any],
    *,
    tool_name: str,
    gate_provider: GateProvider,
    classify: Callable[[dict[str, Any]], OperationMode | None],
) -> Callable[..., Any]:
    """A ``tool(...)`` decorator that gates whatever function it is finally given.

    Put it beneath any decorator that wraps the tool further (the apps'
    connection wait): the function that decorator registers is wrapped here,
    so the gate is entered before anything else runs.
    """

    def tool(*d_args: Any, **d_kwargs: Any) -> Callable[[Callable[..., Any]], Any]:
        register = tool_decorator(*d_args, **d_kwargs)

        def decorator(func: Callable[..., Any]) -> Any:
            return register(gate_tool_call(func, tool_name=tool_name, gate_provider=gate_provider, classify=classify))

        return decorator

    return tool
