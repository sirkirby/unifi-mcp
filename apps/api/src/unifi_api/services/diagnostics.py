"""Diagnostics aggregator for /admin/ and GET /v1/diagnostics."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from unifi_api.db.models import ApiKey, AuditLog, Controller, SiteManagerConnection


async def collect_diagnostics(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    db_path: Path | str,
    capability_cache: Any,
    log_path: Path | str | None,
    version: str,
    started_at: datetime,
) -> dict:
    """Build the diagnostics snapshot for dashboard / API consumption."""

    db_path = Path(db_path)
    log_path_obj = Path(log_path) if log_path else None

    # Service section
    now = datetime.now(timezone.utc)
    uptime_seconds = int((now - started_at).total_seconds())
    service = {
        "version": version,
        "uptime_seconds": uptime_seconds,
        "python_version": sys.version.split()[0],
    }

    # Database section
    db_reachable = True
    db_size = 0
    api_keys_count = 0
    controllers_count = 0
    audit_rows_count = 0
    cloud_count = 0
    try:
        db_size = db_path.stat().st_size
    except FileNotFoundError:
        db_size = 0

    try:
        async with sessionmaker() as session:
            cloud_count = (await session.execute(select(func.count(SiteManagerConnection.id)))).scalar_one()
            api_keys_count = (await session.execute(select(func.count(ApiKey.id)))).scalar_one()
            controllers_count = (await session.execute(select(func.count(Controller.id)))).scalar_one()
            audit_rows_count = (await session.execute(select(func.count(AuditLog.id)))).scalar_one()
    except Exception:
        db_reachable = False

    database = {
        "reachable": db_reachable,
        "path": str(db_path),
        "size_bytes": db_size,
    }

    # Capability cache section
    cap_cache = {
        "size": capability_cache.size,
        "hit_rate": capability_cache.hit_rate,
        "ttl_seconds": capability_cache.ttl_seconds,
    }

    # Logs section
    log_size = 0
    if log_path_obj is not None:
        try:
            log_size = log_path_obj.stat().st_size
        except FileNotFoundError:
            log_size = 0
    logs = {
        "file_path": str(log_path_obj) if log_path_obj else None,
        "file_size_bytes": log_size,
    }

    # Counts section
    counts = {
        "api_keys": api_keys_count,
        "controllers": controllers_count,
        "audit_rows": audit_rows_count,
        "sitemanager_connections": cloud_count,
    }

    return {
        "sitemanager": {"configured": bool(cloud_count)},
        "service": service,
        "database": database,
        "capability_cache": cap_cache,
        "logs": logs,
        "counts": counts,
    }
