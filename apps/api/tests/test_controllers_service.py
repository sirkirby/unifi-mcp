"""Controllers service CRUD tests (no capability probe yet)."""

import json
from pathlib import Path

import pytest
from unifi_api.db.crypto import ColumnCipher, derive_key
from unifi_api.db.engine import create_engine
from unifi_api.db.models import Base
from unifi_api.db.session import get_sessionmaker
from unifi_api.services.controllers import (
    ControllerNotFound,
    CreateControllerPayload,
    create_controller,
    delete_controller,
    get_controller,
    list_controllers,
    update_controller,
)


async def _setup(tmp_path: Path):
    engine = create_engine(tmp_path / "state.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = get_sessionmaker(engine)
    cipher = ColumnCipher(derive_key("test-key"))
    return engine, sm, cipher


@pytest.mark.asyncio
async def test_create_round_trip(tmp_path: Path) -> None:
    engine, sm, cipher = await _setup(tmp_path)
    payload = CreateControllerPayload(
        name="Home",
        base_url="https://10.0.0.1",
        username="root",
        password="hunter2",
        api_token=None,
        product_kinds=["network"],
        verify_tls=False,
        is_default=True,
    )
    async with sm() as session:
        row = await create_controller(session, cipher, payload)
        assert row.name == "Home" and row.is_default is True
        await session.commit()
    async with sm() as session:
        listed = await list_controllers(session)
        assert len(listed) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_decrypts(tmp_path: Path) -> None:
    engine, sm, cipher = await _setup(tmp_path)
    payload = CreateControllerPayload(
        name="N",
        base_url="https://x",
        username="u",
        password="p",
        api_token=None,
        product_kinds=["network"],
        verify_tls=True,
        is_default=True,
    )
    async with sm() as session:
        row = await create_controller(session, cipher, payload)
        await session.commit()
        cid = row.id
    async with sm() as session:
        row = await get_controller(session, cid)
        creds = json.loads(cipher.decrypt(row.credentials_blob))
        assert creds["username"] == "u" and creds["password"] == "p"
    await engine.dispose()


@pytest.mark.asyncio
async def test_update_partial(tmp_path: Path) -> None:
    engine, sm, cipher = await _setup(tmp_path)
    payload = CreateControllerPayload(
        name="N",
        base_url="https://x",
        username="u",
        password="p",
        api_token=None,
        product_kinds=["network"],
        verify_tls=True,
        is_default=False,
    )
    async with sm() as session:
        row = await create_controller(session, cipher, payload)
        await session.commit()
        cid = row.id
    async with sm() as session:
        await update_controller(session, cipher, cid, name="Renamed")
        await session.commit()
    async with sm() as session:
        row = await get_controller(session, cid)
        assert row.name == "Renamed"
    await engine.dispose()


@pytest.mark.asyncio
async def test_default_uniqueness(tmp_path: Path) -> None:
    engine, sm, cipher = await _setup(tmp_path)
    p1 = CreateControllerPayload(
        name="A",
        base_url="https://1",
        username="u",
        password="p",
        api_token=None,
        product_kinds=["network"],
        verify_tls=True,
        is_default=True,
    )
    p2 = CreateControllerPayload(
        name="B",
        base_url="https://2",
        username="u",
        password="p",
        api_token=None,
        product_kinds=["network"],
        verify_tls=True,
        is_default=True,
    )
    async with sm() as session:
        await create_controller(session, cipher, p1)
        await create_controller(session, cipher, p2)
        await session.commit()
    async with sm() as session:
        rows = await list_controllers(session)
        defaults = [r for r in rows if r.is_default]
        assert len(defaults) == 1 and defaults[0].name == "B"  # last write wins
    await engine.dispose()


@pytest.mark.asyncio
async def test_delete_then_404(tmp_path: Path) -> None:
    engine, sm, cipher = await _setup(tmp_path)
    payload = CreateControllerPayload(
        name="N",
        base_url="https://x",
        username="u",
        password="p",
        api_token=None,
        product_kinds=["network"],
        verify_tls=True,
        is_default=False,
    )
    async with sm() as session:
        row = await create_controller(session, cipher, payload)
        await session.commit()
        cid = row.id
    async with sm() as session:
        await delete_controller(session, cid)
        await session.commit()
    async with sm() as session:
        with pytest.raises(ControllerNotFound):
            await get_controller(session, cid)
    await engine.dispose()
