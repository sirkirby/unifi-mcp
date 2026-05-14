"""Phase 6 PR4 Task F — end-to-end access GraphQL queries.

Five representative consumer flows (flat list, deep relationship edge,
cross-resource fan-in, pagination, auth scope). Mirrors the protect e2e
sibling in ``test_query_e2e_protect.py``.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from unifi_api.auth.api_key import generate_key, hash_key
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.db.crypto import ColumnCipher, derive_key
from unifi_api.db.models import ApiKey, Base, Controller
from unifi_api.server import create_app


def _cfg(tmp_path: Path) -> ApiConfig:
    return ApiConfig(
        http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
        logging=LoggingConfig(level="WARNING"),
        db=DbConfig(path=str(tmp_path / "state.db")),
    )


async def _bootstrap(tmp_path: Path):
    """Bootstrap an admin-keyed app with one access controller seeded."""
    app = create_app(_cfg(tmp_path))
    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = app.state.sessionmaker
    material = generate_key()
    cid = str(uuid.uuid4())
    cipher = ColumnCipher(derive_key("k"))
    cred_blob = cipher.encrypt(json.dumps({"username": "u", "password": "p", "api_token": None}).encode("utf-8"))
    async with sm() as session:
        session.add(
            ApiKey(
                id=str(uuid.uuid4()),
                prefix=material.prefix,
                hash=hash_key(material.plaintext),
                scopes="admin",
                name="t",
                created_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            Controller(
                id=cid,
                name="c",
                base_url="https://c",
                product_kinds="access",
                credentials_blob=cred_blob,
                verify_tls=False,
                is_default=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    return app, material.plaintext, cid


def _stub_access_managers(
    monkeypatch,
    *,
    doors: list[Any] | None = None,
    door_groups: list[Any] | None = None,
    devices: list[Any] | None = None,
    users: list[Any] | None = None,
    credentials: list[Any] | None = None,
    policies: list[Any] | None = None,
    schedules: list[Any] | None = None,
    visitors: list[Any] | None = None,
    events: list[Any] | None = None,
) -> dict[str, int]:
    """Patch ManagerFactory.get_domain_manager / get_connection_manager so
    access resolvers see preconfigured fixture data.

    Returns a per-method call counter dict for N+1 assertions.
    """
    call_counts: dict[str, int] = {
        "list_doors": 0,
        "list_door_groups": 0,
        "list_devices": 0,
        "list_users": 0,
        "list_credentials": 0,
        "list_policies": 0,
        "list_schedules": 0,
        "list_visitors": 0,
        "list_events": 0,
    }

    async def _stub_list_doors():
        call_counts["list_doors"] += 1
        return doors or []

    async def _stub_list_door_groups():
        call_counts["list_door_groups"] += 1
        return door_groups or []

    async def _stub_list_devices():
        call_counts["list_devices"] += 1
        return devices or []

    async def _stub_list_users():
        call_counts["list_users"] += 1
        return users or []

    async def _stub_list_credentials():
        call_counts["list_credentials"] += 1
        return credentials or []

    async def _stub_list_policies():
        call_counts["list_policies"] += 1
        return policies or []

    async def _stub_list_schedules():
        call_counts["list_schedules"] += 1
        return schedules or []

    async def _stub_list_visitors():
        call_counts["list_visitors"] += 1
        return visitors or []

    async def _stub_list_events(*args, **kwargs):
        call_counts["list_events"] += 1
        return events or []

    fake_door_mgr = MagicMock()
    fake_door_mgr.list_doors = _stub_list_doors
    fake_door_mgr.list_door_groups = _stub_list_door_groups

    fake_device_mgr = MagicMock()
    fake_device_mgr.list_devices = _stub_list_devices

    fake_credential_mgr = MagicMock()
    fake_credential_mgr.list_credentials = _stub_list_credentials

    fake_policy_mgr = MagicMock()
    fake_policy_mgr.list_policies = _stub_list_policies
    fake_policy_mgr.list_schedules = _stub_list_schedules

    fake_visitor_mgr = MagicMock()
    fake_visitor_mgr.list_visitors = _stub_list_visitors

    fake_event_mgr = MagicMock()
    fake_event_mgr.list_events = _stub_list_events

    fake_system_mgr = MagicMock()
    fake_system_mgr.list_users = _stub_list_users

    domain_mgrs = {
        ("access", "door_manager"): fake_door_mgr,
        ("access", "device_manager"): fake_device_mgr,
        ("access", "credential_manager"): fake_credential_mgr,
        ("access", "policy_manager"): fake_policy_mgr,
        ("access", "visitor_manager"): fake_visitor_mgr,
        ("access", "event_manager"): fake_event_mgr,
        ("access", "system_manager"): fake_system_mgr,
    }

    async def _fake_get_domain_manager(self, session, controller_id, product, attr_name):
        return domain_mgrs.get((product, attr_name), MagicMock())

    fake_cm = MagicMock()
    fake_cm.site = "default"
    fake_cm.set_site = AsyncMock()

    async def _fake_get_connection_manager(self, session, controller_id, product):
        return fake_cm

    monkeypatch.setattr(
        "unifi_api.services.managers.ManagerFactory.get_domain_manager",
        _fake_get_domain_manager,
    )
    monkeypatch.setattr(
        "unifi_api.services.managers.ManagerFactory.get_connection_manager",
        _fake_get_connection_manager,
    )

    return call_counts


# ---------------------------------------------------------------------------
# Test 1 — flat list query (doors)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_doors_flat_list(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    fixture_doors = [
        {"id": "door1", "name": "Front Door", "location": "Lobby"},
        {"id": "door2", "name": "Server Room", "location": "Basement"},
    ]
    _stub_access_managers(monkeypatch, doors=fixture_doors)

    headers = {"Authorization": f"Bearer {key}"}
    query = f'{{ access {{ doors(controller: "{cid}") {{ items {{ id name location }} nextCursor }} }} }}'
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/graphql", headers=headers, json={"query": query})
        assert r.status_code == 200
        body = r.json()
        assert body.get("errors") is None, body
        items = body["data"]["access"]["doors"]["items"]
        assert len(items) == 2
        assert {it["name"] for it in items} == {"Front Door", "Server Room"}


# ---------------------------------------------------------------------------
# Test 2 — deep query with relationship edge (Door.policy_assignments)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_door_with_policy_assignments_edge(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    fixture_doors = [
        {"id": "door1", "name": "Front Door"},
        {"id": "door2", "name": "Server Room"},
    ]
    # Door.policy_assignments resolver filters cached policies by
    # `door_ids` containing the door's id. Only door1 has a policy.
    fixture_policies = [
        {
            "id": "pol1",
            "name": "Office Hours",
            "door_ids": ["door1"],
            "user_group_ids": [],
            "enabled": True,
        },
    ]
    _stub_access_managers(
        monkeypatch,
        doors=fixture_doors,
        policies=fixture_policies,
    )

    headers = {"Authorization": f"Bearer {key}"}
    query = f'''{{
      access {{
        doors(controller: "{cid}") {{
          items {{
            id
            name
            policyAssignments {{ id name }}
          }}
        }}
      }}
    }}'''
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/graphql", headers=headers, json={"query": query})
        assert r.status_code == 200
        body = r.json()
        assert body.get("errors") is None, body
        items = body["data"]["access"]["doors"]["items"]
        assert len(items) == 2
        by_id = {it["id"]: it for it in items}
        assert len(by_id["door1"]["policyAssignments"]) == 1
        assert by_id["door1"]["policyAssignments"][0]["name"] == "Office Hours"
        assert by_id["door2"]["policyAssignments"] == []


# ---------------------------------------------------------------------------
# Test 3 — cross-resource query (doors + users + visitors in one round-trip)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_cross_resource_query(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    fixture_doors = [{"id": "door1", "name": "Front Door"}]
    fixture_users = [{"id": "user1", "name": "Alice"}]
    fixture_visitors = [{"id": "vis1", "name": "Bob"}]
    _stub_access_managers(
        monkeypatch,
        doors=fixture_doors,
        users=fixture_users,
        visitors=fixture_visitors,
    )

    headers = {"Authorization": f"Bearer {key}"}
    query = f'''{{
      access {{
        doors(controller: "{cid}") {{ items {{ id name }} }}
        users(controller: "{cid}") {{ items {{ id name }} }}
        visitors(controller: "{cid}") {{ items {{ id name }} }}
      }}
    }}'''
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/graphql", headers=headers, json={"query": query})
        assert r.status_code == 200
        body = r.json()
        assert body.get("errors") is None, body
        access = body["data"]["access"]
        assert access["doors"]["items"][0]["name"] == "Front Door"
        assert access["users"]["items"][0]["name"] == "Alice"
        assert access["visitors"]["items"][0]["name"] == "Bob"


# ---------------------------------------------------------------------------
# Test 4 — pagination with cursor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_doors_pagination(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    fixture_doors = [{"id": f"door{i:03d}", "name": f"Door {i}"} for i in range(5)]
    _stub_access_managers(monkeypatch, doors=fixture_doors)

    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # Page 1: limit=2, cursor=null
        q1 = f'{{ access {{ doors(controller: "{cid}", limit: 2) {{ items {{ id }} nextCursor }} }} }}'
        r1 = await c.post("/v1/graphql", headers=headers, json={"query": q1})
        body1 = r1.json()
        assert body1.get("errors") is None, body1
        page1_ids = [it["id"] for it in body1["data"]["access"]["doors"]["items"]]
        next_cursor = body1["data"]["access"]["doors"]["nextCursor"]
        assert len(page1_ids) == 2
        assert next_cursor is not None

        # Page 2: limit=2, cursor=<page 1's nextCursor>
        q2 = (
            f'{{ access {{ doors(controller: "{cid}", limit: 2, cursor: "{next_cursor}") '
            f"{{ items {{ id }} nextCursor }} }} }}"
        )
        r2 = await c.post("/v1/graphql", headers=headers, json={"query": q2})
        body2 = r2.json()
        assert body2.get("errors") is None, body2
        page2_ids = [it["id"] for it in body2["data"]["access"]["doors"]["items"]]
        assert len(page2_ids) == 2
        # No overlap between pages
        assert set(page1_ids).isdisjoint(set(page2_ids))


# ---------------------------------------------------------------------------
# Test 5 — auth scope (read-scope key works; no key fails)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_auth_scope(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, _admin_key, cid = await _bootstrap(tmp_path)

    sm = app.state.sessionmaker
    read_material = generate_key()
    async with sm() as session:
        session.add(
            ApiKey(
                id=str(uuid.uuid4()),
                prefix=read_material.prefix,
                hash=hash_key(read_material.plaintext),
                scopes="read",
                name="r",
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    _stub_access_managers(
        monkeypatch,
        doors=[{"id": "door1", "name": "Front"}],
    )

    query = f'{{ access {{ doors(controller: "{cid}", limit: 1) {{ items {{ id }} }} }} }}'
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # Read-scope key works for read fields
        r_read = await c.post(
            "/v1/graphql",
            headers={"Authorization": f"Bearer {read_material.plaintext}"},
            json={"query": query},
        )
        body_read = r_read.json()
        assert body_read.get("errors") is None, body_read
        assert body_read["data"]["access"]["doors"]["items"][0]["id"] == "door1"

        # No bearer -> errors with FORBIDDEN/UNAUTHENTICATED code
        r_unauth = await c.post("/v1/graphql", json={"query": query})
        body_unauth = r_unauth.json()
        assert body_unauth.get("errors")
        codes = [e.get("extensions", {}).get("code") for e in body_unauth["errors"]]
        assert any(code in ("UNAUTHENTICATED", "FORBIDDEN") for code in codes)
