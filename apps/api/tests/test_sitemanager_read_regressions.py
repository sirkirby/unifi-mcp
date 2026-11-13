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
