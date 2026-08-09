"""Manager factory tests — caching + invalidation."""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

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
        self.reconnect_blocked = False
        self.close_gate: "asyncio.Event | None" = None

    async def initialize(self) -> bool:
        self.init_calls += 1
        return True

    async def close(self) -> None:
        if self.close_gate is not None:
            await self.close_gate.wait()
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
async def test_failed_initialization_is_closed_and_not_cached(tmp_path: Path, monkeypatch) -> None:
    instances: list[_FakeCM] = []

    class _FailingCM(_FakeCM):
        last_connection_error = "Unauthorized"

        async def initialize(self) -> bool:
            self.init_calls += 1
            return False

    def factory(**kwargs):
        cm = _FailingCM(**kwargs)
        instances.append(cm)
        return cm

    from unifi_core.network.managers import connection_manager as cm_module

    monkeypatch.setattr(cm_module, "ConnectionManager", factory)
    engine, sm, cipher, cid = await _seed(tmp_path)
    manager_factory = ManagerFactory(sm, cipher)

    for _ in range(2):
        async with sm() as session:
            with pytest.raises(ConnectionError, match="Unauthorized"):
                await manager_factory.get_connection_manager(session, cid, "network")

    assert len(instances) == 2
    assert all(cm.init_calls == 1 and cm.close_calls == 1 for cm in instances)
    assert manager_factory._connection_cache == {}
    await engine.dispose()


@pytest.mark.asyncio
async def test_raising_initialization_is_closed_and_not_cached(tmp_path: Path, monkeypatch) -> None:
    instances: list[_FakeCM] = []

    class _RaisingCM(_FakeCM):
        async def initialize(self) -> bool:
            self.init_calls += 1
            raise RuntimeError("login exploded")

    def factory(**kwargs):
        cm = _RaisingCM(**kwargs)
        instances.append(cm)
        return cm

    from unifi_core.network.managers import connection_manager as cm_module

    monkeypatch.setattr(cm_module, "ConnectionManager", factory)
    engine, sm, cipher, cid = await _seed(tmp_path)
    manager_factory = ManagerFactory(sm, cipher)

    async with sm() as session:
        with pytest.raises(RuntimeError, match="login exploded"):
            await manager_factory.get_connection_manager(session, cid, "network")

    assert len(instances) == 1
    assert instances[0].close_calls == 1
    assert manager_factory._connection_cache == {}
    await engine.dispose()


@pytest.mark.asyncio
async def test_non_boolean_initialization_result_fails_closed(tmp_path: Path, monkeypatch) -> None:
    instances: list[_FakeCM] = []

    class _AmbiguousCM(_FakeCM):
        async def initialize(self) -> bool:
            self.init_calls += 1
            return None  # type: ignore[return-value]

    def factory(**kwargs):
        cm = _AmbiguousCM(**kwargs)
        instances.append(cm)
        return cm

    from unifi_core.network.managers import connection_manager as cm_module

    monkeypatch.setattr(cm_module, "ConnectionManager", factory)
    engine, sm, cipher, cid = await _seed(tmp_path)
    manager_factory = ManagerFactory(sm, cipher)

    async with sm() as session:
        with pytest.raises(ConnectionError, match="Failed to initialize"):
            await manager_factory.get_connection_manager(session, cid, "network")

    assert instances[0].close_calls == 1
    assert manager_factory._connection_cache == {}
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
async def test_probe_preserves_cached_production_connection(tmp_path: Path, monkeypatch) -> None:
    instances = _patch_network_cm(monkeypatch)
    engine, sm, cipher, cid = await _seed(tmp_path)
    factory = ManagerFactory(sm, cipher)
    async with sm() as session:
        cached = await factory.get_connection_manager(session, cid, "network")

    result = await factory.probe_controller(cid)

    assert result["ok"] is True
    assert len(instances) == 2
    assert instances[0] is cached
    assert instances[0].close_calls == 0
    assert instances[1].close_calls == 1
    assert factory._connection_cache[(cid, "network", "default")] is cached
    await factory.invalidate_controller(cid)
    await engine.dispose()


@pytest.mark.asyncio
async def test_probe_heals_auth_blocked_cached_connection(tmp_path: Path, monkeypatch) -> None:
    instances = _patch_network_cm(monkeypatch)
    engine, sm, cipher, cid = await _seed(tmp_path)
    factory = ManagerFactory(sm, cipher)
    async with sm() as session:
        cached = await factory.get_connection_manager(session, cid, "network")
    cached.reconnect_blocked = True

    result = await factory.probe_controller(cid)

    assert result["ok"] is True
    # The blocked cached connection was dropped and closed; the next request
    # reconstructs instead of failing until the auth-circuit cool-down expires.
    assert (cid, "network", "default") not in factory._connection_cache
    assert cached.close_calls == 1
    async with sm() as session:
        fresh = await factory.get_connection_manager(session, cid, "network")
    assert fresh is not cached
    assert len(instances) == 3  # cached + isolated probe + reconstructed
    await factory.invalidate_controller(cid)
    await engine.dispose()


