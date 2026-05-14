"""Diagnostics aggregator tests — Phase 5B PR1 Task 6."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_collect_diagnostics_shape_and_counts(tmp_path: Path) -> None:
    from datetime import datetime, timedelta, timezone

    from unifi_api.db.engine import create_engine
    from unifi_api.db.models import ApiKey, AuditLog, Base, Controller
    from unifi_api.db.session import get_sessionmaker
    from unifi_api.services.capability_cache import CapabilityCache
    from unifi_api.services.diagnostics import collect_diagnostics

    db_path = tmp_path / "state.db"
    engine = create_engine(db_path)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = get_sessionmaker(engine)

    # Seed: 2 keys, 1 controller, 3 audit rows
    async with sm() as session:
        for i in range(2):
            session.add(
                ApiKey(
                    id=f"k{i}",
                    prefix=f"p{i}",
                    hash="h",
                    scopes="read",
                    name=f"n{i}",
                    created_at=datetime.now(timezone.utc),
                )
            )
        session.add(
            Controller(
                id="c1",
                name="c",
                base_url="http://c",
                product_kinds="network",
                credentials_blob=b"x",
                verify_tls=True,
                is_default=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        for _ in range(3):
            session.add(
                AuditLog(
                    ts=datetime.now(timezone.utc),
                    key_id_prefix="p",
                    controller=None,
                    target="t",
                    outcome="ok",
                )
            )
        await session.commit()

    cache = CapabilityCache(ttl_seconds=300)
    cache.put("c1", {"x": 1})
    cache.get("c1")  # hit
    cache.get("missing")  # miss

    log_file = tmp_path / "app.log"
    log_file.write_bytes(b"some log content\n")

    started = datetime.now(timezone.utc) - timedelta(seconds=42)

    snap = await collect_diagnostics(
        sessionmaker=sm,
        db_path=db_path,
        capability_cache=cache,
        log_path=log_file,
        version="0.1.0",
        started_at=started,
    )

    # Shape assertions
    assert set(snap.keys()) == {"service", "database", "capability_cache", "logs", "counts"}

    # Service
    assert snap["service"]["version"] == "0.1.0"
    assert snap["service"]["uptime_seconds"] >= 42
    assert "." in snap["service"]["python_version"]

    # Database
    assert snap["database"]["reachable"] is True
    assert snap["database"]["path"] == str(db_path)
    assert snap["database"]["size_bytes"] > 0

    # Capability cache
    assert snap["capability_cache"]["size"] == 1
    assert snap["capability_cache"]["ttl_seconds"] == 300
    assert 0.0 <= snap["capability_cache"]["hit_rate"] <= 1.0
    assert snap["capability_cache"]["hit_rate"] == 0.5  # 1 hit, 1 miss

    # Logs
    assert snap["logs"]["file_path"] == str(log_file)
    assert snap["logs"]["file_size_bytes"] > 0

    # Counts
    assert snap["counts"]["api_keys"] == 2
    assert snap["counts"]["controllers"] == 1
    assert snap["counts"]["audit_rows"] == 3

    await engine.dispose()
