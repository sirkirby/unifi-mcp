"""The shared write layer for InnerSpace layout writes.

Every ``apply_*`` method of a write manager runs :func:`ensure_writable`,
builds its request from a fresh :func:`read_internal_project`, and sends it
once with :func:`send_write`, which then reads back to decide the outcome:

* :func:`ensure_writable` reads ``/api/system`` uncached, refuses unless
  InnerSpace is installed and running, then reads the floor plans for their
  geometry. Previews run the same check.
* Confirmed writes run one at a time through the operation gate, which the
  servers hold around the whole ``apply_*`` call; this layer adds no lock of
  its own.
* The write goes out with ``replay=False``. A refused session is renewed and
  the write is not sent again: the result is "not applied" with no read-back.
  After any other outcome (an answer of any status, a timeout, a dropped
  connection) the read-back decides, with the console's answer: every change
  in place is applied; no change is "not applied" only when the console
  refused the write (a 4xx, or UniFi OS refusing it a second time); anything
  else is unknown, because an accepted or lost write may still appear and a
  5xx or 429 says nothing about InnerSpace.
* New ids come from :func:`write_ids`: the same call (tool and arguments, the
  plan id included) always gives the same ids, so a retried confirm after a
  lost answer finds its objects already there and sends nothing. The console's
  duplicate-id 500, which changes nothing, stays the backstop.

Remaining race: the operation gate serialises writes in this process only. A
second server process or the browser editor writing to the same project
between the fresh read and the write is overwritten silently: an update sends
each object whole as it was read, and a plan or project setting sends the
value it sets, so the other change is lost and neither side reports it.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Awaitable, Callable, Iterable, Mapping

from unifi_core.exceptions import (
    UniFiError,
    UniFiMalformedResponseError,
    UniFiOperationError,
    UniFiRateLimitError,
)
from unifi_core.innerspace.managers._reads import read_floor_plan_rows
from unifi_core.innerspace.managers.connection_manager import (
    INTERNAL_PROJECT_PATH,
    PLAN_ORDER_PATH,
    PLAN_PATH_PREFIX,
    SYSTEM_PATH,
    InnerSpaceConnectionManager,
    InnerSpaceHttpError,
    InnerSpaceUnavailableError,
    InnerSpaceWriteForbidden,
    InnerSpaceWriteNotSent,
    InnerSpaceWriteOutcomeUnknown,
    _log_route,
)
from unifi_core.innerspace.models.project import _data
from unifi_core.innerspace.models.status import app_status_from_api
from unifi_core.request_paths import InvalidRequestPathError, object_id
from unifi_core.write_verification import (
    WriteVerificationResult,
    failed_write,
    settle_readback,
)

logger = logging.getLogger(__name__)

# Fixed namespace for write ids; changing it changes every id a retried confirm would reuse.
WRITE_ID_NAMESPACE = uuid.UUID("5d1f6c64-7a1b-4b5e-9f3c-2a8e4d6b7c90")

# A read-back state per change: True when the requested state is in place, False when the
# prior state is, None for anything else.
ReadBack = Callable[[], Awaitable[Mapping[str, "bool | None"]]]


# Errors after which the write may have been applied: the read-back decides. Any other error
# from the request (unavailable, refused path, permission) was raised before anything was sent.
_SENT_ERRORS = (
    InnerSpaceWriteOutcomeUnknown,
    InnerSpaceWriteForbidden,
    InnerSpaceHttpError,
    UniFiRateLimitError,
    UniFiMalformedResponseError,
)


class InnerSpaceWriteRefusedError(UniFiOperationError):
    """A write refused before anything was sent, because the request cannot be built safely from the stored state."""


_REORDER_SEGMENT = PLAN_ORDER_PATH.rpartition("/")[2].casefold()


def plan_path(plan_id: str) -> str:
    """The internal route of one plan; the id must be one path segment, and not the reorder route's in any case."""
    segment = object_id(plan_id, "plan")
    if segment.casefold() == _REORDER_SEGMENT:
        raise InvalidRequestPathError("plan id is not valid")
    return f"{PLAN_PATH_PREFIX}/{segment}"


async def ensure_writable(cm: InnerSpaceConnectionManager, *, operation: str) -> list[dict[str, Any]]:
    """Refuse unless InnerSpace is installed and running; returns the floor-plan rows (each plan's geometry).

    ``/api/system`` is read uncached. Previews and ``apply_*`` run the same check.
    """
    status = app_status_from_api(await cm.request("GET", SYSTEM_PATH, operation=operation))
    if not status.installed:
        raise InnerSpaceUnavailableError(f"{operation}: InnerSpace is not installed on this console")
    if not status.running:
        raise InnerSpaceUnavailableError(f"{operation}: InnerSpace is not running on this console")
    return await read_floor_plan_rows(cm, operation=operation)


async def read_internal_project(cm: InnerSpaceConnectionManager, *, operation: str) -> dict[str, Any]:
    """The stored project (no ``mode``): ``project``, ``plans``, ``shapes`` and the type lists."""
    return _data(await cm.request("GET", INTERNAL_PROJECT_PATH, operation=operation))


def write_ids(tool: str, args: Mapping[str, Any], count: int) -> list[str]:
    """``count`` ids for new objects, fixed by the tool, its canonical arguments and the index in the batch.

    The arguments carry the plan id. The stored state is not part of the seed, so
    a retry after a lost answer derives the same ids as the call that landed.
    """
    seed = json.dumps({"tool": tool, "args": args}, sort_keys=True, separators=(",", ":"))
    return [str(uuid.uuid5(WRITE_ID_NAMESPACE, f"{seed}#{index}")) for index in range(count)]