@pytest.mark.asyncio
async def test_invalidate_sweeps_connection_cache_before_awaiting_closes(tmp_path: Path, monkeypatch) -> None:
    """A domain-manager rebuild racing invalidate must not grab a closing connection."""
    _patch_network_cm(monkeypatch)
    engine, sm, cipher, cid = await _seed(tmp_path)
    factory = ManagerFactory(sm, cipher)
    async with sm() as session:
        cm_a = await factory.get_connection_manager(session, cid, "network", site="site-a")
        cm_b = await factory.get_connection_manager(session, cid, "network", site="site-b")
    gate = asyncio.Event()
    cm_a.close_gate = gate
    cm_b.close_gate = gate

    invalidate = asyncio.create_task(factory.invalidate_controller(cid))
    for _ in range(10):
        await asyncio.sleep(0)  # let invalidate suspend inside the first close()

    # Both entries must already be gone even though closes are still pending.
    assert not [k for k in factory._connection_cache if k[0] == cid]

    async def rebuild():
        async with sm() as session:
            return await factory.get_domain_manager(session, cid, "network", "client_manager", site="site-b")

    rebuild_task = asyncio.create_task(rebuild())
    for _ in range(10):
        await asyncio.sleep(0)
    # The rebuild is parked on the per-controller lock, not bound to cm_b.
    assert not rebuild_task.done()

    gate.set()
    await invalidate
    manager = await rebuild_task
    rebuilt_cm = factory._connection_cache[(cid, "network", "site-b")]
    assert rebuilt_cm is not cm_b
    assert manager is factory._domain_cache[(cid, "network", "client_manager", "site-b")]
    await factory.invalidate_controller(cid)
    await engine.dispose()


@pytest.mark.asyncio
async def test_probe_closes_fresh_uncached_connection(tmp_path: Path, monkeypatch) -> None:
    instances = _patch_network_cm(monkeypatch)
    engine, sm, cipher, cid = await _seed(tmp_path)
    factory = ManagerFactory(sm, cipher)

    result = await factory.probe_controller(cid)

    assert result["ok"] is True
    assert len(instances) == 1
    assert instances[0].close_calls == 1
    assert factory._connection_cache == {}
    await engine.dispose()


@pytest.mark.asyncio
async def test_invalidation_waits_for_inflight_construction(tmp_path: Path, monkeypatch) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    instances: list[_FakeCM] = []

    class _SlowCM(_FakeCM):
        async def initialize(self) -> bool:
            self.init_calls += 1
            started.set()
            await release.wait()
            return True

    def cm_factory(**kwargs):
        cm = _SlowCM(**kwargs)
        instances.append(cm)
        return cm

    from unifi_core.network.managers import connection_manager as cm_module

    monkeypatch.setattr(cm_module, "ConnectionManager", cm_factory)
    engine, sm, cipher, cid = await _seed(tmp_path)
    factory = ManagerFactory(sm, cipher)

    async def construct():
        async with sm() as session:
            return await factory.get_connection_manager(session, cid, "network")

    construction = asyncio.create_task(construct())
    await started.wait()
    invalidation = asyncio.create_task(factory.invalidate_controller(cid))
    await asyncio.sleep(0)
    assert not invalidation.done()
    release.set()
    await construction
    await invalidation

    assert factory._connection_cache == {}
    assert instances[0].close_calls == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_invalidation_removes_domain_cache_before_awaiting_close(tmp_path: Path) -> None:
    engine, sm, cipher, cid = await _seed(tmp_path)
    factory = ManagerFactory(sm, cipher)
    close_started = asyncio.Event()
    release_close = asyncio.Event()

    class _SlowCloseCM:
        async def close(self) -> None:
            close_started.set()
            await release_close.wait()

    domain_key = (cid, "network", "network_manager", "default")
    factory._domain_cache[domain_key] = object()
    factory._connection_cache[(cid, "network", "default")] = _SlowCloseCM()

    invalidation = asyncio.create_task(factory.invalidate_controller(cid))
    await close_started.wait()

    assert domain_key not in factory._domain_cache

    release_close.set()
    await invalidation
    await engine.dispose()


@pytest.mark.asyncio
async def test_invalidate_supports_cleanup_only_connection_manager(tmp_path: Path) -> None:
    engine, sm, cipher, cid = await _seed(tmp_path)
    factory = ManagerFactory(sm, cipher)
    cleanup = AsyncMock()
    factory._connection_cache[(cid, "network", "default")] = type("CleanupOnlyCM", (), {"cleanup": cleanup})()

    await factory.invalidate_controller(cid)

    cleanup.assert_awaited_once()
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
