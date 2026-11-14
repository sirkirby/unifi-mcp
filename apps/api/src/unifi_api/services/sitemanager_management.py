"""Transactional connection management shared by REST, admin and CLI."""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from unifi_api.services.audit import write_audit
from unifi_api.services.sitemanager_connections import (
    create_connection,
    delete_connection,
    get_connection,
    metadata,
    update_connection,
)
from unifi_api.services.sitemanager_errors import map_error

_log = logging.getLogger("unifi-api.sitemanager")


@dataclass
class ManagementResult:
    data: dict | None
    status: int = 200


async def manage_connection(sessionmaker, cipher, factory, operation, *, payload=None, actor):
    """Operation must be one of the fixed labels supplied by the adapters."""
    labels = {
        "create": "create Site Manager connection",
        "get": "get Site Manager connection",
        "update": "update Site Manager connection",
        "delete": "delete Site Manager connection",
        "probe": "probe Site Manager connection",
    }
    label = labels[operation]
    connection_id = None
    started = time.monotonic()
    try:
        async with sessionmaker() as session:
            if operation == "create":
                row = await create_connection(session, cipher, payload)
            else:
                row = await get_connection(session)
                connection_id = row.id
                if operation == "update":
                    row = await update_connection(session, cipher, payload)
                elif operation == "delete":
                    await delete_connection(session)
            connection_id = row.id
            data = metadata(row)
            if operation == "probe":
                # Uses its own session and transport. No account data leaves this scope.
                async with factory.isolated() as bundle:
                    await bundle.inventory_manager.list_hosts(page_size=1)
                data = {
                    "ok": True,
                    "latency_ms": round((time.monotonic() - started) * 1000),
                    "error_kind": None,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                }
            if operation != "get":
                await write_audit(
                    session,
                    key_id_prefix=actor,
                    controller=None,
                    sitemanager_connection=connection_id,
                    target=f"sitemanager.connection.{operation}",
                    outcome="success",
                )
                await session.commit()
    except Exception as exc:
        error = map_error(exc, label, management=operation != "probe")
    else:
        # The mutation and success audit are durable; cleanup cannot undo them.
        if operation in ("update", "delete"):
            try:
                await factory.invalidate()
            except Exception as exc:
                _log.warning("Site Manager %s cleanup failed (%s)", operation, type(exc).__name__)
        return ManagementResult(None if operation == "delete" else data, 201 if operation == "create" else 200)
    # Never carry the original exception or its traceback into API errors.
    try:
        if operation != "get":
            async with sessionmaker() as session:
                await write_audit(
                    session,
                    key_id_prefix=actor,
                    controller=None,
                    sitemanager_connection=connection_id,
                    target=f"sitemanager.connection.{operation}",
                    outcome="error",
                    error_kind=error.kind,
                )
                await session.commit()
    except Exception as exc:
        error = map_error(exc, "record Site Manager connection audit")
    if operation == "probe":
        return ManagementResult(
            {
                "ok": False,
                "latency_ms": round((time.monotonic() - started) * 1000),
                "error_kind": error.kind,
                "message": error.message,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            },
            error.status,
        )
    raise error from None
