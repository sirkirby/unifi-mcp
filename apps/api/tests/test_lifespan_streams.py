"""Lifespan eager-listening tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.server import create_app
from unifi_api.services.streams import SubscriberPool


def _cfg(tmp_path):
    return ApiConfig(
        http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
        logging=LoggingConfig(level="WARNING"),
        db=DbConfig(path=str(tmp_path / "state.db")),
    )


def test_create_app_initializes_subscriber_pool(tmp_path, monkeypatch) -> None:
    """SubscriberPool is wired on app.state at create_app time (already from Task 13)."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app = create_app(_cfg(tmp_path))
    assert isinstance(app.state.subscriber_pool, SubscriberPool)


@pytest.mark.asyncio
async def test_lifespan_eager_starts_listening_per_controller(tmp_path, monkeypatch) -> None:
    """Lifespan warms event managers; the factory owns listener startup."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")

    import uuid
    from datetime import datetime, timezone

    from unifi_api.db.crypto import ColumnCipher, derive_key
    from unifi_api.db.models import Base, Controller

    app = create_app(_cfg(tmp_path))
    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = app.state.sessionmaker
    cipher = ColumnCipher(derive_key("k"))
    cid = str(uuid.uuid4())
    async with sm() as session:
        session.add(
            Controller(
                id=cid,
                name="N",
                base_url="https://x",
                product_kinds="network,protect",
                credentials_blob=cipher.encrypt(b'{"username":"u","password":"p","api_token":null}'),
                verify_tls=False,
                is_default=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    # Record warm-up requests without starting a second, unowned listener.
    started: list[tuple[str, str]] = []

    async def fake_get_domain_manager(session, ctrl_id, product, attr):
        started.append((ctrl_id, product))
        return MagicMock()

    app.state.manager_factory.get_domain_manager = AsyncMock(side_effect=fake_get_domain_manager)

    # Trigger lifespan startup
    async with app.router.lifespan_context(app):
        pass

    assert (cid, "network") in started
    assert (cid, "protect") in started


@pytest.mark.asyncio
async def test_lifespan_continues_when_one_start_listening_raises(tmp_path, monkeypatch, caplog) -> None:
    """A failing start_listening for one controller logs warning, doesn't block startup."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")

    import uuid
    from datetime import datetime, timezone

    from unifi_api.db.crypto import ColumnCipher, derive_key
    from unifi_api.db.models import Base, Controller

    app = create_app(_cfg(tmp_path))
    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = app.state.sessionmaker
    cipher = ColumnCipher(derive_key("k"))
    cid = str(uuid.uuid4())
    async with sm() as session:
        session.add(
            Controller(
                id=cid,
                name="N",
                base_url="https://x",
                product_kinds="network",
                credentials_blob=cipher.encrypt(b'{"username":"u","password":"p","api_token":null}'),
                verify_tls=False,
                is_default=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    async def boom_get_domain_manager(*a, **kw):
        raise RuntimeError("simulated init failure")

    app.state.manager_factory.get_domain_manager = AsyncMock(side_effect=boom_get_domain_manager)

    # Lifespan should still complete startup despite the per-controller failure
    async with app.router.lifespan_context(app):
        pass
    # No assertion needed beyond that the context manager completed without raising


@pytest.mark.asyncio
async def test_cloud_configuration_starts_no_request_or_event_listener_and_closes_factory(tmp_path, monkeypatch):
    from unifi_api.db.models import Base
    from unifi_api.services.sitemanager_connections import create_connection
    from unifi_core.sitemanager.managers.connection_manager import SiteManagerConnectionManager
    from unifi_core.sitemanager.models.connections import SiteManagerConnectionCreate

    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    construct = MagicMock(side_effect=AssertionError("Cloud construction at startup"))
    from unifi_api.services import sitemanager_managers

    monkeypatch.setattr(sitemanager_managers, "SiteManagerConnectionManager", construct)
    request = AsyncMock(side_effect=AssertionError("Cloud request at startup"))
    monkeypatch.setattr(SiteManagerConnectionManager, "get", request)
    app = create_app(_cfg(tmp_path))
    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with app.state.sessionmaker() as session:
        await create_connection(
            session,
            app.state.cipher,
            SiteManagerConnectionCreate(name="Account", site_manager_api_key="synthetic-cloud-key"),
        )
        await session.commit()
    console_factory = app.state.manager_factory
    console_factory.get_domain_manager = AsyncMock(side_effect=AssertionError("Cloud treated as console"))
    close = AsyncMock(wraps=app.state.sitemanager_factory.close)
    app.state.sitemanager_factory.close = close
    async with app.router.lifespan_context(app):
        construct.assert_not_called()
        request.assert_not_awaited()
        console_factory.get_domain_manager.assert_not_awaited()
    close.assert_awaited_once()
    assert app.state.sitemanager_factory._closed


@pytest.mark.asyncio
async def test_cloud_factory_closes_on_exceptional_lifespan_exit(tmp_path, monkeypatch):
    from unifi_api.db.models import Base

    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app = create_app(_cfg(tmp_path))
    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    close = AsyncMock(wraps=app.state.sitemanager_factory.close)
    app.state.sitemanager_factory.close = close
    with pytest.raises(RuntimeError, match="synthetic-stop"):
        async with app.router.lifespan_context(app):
            raise RuntimeError("synthetic-stop")
    close.assert_awaited_once()