def _answer(error: UniFiError | None) -> str:
    """What the console said, in fixed words: a status and an ``errors.*`` code at most."""
    if error is None:
        return "the console accepted the request"
    if isinstance(error, InnerSpaceWriteForbidden):
        return "the console refused the write (HTTP 403): the console account cannot make this change"
    if isinstance(error, InnerSpaceHttpError):
        return f"the console answered HTTP {error.status}" + (f" ({error.code})" if error.code else "")
    if isinstance(error, UniFiRateLimitError):
        return "the console answered HTTP 429"
    if isinstance(error, UniFiMalformedResponseError):
        return "the console's answer was unreadable"
    return "the console did not answer"


def _classify(error: UniFiError | None) -> str:
    """What a sent write's answer says about it.

    ``accepted``: a 2xx, readable or not. ``lost``: no answer. Both may still show a moment later,
    so the read-back settles. ``refused``: a 4xx from InnerSpace (not 429) or UniFi OS refusing the
    write on the session it had just issued; an unchanged read-back then means not applied.
    ``unclear``: anything else (5xx, 429, a redirect), which says nothing about InnerSpace.
    """
    if error is None or isinstance(error, UniFiMalformedResponseError):
        return "accepted"
    if isinstance(error, InnerSpaceWriteOutcomeUnknown):
        return "lost"
    if isinstance(error, InnerSpaceWriteForbidden) or (
        isinstance(error, InnerSpaceHttpError) and 400 <= error.status < 500
    ):
        return "refused"
    return "unclear"


async def send_write(
    cm: InnerSpaceConnectionManager,
    method: str,
    path: str,
    body: Any,
    *,
    operation: str,
    read_back: ReadBack,
    metadata: Mapping[str, Any] | None = None,
    warnings: Iterable[str] = (),
) -> WriteVerificationResult:
    """Send one write, never twice, then let the read-back decide whether it was applied.

    ``read_back`` re-reads the console and returns, per change, ``True`` when the
    requested state is in place, ``False`` when the prior state is, and ``None``
    otherwise. ``metadata`` (created ids, effect counts) and ``warnings`` are
    carried into the result; ``missing`` lists the changes not in place (``None``
    when the read-back failed or had no changes in it). A read-back with no
    changes in it proves nothing, so the outcome is unknown. The reply body is never logged or returned.

    When the console accepted the write (readable answer or not), or its answer was lost, a read-back
    that does not show every change yet is repeated a few times (``settle_readback``, within the write's
    hold budget, sleeping with ``cm.readback_sleep``): a read made just after a write can show the old
    state. Any other answer gets one read-back.

    Only a definite refusal (a 4xx from the console, or UniFi OS refusing the write) with an unchanged
    read-back is "not applied". An accepted or lost write that still reads unchanged once the waits are
    over (or cut short) may yet appear, and a 5xx or 429 says nothing about InnerSpace: those are unknown.
    """
    meta: dict[str, Any] = dict(metadata or {})
    meta["warnings"] = list(warnings)
    route = _log_route(path)
    error: UniFiError | None = None
    try:
        await cm.request(method, path, operation=operation, json=body, replay=False)
    except InnerSpaceWriteNotSent:
        logger.info("[innerspace-writes] %s: %s %s not sent (session refused)", operation, method, route)
        return failed_write(
            f"{operation}: the console refused the session, so the change was not sent. The session was renewed "
            "and nothing was changed; the same request can be sent again.",
            operation=operation,
            mutation_applied=False,
            metadata=meta,
        )
    except _SENT_ERRORS as exc:
        error = exc
    answer = _answer(error)
    kind = _classify(error)

    async def read() -> dict[str, bool | None]:
        return dict(await read_back())

    def complete(states: Mapping[str, bool | None]) -> bool:
        return bool(states) and all(state is True for state in states.values())

    try:
        if kind in ("accepted", "lost"):
            states = (await settle_readback(read, complete, sleep=cm.readback_sleep)).value
        else:
            states = await read()
    except Exception as exc:
        # The write went out: any read-back failure, UniFi or not, leaves the outcome unknown.
        logger.warning("[innerspace-writes] %s: read-back failed (%s)", operation, type(exc).__name__)
        meta["missing"] = None
        return failed_write(
            f"{operation}: {answer}, and the read-back failed, so whether the change was applied is unknown. "
            "Read before retrying.",
            operation=operation,
            mutation_applied=None,
            metadata=meta,
        )
    missing = sorted(key for key, state in states.items() if state is not True)
    meta["missing"] = missing if states else None
    unchanged = bool(states) and all(state is False for state in states.values())
    if states and not missing:
        outcome = "applied"
        if error is not None:
            lost = "the console's answer was lost" if isinstance(error, InnerSpaceWriteOutcomeUnknown) else answer
            meta["warnings"].append(f"The read-back shows every change in place: applied, although {lost}")
        result = WriteVerificationResult(success=True, mutation_applied=True, operation=operation, metadata=meta)
    elif unchanged and kind == "refused":
        outcome = "not applied"
        result = failed_write(
            f"{operation}: {answer}, and the read-back shows no change; nothing was applied.",
            operation=operation,
            mutation_applied=False,
            metadata=meta,
        )
    else:
        outcome = "unknown"
        if unchanged:
            shown = "no change yet, and the change may still appear"
        elif states:
            shown = (
                "only part of the change or a state that is neither the old nor the requested one; an edit made "
                "at the same time can cause this"
            )
        else:
            shown = "nothing to compare"
        result = failed_write(
            f"{operation}: {answer}, and the read-back shows {shown}. Read before retrying.",
            operation=operation,
            mutation_applied=None,
            metadata=meta,
        )
    logger.info("[innerspace-writes] %s: %s %s %s", operation, method, route, outcome)
    return result
