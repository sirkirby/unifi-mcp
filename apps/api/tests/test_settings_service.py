"""Tests for SettingsService typed accessors over app_settings."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from unifi_api.db.engine import create_engine
from unifi_api.db.models import AppSetting, Base
from unifi_api.db.session import get_sessionmaker
from unifi_api.services.settings import SettingsService, UnknownSettingKey


async def _build_service(tmp_path: Path, seeds: list[tuple[str, str]] | None = None):
    engine = create_engine(tmp_path / "state.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = get_sessionmaker(engine)
    if seeds:
        async with sm() as session:
            for key, value in seeds:
                session.add(AppSetting(key=key, value=value, updated_at=datetime.now(timezone.utc)))
            await session.commit()
    return SettingsService(sm), engine


@pytest.mark.asyncio
async def test_get_int_returns_seeded_default(tmp_path: Path) -> None:
    svc, engine = await _build_service(tmp_path, [("audit.retention.max_age_days", "90")])
    try:
        assert await svc.get_int("audit.retention.max_age_days") == 90
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_bool_returns_true(tmp_path: Path) -> None:
    svc, engine = await _build_service(
        tmp_path,
        [
            ("audit.retention.enabled", "true"),
            ("flag.yes", "yes"),
            ("flag.one", "1"),
            ("flag.off", "false"),
        ],
    )
    try:
        assert await svc.get_bool("audit.retention.enabled") is True
        assert await svc.get_bool("flag.yes") is True
        assert await svc.get_bool("flag.one") is True
        assert await svc.get_bool("flag.off") is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_set_str_then_get_str_round_trip(tmp_path: Path) -> None:
    svc, engine = await _build_service(tmp_path)
    try:
        await svc.set_str("foo", "bar")
        assert await svc.get_str("foo") == "bar"
        # Update path: overwrite the existing row.
        await svc.set_str("foo", "baz")
        assert await svc.get_str("foo") == "baz"
        # Numeric and bool setters round-trip through the same column.
        await svc.set_int("count", 42)
        assert await svc.get_int("count") == 42
        await svc.set_bool("enabled", True)
        assert await svc.get_bool("enabled") is True
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_all_returns_dict(tmp_path: Path) -> None:
    svc, engine = await _build_service(
        tmp_path,
        [
            ("alpha", "1"),
            ("beta", "two"),
        ],
    )
    try:
        result = await svc.get_all()
        assert result == {"alpha": "1", "beta": "two"}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_default_fallback_when_key_missing(tmp_path: Path) -> None:
    svc, engine = await _build_service(tmp_path)
    try:
        assert await svc.get_int("missing.key", default=42) == 42
        assert await svc.get_bool("missing.key", default=False) is False
        assert await svc.get_str("missing.key", default="x") == "x"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_raises_unknown_setting_key_when_missing_and_no_default(
    tmp_path: Path,
) -> None:
    svc, engine = await _build_service(tmp_path)
    try:
        with pytest.raises(UnknownSettingKey):
            await svc.get_str("nope")
        with pytest.raises(UnknownSettingKey):
            await svc.get_int("nope")
        with pytest.raises(UnknownSettingKey):
            await svc.get_bool("nope")
    finally:
        await engine.dispose()
