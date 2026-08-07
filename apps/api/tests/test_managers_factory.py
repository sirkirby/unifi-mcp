"""Manager factory tests — caching + invalidation."""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from unifi_api.db.crypto import ColumnCipher, derive_key
from unifi_api.db.engine import create_engine
from unifi_api.db.models import Base, Controller
from unifi_api.db.session import get_sessionmaker
from unifi_api.services.managers import (
    ManagerFactory,
    UnknownProduct,
)


class _FakeCM:
    """Stand-in for ConnectionManager — records initialize() invocations."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.init_calls = 0
        self.close_calls = 0

    async def initialize(self) -> bool:
        self.init_calls += 1
        return True

    async def close(self) -> None:
        self.close_calls += 1


def _patch_network_cm(monkeypatch) -> list[_FakeCM]:
    """Replace the network ConnectionManager with a fake; return the
    instance list so callers can assert against constructions."""
    instances: list[_FakeCM] = []

    def _factory(**kwargs):
        cm = _FakeCM(**kwargs)
        instances.append(cm)
        return cm

    from unifi_core.network.managers import connection_manager as cm_module

    monkeypatch.setattr(cm_module, "ConnectionManager", _factory)
    return instances


async def _seed(tmp_path: Path, products: list[str] = ["network"]):
    engine = create_engine(tmp_path / "state.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = get_sessionmaker(engine)
    cipher = ColumnCipher(derive_key("k"))
    cid = str(uuid.uuid4())
    creds = cipher.encrypt(json.dumps({"username": "u", "password": "p", "api_token": None}).encode())
    async with sm() as session:
        session.add(
            Controller(
                id=cid,
                name="N",
                base_url="https://10.0.0.1",
                product_kinds=",".join(products),
                credentials_blob=creds,
                verify_tls=False,
                is_default=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    return engine, sm, cipher, cid


@pytest.mark.asyncio
async def test_factory_caches_connection_manager(tmp_path: Path, monkeypatch) -> None:
    _patch_network_cm(monkeypatch)
    engine, sm, cipher, cid = await _seed(tmp_path)
    factory = ManagerFactory(sm, cipher)
    async with sm() as session:
        cm1 = await factory.get_connection_manager(session, cid, "network")
        cm2 = await factory.get_connection_manager(session, cid, "network")
    assert cm1 is cm2
    await engine.dispose()


@pytest.mark.asyncio
async def test_invalidate_drops_cached_instance(tmp_path: Path, monkeypatch) -> None:
    _patch_network_cm(monkeypatch)
    engine, sm, cipher, cid = await _seed(tmp_path)
    factory = ManagerFactory(sm, cipher)
    async with sm() as session:
        cm1 = await factory.get_connection_manager(session, cid, "network")
    await factory.invalidate_controller(cid)
    async with sm() as session:
        cm2 = await factory.get_connection_manager(session, cid, "network")
    assert cm1 is not cm2
    await engine.dispose()


@pytest.mark.asyncio
async def test_unknown_product_raises(tmp_path: Path, monkeypatch) -> None:
    _patch_network_cm(monkeypatch)
    engine, sm, cipher, cid = await _seed(tmp_path, products=["network"])
    factory = ManagerFactory(sm, cipher)
    async with sm() as session:
        with pytest.raises(UnknownProduct):
            await factory.get_connection_manager(session, cid, "drive")
    await engine.dispose()


@pytest.mark.asyncio
async def test_factory_calls_initialize_on_construction(tmp_path: Path, monkeypatch) -> None:
    """ConnectionManager.initialize() must be awaited after construction.

    Regression guard for the Phase 2 bug where the factory built
    ConnectionManagers but never initialized them, causing downstream
    manager-method calls to hang trying to authenticate.
    """
    instances = _patch_network_cm(monkeypatch)
    engine, sm, cipher, cid = await _seed(tmp_path, products=["network"])
    factory = ManagerFactory(sm, cipher)
    async with sm() as session:
        cm = await factory.get_connection_manager(session, cid, "network")
    assert len(instances) == 1
    assert instances[0] is cm
    assert instances[0].init_calls == 1
    # Subsequent fetches use the cache — initialize must NOT be called again.
    async with sm() as session:
        cm2 = await factory.get_connection_manager(session, cid, "network")
    assert cm2 is cm
    assert instances[0].init_calls == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_network_connection_cache_is_scoped_by_site(tmp_path: Path, monkeypatch) -> None:
    instances = _patch_network_cm(monkeypatch)
    engine, sm, cipher, cid = await _seed(tmp_path)
    factory = ManagerFactory(sm, cipher)

    async with sm() as session:
        site_a = await factory.get_connection_manager(session, cid, "network", site="site-a")
        site_b = await factory.get_connection_manager(session, cid, "network", site="site-b")
        site_a_again = await factory.get_connection_manager(session, cid, "network", site="site-a")

    assert site_a is site_a_again
    assert site_a is not site_b
    assert [cm.kwargs["site"] for cm in instances] == ["site-a", "site-b"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_network_domain_managers_remain_isolated_under_forced_interleaving(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _patch_network_cm(monkeypatch)
    engine, sm, cipher, cid = await _seed(tmp_path)
    factory = ManagerFactory(sm, cipher)
    both_started = asyncio.Event()
    started: list[str] = []

    class _SiteManager:
        def __init__(self, cm: _FakeCM) -> None:
            self.cm = cm

        async def observe_site(self) -> str:
            started.append(self.cm.kwargs["site"])
            if len(started) == 2:
                both_started.set()
            await both_started.wait()
            await asyncio.sleep(0)
            return self.cm.kwargs["site"]

    factory._builder_cache["network"] = {"site_manager": _SiteManager}

    async def _call(site: str) -> str:
        async with sm() as session:
            manager = await factory.get_domain_manager(
                session,
                cid,
                "network",
                "site_manager",
                site=site,
            )
        return await manager.observe_site()

    assert await asyncio.gather(_call("site-a"), _call("site-b")) == ["site-a", "site-b"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_invalidate_closes_every_site_connection(tmp_path: Path, monkeypatch) -> None:
    instances = _patch_network_cm(monkeypatch)
    engine, sm, cipher, cid = await _seed(tmp_path)
    factory = ManagerFactory(sm, cipher)

    async with sm() as session:
        await factory.get_connection_manager(session, cid, "network", site="site-a")
        await factory.get_connection_manager(session, cid, "network", site="site-b")

    await factory.invalidate_controller(cid)

    assert len(instances) == 2
    assert [cm.close_calls for cm in instances] == [1, 1]
    await engine.dispose()
