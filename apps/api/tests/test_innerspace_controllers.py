"""InnerSpace as a controller product: session-only credentials, the factory, and no capability probe."""

from __future__ import annotations

import pytest
from unifi_api.services import managers as managers_module
from unifi_api.services.controllers import (
    InvalidControllerCredentials,
    probe_capabilities,
    update_controller,
    validate_controller_credentials,
)
from unifi_api.services.managers import ManagerFactory, _build_innerspace_managers

from tests.innerspace_data import bootstrap, client

TOKEN = dict(api_token="synthetic-key-material")


@pytest.fixture(autouse=True)
def _db_key(monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")


def test_innerspace_requires_session_credentials():
    validate_controller_credentials(["innerspace"], "u", "p", None)
    validate_controller_credentials(["innerspace", "network"], "u", "p", TOKEN["api_token"])
    for products in (["innerspace"], ["network", "innerspace"]):
        with pytest.raises(InvalidControllerCredentials, match="InnerSpace requires username and password"):
            validate_controller_credentials(products, "", "", TOKEN["api_token"])


@pytest.mark.asyncio
async def test_innerspace_requires_session_credentials_on_create_and_update(tmp_path):
    app, key, cid = await bootstrap(tmp_path, products="network")
    headers = {"Authorization": f"Bearer {key}"}
    async with client(app) as c:
        token_only = {"name": "x", "base_url": "https://192.0.2.20", "product_kinds": ["innerspace"], **TOKEN}
        created = await c.post("/v1/controllers", headers=headers, json=token_only)
        with_session = await c.post(
            "/v1/controllers", headers=headers, json={**token_only, "username": "u", "password": "p"}
        )
        url = f"/v1/controllers/{with_session.json()['id']}"
        cleared = await c.patch(url, headers=headers, json={"username": "", "password": ""})
        admin_create = await c.post(
            "/admin/controllers/create",
            headers=headers,
            data={"name": "y", "base_url": "https://192.0.2.21", "product_kinds": ["innerspace"], **TOKEN},
        )
    async with app.state.sessionmaker() as session:
        with pytest.raises(InvalidControllerCredentials, match="InnerSpace requires username and password"):
            await update_controller(
                session, app.state.cipher, cid, product_kinds=["innerspace"], username="", password=""
            )

    assert created.status_code == 422
    assert "InnerSpace requires username and password" in created.text
    assert with_session.status_code == 201, with_session.text
    assert with_session.json()["product_kinds"] == ["innerspace"]
    assert cleared.status_code == 422
    assert admin_create.status_code == 422


@pytest.mark.asyncio
async def test_adding_innerspace_to_a_token_only_controller_is_refused(tmp_path):
    app, key, _cid = await bootstrap(tmp_path, products="network")
    headers = {"Authorization": f"Bearer {key}"}
    async with client(app) as c:
        token_only = {"name": "t", "base_url": "https://192.0.2.23", "product_kinds": ["network"], **TOKEN}
        created = await c.post("/v1/controllers", headers=headers, json=token_only)
        url = f"/v1/controllers/{created.json()['id']}"
        added = await c.patch(url, headers=headers, json={"product_kinds": ["network", "innerspace"]})
        unchanged = await c.get(url, headers=headers)

    assert created.status_code == 201, created.text
    assert added.status_code == 422
    assert "InnerSpace requires username and password" in added.text
    assert unchanged.json()["product_kinds"] == ["network"]


@pytest.mark.asyncio
async def test_closed_product_set_names_innerspace(tmp_path):
    app, key, _cid = await bootstrap(tmp_path, products="network")
    headers = {"Authorization": f"Bearer {key}"}
    async with client(app) as c:
        unknown = await c.post(
            "/admin/controllers/create",
            headers=headers,
            data={"name": "z", "base_url": "https://192.0.2.22", "product_kinds": ["talk"], "username": "u"},
        )
        form = await c.get("/admin/controllers/_new_form", headers=headers)
    with pytest.raises(InvalidControllerCredentials, match="network, protect, access, or innerspace"):
        validate_controller_credentials(["talk"], "u", "p", None)

    assert unknown.status_code == 422
    assert "network, protect, access, or innerspace" in unknown.text
    assert 'value="innerspace"' in form.text


def test_builder_keys_match_runtime_attributes():
    assert managers_module._PRODUCT_BUILDERS["innerspace"] is _build_innerspace_managers
    assert set(_build_innerspace_managers()) == {
        "attenuation_manager",
        "floor_plan_manager",
        "inventory_manager",
        "project_manager",
        "project_settings_manager",
        "system_manager",
        "wall_manager",
        "wall_type_manager",
    }


@pytest.mark.asyncio
async def test_factory_never_passes_token(tmp_path, monkeypatch):
    built: list[dict] = []

    class _Recorder:
        def __init__(self, *args, **kwargs):
            built.append({"args": args, "kwargs": kwargs})

        async def initialize(self):
            return True

    monkeypatch.setattr("unifi_core.innerspace.managers.connection_manager.InnerSpaceConnectionManager", _Recorder)
    app, _key, cid = await bootstrap(tmp_path)
    factory: ManagerFactory = app.state.manager_factory

    async with app.state.sessionmaker() as session:
        manager = await factory.get_domain_manager(session, cid, "innerspace", "project_manager")

    assert type(manager).__name__ == "InnerSpaceProjectManager"
    assert built == [
        {
            "args": (),
            "kwargs": {"host": "192.0.2.10", "username": "u", "password": "p", "port": 443, "verify_ssl": False},
        }
    ]
    assert "synthetic-key-material" not in repr(built)


class _Reply:
    status = 200

    async def json(self, content_type=None):
        return {"version": "5.0.0"}

    async def text(self):
        return ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Session:
    def __init__(self, seen: list[str]):
        self._seen = seen

    def get(self, url):
        self._seen.append(url)
        return _Reply()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _probe_session(monkeypatch) -> list[str]:
    seen: list[str] = []
    monkeypatch.setattr("unifi_api.services.controllers.aiohttp.ClientSession", lambda **_: _Session(seen))
    return seen


class _Row:
    def __init__(self, products: str):
        self.id, self.name, self.base_url = "c1", "c", "https://192.0.2.10"
        self.product_kinds, self.verify_tls = products, False


@pytest.mark.asyncio
async def test_probe_unchanged_for_other_products(monkeypatch):
    seen = _probe_session(monkeypatch)

    payload = await probe_capabilities(_Row("network,protect,access,innerspace"))

    assert seen == [
        "https://192.0.2.10/api/system",
        "https://192.0.2.10/proxy/network/api/s/default/stat/sysinfo",
        "https://192.0.2.10/proxy/protect/api/cameras",
        "https://192.0.2.10/proxy/access/api/v1/developer/devices",
    ]
    assert payload["products"] == ["network", "protect", "access"]
    assert payload["not_probed"] == ["innerspace"]
    assert payload["version"]["controller"] == "5.0.0"


@pytest.mark.asyncio
async def test_probe_skips_innerspace(monkeypatch):
    seen = _probe_session(monkeypatch)

    payload = await probe_capabilities(_Row("innerspace"))

    assert seen == ["https://192.0.2.10/api/system"]
    assert payload["products"] == []
    assert payload["not_probed"] == ["innerspace"]
    assert payload["probe_error"] is None


@pytest.mark.asyncio
async def test_probe_without_innerspace_reports_nothing_unprobed(monkeypatch):
    _probe_session(monkeypatch)

    payload = await probe_capabilities(_Row("network"))

    assert payload["not_probed"] == []
