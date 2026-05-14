"""Phase 5A PR2 Cluster 4 — network filtering resource routes.

Covers firewall groups/zones, QoS rules, DPI applications/categories,
content-filters, ACL rules, and OON policies (LIST + DETAIL where applicable).
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from unifi_api.auth.api_key import generate_key, hash_key
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.db.crypto import ColumnCipher, derive_key
from unifi_api.db.models import ApiKey, Base, Controller
from unifi_api.server import create_app


def _cfg(tmp_path):
    return ApiConfig(
        http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
        logging=LoggingConfig(level="WARNING"),
        db=DbConfig(path=str(tmp_path / "state.db")),
    )


async def _bootstrap(tmp_path, products="network"):
    app = create_app(_cfg(tmp_path))
    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = app.state.sessionmaker
    cipher = ColumnCipher(derive_key("k"))
    cid = str(uuid.uuid4())
    material = generate_key()
    async with sm() as session:
        session.add(
            ApiKey(
                id=str(uuid.uuid4()),
                prefix=material.prefix,
                hash=hash_key(material.plaintext),
                scopes="read",
                name="t",
                created_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            Controller(
                id=cid,
                name="N",
                base_url="https://x",
                product_kinds=products,
                credentials_blob=cipher.encrypt(b'{"username":"u","password":"p","api_token":null}'),
                verify_tls=False,
                is_default=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    return app, material.plaintext, cid


class _FakeCM:
    def __init__(self) -> None:
        self.site = "default"

    async def initialize(self) -> None:
        return None

    async def set_site(self, s: str) -> None:
        self.site = s


def _stub_connection(app, cid: str) -> _FakeCM:
    fake = _FakeCM()
    app.state.manager_factory._connection_cache[(cid, "network")] = fake
    return fake


# ---------- firewall groups ----------


@pytest.mark.asyncio
async def test_list_firewall_groups_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake = [
        {"_id": "g1", "name": "internal", "group_type": "address-group", "group_members": ["10.0.0.0/24"]},
        {"_id": "g2", "name": "ports", "group_type": "port-group", "group_members": ["80", "443"]},
    ]

    async def fake_get(self):
        return fake

    from unifi_core.network.managers.firewall_manager import FirewallManager

    monkeypatch.setattr(FirewallManager, "get_firewall_groups", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/firewall/groups?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 2
    names = {i["name"] for i in body["items"]}
    assert names == {"internal", "ports"}
    members = {i["id"]: i["members"] for i in body["items"]}
    assert "10.0.0.0/24" in members["g1"]


@pytest.mark.asyncio
async def test_get_firewall_group_details_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    target = {"_id": "g7", "name": "deny", "group_type": "address-group", "group_members": ["1.2.3.4"]}

    async def fake_get(self, gid):
        return target if gid == "g7" else None

    from unifi_core.network.managers.firewall_manager import FirewallManager

    monkeypatch.setattr(FirewallManager, "get_firewall_group_by_id", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/firewall/groups/g7?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "detail"
    assert body["data"]["id"] == "g7"
    assert body["data"]["members"] == ["1.2.3.4"]


@pytest.mark.asyncio
async def test_get_firewall_group_details_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self, gid):
        return None

    from unifi_core.network.managers.firewall_manager import FirewallManager

    monkeypatch.setattr(FirewallManager, "get_firewall_group_by_id", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/firewall/groups/missing?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_firewall_groups_capability_mismatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, products="protect")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/firewall/groups?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 409
    assert r.json()["detail"]["kind"] == "capability_mismatch"


# ---------- firewall zones ----------


@pytest.mark.asyncio
async def test_list_firewall_zones_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake = [
        {"_id": "z1", "name": "internal", "default_policy": "ALLOW", "networks": ["n1", "n2"]},
        {"_id": "z2", "name": "external", "default_policy": "BLOCK", "networks": []},
    ]

    async def fake_get(self):
        return fake

    from unifi_core.network.managers.firewall_manager import FirewallManager

    monkeypatch.setattr(FirewallManager, "get_firewall_zones", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/firewall/zones?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 2
    names = {i["name"] for i in body["items"]}
    assert names == {"internal", "external"}


# ---------- QoS rules ----------


@pytest.mark.asyncio
async def test_list_qos_rules_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake = [
        {"_id": "q1", "name": "voice", "enabled": True, "qos_marking": {"dscp_code": 46}},
        {"_id": "q2", "name": "video", "enabled": False, "qos_marking": {"dscp_code": 34}},
    ]

    async def fake_get(self):
        return fake

    from unifi_core.network.managers.qos_manager import QosManager

    monkeypatch.setattr(QosManager, "get_qos_rules", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/qos-rules?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_get_qos_rule_details_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    target = {"_id": "q1", "name": "voice", "enabled": True}

    async def fake_get(self, rule_id):
        return target if rule_id == "q1" else None

    from unifi_core.network.managers.qos_manager import QosManager

    monkeypatch.setattr(QosManager, "get_qos_rule_details", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/qos-rules/q1?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "detail"
    assert body["data"]["id"] == "q1"


@pytest.mark.asyncio
async def test_get_qos_rule_details_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self, rule_id):
        return None

    from unifi_core.network.managers.qos_manager import QosManager

    monkeypatch.setattr(QosManager, "get_qos_rule_details", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/qos-rules/missing?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_qos_rule_details_unifi_not_found(tmp_path, monkeypatch) -> None:
    """Manager refactor PR #172: get_qos_rule_details raises UniFiNotFoundError."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    from unifi_core.exceptions import UniFiNotFoundError
    from unifi_core.network.managers.qos_manager import QosManager

    async def fake_get(self, rule_id):
        raise UniFiNotFoundError("qos_rule", rule_id)

    monkeypatch.setattr(QosManager, "get_qos_rule_details", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/qos-rules/missing?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 404


# ---------- DPI ----------


@pytest.mark.asyncio
async def test_list_dpi_applications_happy_path(tmp_path, monkeypatch) -> None:
    """DPI manager returns a paginated wrapper {data, totalCount, ...}.

    The route unwraps wrapper["data"] before serializing.
    """
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    fake_cm = _stub_connection(app, cid)
    # DPI route requires the cm to carry a UniFiAuth with an API key.
    from unifi_core.auth import UniFiAuth

    fake_cm.unifi_auth = UniFiAuth(api_key="test-token")

    wrapper = {
        "data": [
            {"id": 65537, "name": "WhatsApp", "categoryId": 0},
            {"id": 65538, "name": "Telegram", "categoryId": 0},
        ],
        "totalCount": 2,
        "offset": 0,
        "limit": 100,
    }

    async def fake_get(self, **kwargs):
        return wrapper

    from unifi_core.network.managers.dpi_manager import DpiManager

    monkeypatch.setattr(DpiManager, "get_dpi_applications", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/dpi-applications?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 2
    # category id 0 is real and falsy — verify it round-trips intact.
    assert body["items"][0]["category_id"] == 0


@pytest.mark.asyncio
async def test_list_dpi_applications_returns_501_when_no_api_token(tmp_path, monkeypatch) -> None:
    """When the controller has no API token, DPI must return 501 with a
    clear `api_key_required` hint, not a silent empty list or 500."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    fake_cm = _stub_connection(app, cid)
    from unifi_core.auth import UniFiAuth

    fake_cm.unifi_auth = UniFiAuth(api_key=None)  # explicit no-token

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/dpi-applications?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 501, r.text
    detail = r.json()["detail"]
    assert detail["kind"] == "api_key_required"
    assert detail["missing"] == "controller_api_token"
    assert detail["controller"] == cid


@pytest.mark.asyncio
async def test_list_dpi_categories_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    fake_cm = _stub_connection(app, cid)
    from unifi_core.auth import UniFiAuth

    fake_cm.unifi_auth = UniFiAuth(api_key="test-token")

    wrapper = {
        "data": [
            {"id": 0, "name": "Instant messengers"},
            {"id": 1, "name": "Peer-to-peer"},
        ],
        "totalCount": 2,
        "offset": 0,
        "limit": 100,
    }

    async def fake_get(self, **kwargs):
        return wrapper

    from unifi_core.network.managers.dpi_manager import DpiManager

    monkeypatch.setattr(DpiManager, "get_dpi_categories", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/dpi-categories?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "list"
    ids = {i["id"] for i in body["items"]}
    assert ids == {0, 1}


# ---------- content filters ----------


@pytest.mark.asyncio
async def test_list_content_filters_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake = [
        {"_id": "cf1", "name": "kids", "level": "STRICT"},
        {"_id": "cf2", "name": "guest", "level": "MODERATE"},
    ]

    async def fake_get(self):
        return fake

    from unifi_core.network.managers.content_filter_manager import ContentFilterManager

    monkeypatch.setattr(ContentFilterManager, "get_content_filters", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/content-filters?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_get_content_filter_details_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    target = {"_id": "cf9", "name": "lab", "level": "STRICT"}

    async def fake_get(self, filter_id):
        return target if filter_id == "cf9" else None

    from unifi_core.network.managers.content_filter_manager import ContentFilterManager

    monkeypatch.setattr(ContentFilterManager, "get_content_filter_by_id", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/content-filters/cf9?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "detail"
    assert body["data"]["id"] == "cf9"


@pytest.mark.asyncio
async def test_get_content_filter_details_unifi_not_found(tmp_path, monkeypatch) -> None:
    """Manager refactor PR #172: get_content_filter_by_id raises UniFiNotFoundError."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    from unifi_core.exceptions import UniFiNotFoundError
    from unifi_core.network.managers.content_filter_manager import ContentFilterManager

    async def fake_get(self, filter_id):
        raise UniFiNotFoundError("content_filter", filter_id)

    monkeypatch.setattr(ContentFilterManager, "get_content_filter_by_id", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/content-filters/missing?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 404


# ---------- ACL ----------


@pytest.mark.asyncio
async def test_list_acl_rules_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake = [
        {"_id": "a1", "name": "block-cam", "action": "BLOCK", "mac_acl_network_id": "n1", "type": "MAC"},
        {"_id": "a2", "name": "allow-iot", "action": "ALLOW", "mac_acl_network_id": "n1", "type": "MAC"},
    ]

    async def fake_get(self, network_id=None):
        return fake

    from unifi_core.network.managers.acl_manager import AclManager

    monkeypatch.setattr(AclManager, "get_acl_rules", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/acl-rules?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_get_acl_rule_details_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    target = {"_id": "a3", "name": "deny-x", "action": "BLOCK", "mac_acl_network_id": "n1", "type": "MAC"}

    async def fake_get(self, rule_id):
        return target if rule_id == "a3" else None

    from unifi_core.network.managers.acl_manager import AclManager

    monkeypatch.setattr(AclManager, "get_acl_rule_by_id", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/acl-rules/a3?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "detail"
    assert body["data"]["id"] == "a3"


@pytest.mark.asyncio
async def test_get_acl_rule_details_unifi_not_found(tmp_path, monkeypatch) -> None:
    """Manager refactor PR #172: get_acl_rule_by_id raises UniFiNotFoundError."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    from unifi_core.exceptions import UniFiNotFoundError
    from unifi_core.network.managers.acl_manager import AclManager

    async def fake_get(self, rule_id):
        raise UniFiNotFoundError("acl_rule", rule_id)

    monkeypatch.setattr(AclManager, "get_acl_rule_by_id", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/acl-rules/missing?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 404


# ---------- OON ----------


@pytest.mark.asyncio
async def test_list_oon_policies_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake = [
        {"_id": "o1", "name": "guest-throttle", "enabled": True, "targets": [{"id": "t1"}]},
        {"_id": "o2", "name": "iot-isolate", "enabled": False, "targets": []},
    ]

    async def fake_get(self):
        return fake

    from unifi_core.network.managers.oon_manager import OonManager

    monkeypatch.setattr(OonManager, "get_oon_policies", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/oon-policies?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_get_oon_policy_details_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    target = {"_id": "o5", "name": "office-policy", "enabled": True, "targets": [{"id": "t1"}, {"id": "t2"}]}

    async def fake_get(self, policy_id):
        return target if policy_id == "o5" else None

    from unifi_core.network.managers.oon_manager import OonManager

    monkeypatch.setattr(OonManager, "get_oon_policy_by_id", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/oon-policies/o5?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "detail"
    assert body["data"]["id"] == "o5"
