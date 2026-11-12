"""Generation leases survive rotation/deletion and observe changes from other processes."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from unifi_api.services import sitemanager_managers as module
from unifi_api.services.sitemanager_connections import (
    SiteManagerConfigurationError,
    SiteManagerConnectionNotFound,
    delete_connection,
    update_connection,
)
from unifi_core.sitemanager.models.connections import SiteManagerConnectionPatch

from tests.test_sitemanager_connections import KEY, seed
from tests.test_sitemanager_connections import store as store


@pytest.fixture
def connections(monkeypatch):
    built = []

    class Connection:
        def __init__(self, *, api_key):
            self.key = api_key
            self.close = AsyncMock()
            self.initialize = AsyncMock(return_value=True)
            built.append(self)

    monkeypatch.setattr(module, "SiteManagerConnectionManager", Connection)
    return built


@pytest.mark.asyncio
async def test_one_connection_for_concurrent_first_reads(store, connections, cloud_secrecy_guard):
    await seed(store)
    factory = module.SiteManagerFactory(*store)
    ready = asyncio.Event()
    acquired = []

    async def read():
        async with factory.acquire() as bundle:
            acquired.append(bundle)
            if len(acquired) == 12:
                ready.set()
            await ready.wait()

    await asyncio.gather(*(read() for _ in range(12)))
    assert len(connections) == 1
    assert len(acquired) == 12
    assert all(bundle is acquired[0] for bundle in acquired)
    assert connections[0].key == KEY
    assert acquired[0].inventory_manager._connection is connections[0]
    await factory.close()
    connections[0].close.assert_awaited_once()


@pytest.mark.asyncio
async def test_rotation_and_two_factories_observe_revision(store, connections, cloud_secrecy_guard):
    await seed(store)
    sm, cipher = store
    first, second = module.SiteManagerFactory(*store), module.SiteManagerFactory(*store)
    async with first.acquire() as held:
        async with second.acquire() as other:
            assert other.revision == 1
        async with sm() as session:
            await update_connection(
                session, cipher, SiteManagerConnectionPatch(site_manager_api_key="rotated-synthetic")
            )
            await session.commit()
        for factory in (first, second):
            async with factory.acquire() as fresh:
                assert fresh.revision == 2
                assert fresh.connection.key == "rotated-synthetic"
                for attr in ("inventory_manager", "isp_metrics_manager", "sdwan_manager"):
                    assert getattr(fresh, attr) is not getattr(held, attr)
        held.connection.close.assert_not_awaited()
    held.connection.close.assert_awaited_once()
    await first.close()
    await second.close()
    assert len(connections) == 4
    for connection in connections:
        connection.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_does_not_close_inflight_lease_and_recreate_changes_identity(
    store, connections, cloud_secrecy_guard
):
    old_row = await seed(store)
    sm, _ = store
    factory = module.SiteManagerFactory(*store)
    async with factory.acquire() as old:
        async with sm() as session:
            await delete_connection(session)
            await session.commit()
        with pytest.raises(SiteManagerConnectionNotFound):
            async with factory.acquire():
                pytest.fail("Deleted connection acquired")
        old.connection.close.assert_not_awaited()
        replacement = await seed(store)
        async with factory.acquire() as new:
            assert new.connection_id == replacement.id != old_row.id
    old.connection.close.assert_awaited_once()
    await factory.close()


@pytest.mark.asyncio
async def test_cancellation_releases_retired_lease_and_shutdown_waits(store, connections, cloud_secrecy_guard):
    await seed(store)
    factory = module.SiteManagerFactory(*store)
    entered = asyncio.Event()

    async def read():
        async with factory.acquire():
            entered.set()
            await asyncio.Event().wait()

    reader = asyncio.create_task(read())
    await entered.wait()
    closing = asyncio.create_task(factory.close())
    await asyncio.sleep(0)
    assert not closing.done()
    reader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await reader
    await asyncio.wait_for(closing, 1)
    assert len(connections) == 1
    connections[0].close.assert_awaited_once()
    with pytest.raises(SiteManagerConfigurationError):
        async with factory.acquire():
            pytest.fail("Closed factory acquired")


@pytest.mark.asyncio
async def test_no_cloud_env_or_console_fallback(store, monkeypatch, tmp_path, cloud_secrecy_guard):
    from unifi_api.services.controllers import CreateControllerPayload, create_controller
    from unifi_core.sitemanager.managers.connection_manager import SiteManagerConnectionManager

    sm, cipher = store
    alternatives = {
        "UNIFI_API_KEY": "synthetic-shared-env-key",
        "UNIFI_NETWORK_API_KEY": "synthetic-network-env-key",
        "UNIFI_PROTECT_API_KEY": "synthetic-protect-env-key",
        "UNIFI_ACCESS_API_KEY": "synthetic-access-env-key",
        "UNIFI_SITEMANAGER_API_KEY": "synthetic-cloud-env-key",
        "SITEMANAGER_API_KEY": "synthetic-unprefixed-cloud-env-key",
    }
    config = tmp_path / "alternate-config.yaml"
    config.write_text("api_key: synthetic-file-key\nsitemanager:\n  api_key: synthetic-nested-file-key\n")
    monkeypatch.setenv("CONFIG_PATH", str(config))
    for var, value in alternatives.items():
        monkeypatch.setenv(var, value)
    async with sm() as session:
        await create_controller(
            session,
            cipher,
            CreateControllerPayload(
                name="Console",
                base_url="https://192.0.2.1",
                product_kinds=["network"],
                username="synthetic-console-user",
                password="synthetic-console-password",
                api_token="synthetic-console-api-token",
                verify_tls=True,
                is_default=True,
            ),
        )
        await session.commit()

    constructed = []

    def tracked_connection(*args, **kwargs):
        # Keep the real Core constructor so any fallback there stays observable.
        connection = SiteManagerConnectionManager(*args, **kwargs)
        constructed.append(connection)
        return connection

    monkeypatch.setattr(module, "SiteManagerConnectionManager", tracked_connection)
    factory = module.SiteManagerFactory(*store)
    with pytest.raises(SiteManagerConnectionNotFound):
        async with factory.acquire():
            pytest.fail("Environment, file or console fallback used")
    assert constructed == []
    row = await seed(store)
    async with sm() as session:
        from unifi_api.db.models import SiteManagerConnection

        stored = await session.get(SiteManagerConnection, row.id)
        stored.api_key_blob = b"broken-ciphertext"
        await session.commit()
    with pytest.raises(SiteManagerConfigurationError) as error:
        async with factory.acquire():
            pytest.fail("Broken ciphertext used an alternate key")
    assert error.value.__suppress_context__
    assert constructed == []
    # A positive control uses the actual constructor, with only the stored key.
    from unifi_api.services.sitemanager_connections import associated_data

    async with sm() as session:
        stored = await session.get(SiteManagerConnection, row.id)
        stored.api_key_blob = cipher.encrypt(KEY.encode(), associated_data=associated_data(row.id))
        await session.commit()
    async with factory.acquire() as bundle:
        assert len(constructed) == 1
        assert bundle.connection._api_key == KEY
        assert bundle.connection._session is None
        assert bundle.connection._api_key not in set(alternatives.values()) | {
            "synthetic-file-key",
            "synthetic-nested-file-key",
            "synthetic-console-api-token",
            "synthetic-console-password",
            "synthetic-console-user",
        }
    await factory.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_failed_or_cancelled_construction_not_cached(
    store, connections, monkeypatch, cancel, cloud_secrecy_guard
):
    await seed(store)
    factory = module.SiteManagerFactory(*store)
    original = module._build_sitemanager_managers

    def fail(connection):
        if cancel:
            raise asyncio.CancelledError()
        raise RuntimeError("synthetic-construction-failure")

    monkeypatch.setattr(module, "_build_sitemanager_managers", fail)
    with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
        async with factory.acquire():
            pytest.fail("Failed construction cached")
    assert len(connections) == 1
    connections[0].close.assert_awaited_once()
    monkeypatch.setattr(module, "_build_sitemanager_managers", original)
    async with factory.acquire():
        pass
    assert len(connections) == 2
    await factory.close()
    connections[1].close.assert_awaited_once()


@pytest.mark.asyncio
async def test_probe_connection_is_isolated_and_shutdown_tracks_it(store, connections, cloud_secrecy_guard):
    await seed(store)
    factory = module.SiteManagerFactory(*store)
    async with factory.acquire() as active:
        async with factory.isolated() as probe:
            assert probe.connection is not active.connection
            closing = asyncio.create_task(factory.close())
            await asyncio.sleep(0)
            assert not closing.done()
        probe.connection.close.assert_awaited_once()
        active.connection.close.assert_not_awaited()
    await asyncio.wait_for(closing, 1)
    active.connection.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_running_factory_observes_real_cli_rotation(
    store, connections, tmp_path, monkeypatch, cloud_secrecy_guard
):
    from typer.testing import CliRunner
    from unifi_api.cli import app

    await seed(store)
    monkeypatch.setenv("UNIFI_API_DB_KEY", "synthetic-db-passphrase")
    config = tmp_path / "config.yaml"
    config.write_text(f"db:\n  path: {tmp_path / 'cloud.db'}\n")
    factory = module.SiteManagerFactory(*store)
    async with factory.acquire() as old:
        result = await asyncio.to_thread(
            CliRunner().invoke,
            app,
            ["sitemanager", "update", "--key-stdin", "--config-path", str(config)],
            input="synthetic-cli-rotated-key\n",
        )
        assert result.exit_code == 0, result.output
        cloud_secrecy_guard(result.output, key="synthetic-cli-rotated-key")
        async with factory.acquire() as new:
            assert new.revision == 2
            assert new.connection.key == "synthetic-cli-rotated-key"
        old.connection.close.assert_not_awaited()
    await factory.close()


@pytest.mark.asyncio
async def test_shutdown_close_failure_is_safe_and_retires_generation(store, connections, caplog, cloud_secrecy_guard):
    from unifi_api.services.sitemanager_errors import SiteManagerAPIError

    await seed(store)
    factory = module.SiteManagerFactory(*store)
    async with factory.acquire():
        pass
    connections[0].close.side_effect = RuntimeError(KEY)
    with pytest.raises(SiteManagerAPIError) as error:
        await factory.close()
    assert error.value.kind == "sitemanager_internal_error"
    cloud_secrecy_guard(str(error.value))
    cloud_secrecy_guard(caplog.text)
    assert all(record.exc_info is None for record in caplog.records)
    assert factory._bundles == set()
