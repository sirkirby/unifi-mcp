"""Shared bootstrap + manager-stub helpers for fixture e2e tests.

Phase 8 PR2 introduces a per-resolver fixture e2e layer. Each fixture
test file declares the tools it covers via ``# tool: <name>`` comments
at module top; ``test_resolver_coverage`` enumerates ``type_registry._tool_types``
and asserts every entry is named in at least one fixture file.

The helpers below give cluster tasks a 3-line bootstrap:

    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, {
        ("network", "client_manager", "get_clients"): [{"mac": "aa:01"}],
    })
    body = await graphql_query(app, key, "{ network { clients(controller: \\"...\\") { items { mac } } } }")
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from httpx import ASGITransport, AsyncClient
from unifi_api.auth.api_key import generate_key, hash_key
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.db.crypto import ColumnCipher, derive_key
from unifi_api.db.models import ApiKey, Base, Controller
from unifi_api.server import create_app


def cfg(tmp_path: Path) -> ApiConfig:
    return ApiConfig(
        http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
        logging=LoggingConfig(level="WARNING"),
        db=DbConfig(path=str(tmp_path / "state.db")),
    )


async def bootstrap(tmp_path: Path, *, product: str = "network") -> tuple[Any, str, str]:
    """Bootstrap an admin-keyed app with one controller seeded for ``product``.

    Returns (app, api_key_plaintext, controller_id).
    """
    app = create_app(cfg(tmp_path))
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
                product_kinds=product,
                credentials_blob=cred_blob,
                verify_tls=False,
                is_default=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    return app, material.plaintext, cid


def stub_managers(
    monkeypatch,
    manager_returns: dict[tuple[str, str, str], Any],
) -> None:
    """Patch ManagerFactory so requested (product, manager_attr, method) returns
    the supplied fixture data.

    Example:
        stub_managers(monkeypatch, {
            ("network", "client_manager", "get_clients"): [{"mac": "aa:01"}],
            ("network", "device_manager", "get_devices"): [{"mac": "ap:01"}],
        })
    """
    domain_mgrs: dict[tuple[str, str], MagicMock] = {}
    for (product, mgr_attr, method_name), value in manager_returns.items():
        mgr = domain_mgrs.setdefault((product, mgr_attr), MagicMock())

        # Bind a coroutine that returns the fixture value, capturing it in default
        # to avoid late-binding in the loop.
        async def _bound(*args, _val=value, **kwargs):
            return _val

        setattr(mgr, method_name, _bound)

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


async def graphql_query(app, key: str, query: str) -> dict:
    """Run a GraphQL query against the bootstrapped app and return the JSON body."""
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/graphql", headers=headers, json={"query": query})
        return r.json()
