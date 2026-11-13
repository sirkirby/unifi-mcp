"""Real transport privacy, omitted surface defaults and read lease ownership."""

import logging

import pytest
from httpx import ASGITransport, AsyncClient
from unifi_api.services import sitemanager_managers
from unifi_api.services.sitemanager_connections import create_connection
from unifi_core.sitemanager.managers.connection_manager import SiteManagerConnectionManager
from unifi_core.sitemanager.models.connections import SiteManagerConnectionCreate

from tests.sitemanager_data import bootstrap
from tests.sitemanager_secrets import KEY


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["rest", "graphql", "action"])
async def test_real_core_transport_log_hides_account_ids(tmp_path, monkeypatch, unused_tcp_port, caplog, surface):
    app, key, factory = await bootstrap(tmp_path, monkeypatch, fake=False)
    monkeypatch.setattr(
        sitemanager_managers,
        "SiteManagerConnectionManager",
        lambda *, api_key: SiteManagerConnectionManager(api_key, base_url=f"http://127.0.0.1:{unused_tcp_port}"),
    )
    async with app.state.sessionmaker() as session:
        await create_connection(
            session, app.state.cipher, SiteManagerConnectionCreate(name="Synthetic", site_manager_api_key=KEY)
        )
        await session.commit()
    marker = "CALLER-ID-123"
    try:
        with caplog.at_level(logging.WARNING):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                headers = {"Authorization": f"Bearer {key}"}
                if surface == "rest":
                    response = await client.get("/v1/sitemanager/hosts/" + marker, headers=headers)
                elif surface == "graphql":
                    response = await client.post(
                        "/v1/graphql",
                        headers=headers,
                        json={"query": '{ sitemanager { sdwanConfig(configId:"' + marker + '") { id } } }'},
                    )
                else:
                    response = await client.post(
                        "/v1/sitemanager/actions/sitemanager_get_host",
                        headers=headers,
                        json={"args": {"host_id": marker}},
                    )
        if surface == "graphql":
            assert response.status_code == 200
            assert response.json()["errors"][0]["extensions"]["code"] == "UPSTREAM_ERROR"
        else:
            assert response.status_code == 502
            assert response.json()["detail"]["kind"] == "sitemanager_upstream_error"
        records = [record for record in caplog.records if record.name.startswith("unifi_core.sitemanager")]
        assert len(records) == 1
        template = "/v1/sd-wan-configs/{id}" if surface == "graphql" else "/v1/hosts/{id}"
        assert records[0].getMessage() == f"Site Manager request GET {template} failed (ClientConnectorError)"
        assert marker not in caplog.text and marker not in response.text
        assert KEY not in caplog.text and KEY not in response.text
        assert all(record.exc_info is None for record in caplog.records)
    finally:
        await factory.close()
        await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("surface,index", [("rest", 4), ("graphql", 4), ("graphql", 5)])
async def test_omitted_metrics_defaults_reach_manager(tmp_path, monkeypatch, surface, index):
    from tests.sitemanager_data import CASES
    from tests.test_sitemanager_reads import request_case

    app, key, factory = await bootstrap(tmp_path, monkeypatch)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await request_case(client, key, CASES[index], surface)
        assert response.status_code == 200
        if surface == "graphql":
            assert "errors" not in response.json()
            assert len(response.json()["data"]["sitemanager"][CASES[index][-1]]["items"]) == 1
        else:
            assert len(response.json()["items"]) == 1
        if index == 4:
            factory.bundle.isp_metrics_manager.get_metrics.assert_awaited_once_with(metric_type="1h", period_limit=12)
        else:
            factory.bundle.isp_metrics_manager.query_metrics.assert_awaited_once_with(
                metric_type="1h",
                period_limit=12,
                sites=[{"host_id": "synthetic-host", "site_id": "synthetic-site"}],
            )
        assert factory.acquisitions == 1 and factory.open_leases == 0 and factory.releases == 1
    finally:
        await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["rest", "graphql", "action"])
@pytest.mark.parametrize("outcome", ["success", "upstream_error", "projection_error", "cancelled"])
async def test_read_releases_lease_on_every_exit(tmp_path, monkeypatch, surface, outcome):
    import asyncio
    from unittest.mock import Mock

    from unifi_api.graphql.types.sitemanager.hosts import SiteManagerHost
    from unifi_core.exceptions import UniFiConnectionError

    from tests.sitemanager_data import CASES
    from tests.test_sitemanager_reads import request_case

    app, key, factory = await bootstrap(tmp_path, monkeypatch)
    entered, never = asyncio.Event(), asyncio.Event()
    projection = None
    task = None
    if outcome == "upstream_error":
        factory.bundle.inventory_manager.get_host.side_effect = UniFiConnectionError("Synthetic upstream failure")
    elif outcome == "projection_error":
        projection = Mock(side_effect=ValueError("Synthetic projection failure"))
        monkeypatch.setattr(SiteManagerHost, "from_manager_output", projection)
    elif outcome == "cancelled":

        async def blocked(*args, **kwargs):
            entered.set()
            await never.wait()

        factory.bundle.inventory_manager.get_host.side_effect = blocked
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            if outcome == "cancelled":
                task = asyncio.create_task(request_case(client, key, CASES[1], surface))
                await asyncio.wait_for(entered.wait(), timeout=2)
                assert factory.open_leases == 1 and factory.releases == 0
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                response = await request_case(client, key, CASES[1], surface)
                if surface == "graphql":
                    assert response.status_code == 200
                    if outcome == "success":
                        assert response.json()["data"]["sitemanager"]["host"]["id"] == "synthetic-host"
                    else:
                        assert response.json()["errors"][0]["extensions"]["code"] == (
                            "UPSTREAM_ERROR" if outcome == "upstream_error" else "INTERNAL"
                        )
                else:
                    assert (
                        response.status_code
                        == {"success": 200, "upstream_error": 502, "projection_error": 500}[outcome]
                    )
                    if outcome == "success":
                        assert response.json()["data"]["id"] == "synthetic-host"
            factory.bundle.inventory_manager.get_host.assert_awaited_once()
            if projection is not None:
                projection.assert_called_once()
            assert factory.acquisitions == 1
            assert factory.open_leases == 0
            assert factory.releases == 1
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await app.state.engine.dispose()
