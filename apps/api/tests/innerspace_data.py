"""Synthetic InnerSpace console replies and an app wired to a console session stand-in.

The connection manager is the real ``InnerSpaceConnectionManager``; only its
``request`` and ``request_bytes`` are replaced, so the real domain managers, the
input validation and ``ensure_app_running`` all run.
"""

from __future__ import annotations

import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient
from unifi_api.auth.api_key import generate_key, hash_key
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig, PolicyConfig, ResponsePolicyConfig
from unifi_api.db.crypto import ColumnCipher, derive_key
from unifi_api.db.models import ApiKey, Base, Controller
from unifi_api.server import create_app
from unifi_core.innerspace.managers.connection_manager import (
    INTEGRATION_PREFIX,
    INTERNAL_PROJECT_PATH,
    SYSTEM_PATH,
    InnerSpaceConnectionManager,
)

PLAN = "00000000-0000-4000-8000-0000000000a1"
SITE = "00000000-0000-4000-8000-0000000000b1"
ASSET_URL = f"{INTEGRATION_PREFIX}/assets/00000000-0000-4000-8000-0000000000c1/00000000-0000-4000-8000-0000000000c2.png"
MAC = "00:00:5e:00:53:01"
DEVICE_IP = "192.0.2.50"
# A value that must never reach a response, a log line or an audit row.
REJECTED = "rejected-value-7f3a"
# A console-supplied value under a sensitive key name; the response policy decides whether it is shown.
SECRET_VALUE = "synthetic-shelf-value"

SYSTEM = {"apps": {"controllers": [{"name": "innerspace", "isInstalled": True, "isRunning": True, "version": "1.4.3"}]}}
NOT_INSTALLED = {"apps": {"controllers": [{"name": "network", "isInstalled": True, "isRunning": True}]}}
INTERNAL_PROJECT = {"data": {"project": {"id": "p1", "title": "Synthetic", "unit": "metric"}}}
FLOOR_PLANS = {
    "floor_plans": [
        {
            "id": PLAN,
            "name": "Plan A",
            "floor_number": 1,
            "width": 1000,
            "height": 800,
            "ppm": 100.0,
            "origin_x": 0,
            "origin_y": 0,
            "site_id": SITE,
            "image_url": ASSET_URL,
        }
    ]
}
PROJECT = {
    "data": {
        "project": {"id": "p1", "title": "Synthetic", "createdAt": "2026-01-01T00:00:00Z"},
        "plans": [{"id": PLAN, "title": "Plan A", "ordering": 1, "siteId": SITE}],
        "shapes": [
            {
                "id": "map-1",
                "type": "map",
                "planId": PLAN,
                "urlImage": ASSET_URL,
                "imageScale": {"x": 1, "y": 1},
                "imageOffset": {"x": 0, "y": 0},
            },
            {
                "id": "wall-1",
                "type": "wall",
                "planId": PLAN,
                "variant": "drywall",
                "position": [{"x": -100, "y": 100}, {"x": 100, "y": 100}],
            },
            {
                "id": "wall-2",
                "type": "wall",
                "planId": PLAN,
                "variant": "glass",
                "position": [{"x": -100, "y": -100}, {"x": 100, "y": -100}],
            },
            {
                "id": "device-1",
                "type": "device",
                "planId": PLAN,
                "title": "Lobby AP",
                "productId": "U7PRO",
                "mount": "ceiling",
                "position": [{"x": 0, "y": 2.5, "z": 0}],
                "meta": {"mac": MAC, "ip": DEVICE_IP},
            },
        ],
        "wallTypes": [{"id": "wt-1", "name": "Drywall", "attenuation": 3}],
        "attenuationObjectTypes": [dict(id="ao-1", name="Shelf", password=SECRET_VALUE)],
    }
}
ACCESS_POINTS = {
    "access_points": [
        {
            "id": "ap-1",
            "name": "Lobby AP",
            "mac": MAC,
            "floor_plan_id": PLAN,
            "x": 250.0,
            "y": 300.0,
            "height": 2.7,
            "mount": "ceiling",
            "status": "online",
        }
    ]
}
SWITCHES = {"switches": [{"id": "sw-1", "name": "Core", "mac": "00:00:5e:00:53:02", "floor_plan_id": PLAN}]}
INVENTORY = {"devices": [{"id": "inv-1", "name": "Spare", "mac": "00:00:5e:00:53:03", "serial": "SYN1"}]}

REPLIES: dict[str, Any] = {
    SYSTEM_PATH: SYSTEM,
    INTERNAL_PROJECT_PATH: INTERNAL_PROJECT,
    f"{INTEGRATION_PREFIX}/floor_plans": FLOOR_PLANS,
    f"{INTEGRATION_PREFIX}/project": PROJECT,
    f"{INTEGRATION_PREFIX}/access_points": ACCESS_POINTS,
    f"{INTEGRATION_PREFIX}/switches": SWITCHES,
    f"{INTEGRATION_PREFIX}/inventory": INVENTORY,
}


def console_cm(replies: dict[str, Any] | None = None, *, error: BaseException | None = None):
    """A real connection manager whose console replies come from ``replies`` (or raise ``error``)."""
    cm = InnerSpaceConnectionManager("192.0.2.10", "synthetic-admin", "synthetic-login")
    table = {**REPLIES, **(replies or {})}

    async def _request(method, path, *, operation, params=None, json=None):
        if error is not None and path != SYSTEM_PATH:
            raise error
        return deepcopy(table[path])

    cm.request = AsyncMock(side_effect=_request)
    cm.request_bytes = AsyncMock(return_value=(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, "image/png"))
    return cm


def cfg(tmp_path, *, redact_sensitive_fields: bool = True) -> ApiConfig:
    return ApiConfig(
        http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
        logging=LoggingConfig(level="WARNING"),
        db=DbConfig(path=str(tmp_path / "state.db")),
        policy=PolicyConfig(response=ResponsePolicyConfig(redact_sensitive_fields=redact_sensitive_fields)),
    )


def credentials(**values: Any) -> bytes:
    return ColumnCipher(derive_key("k")).encrypt(json.dumps(values).encode())


async def bootstrap(tmp_path, *, products: str = "innerspace", scopes: str = "admin", redact: bool = True):
    """An app with one default controller for ``products`` and a key with ``scopes``."""
    app = create_app(cfg(tmp_path, redact_sensitive_fields=redact))
    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    material = generate_key()
    cid = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    async with app.state.sessionmaker() as session:
        session.add(
            ApiKey(
                id=str(uuid.uuid4()),
                prefix=material.prefix,
                hash=hash_key(material.plaintext),
                scopes=scopes,
                name="t",
                created_at=now,
            )
        )
        session.add(
            Controller(
                id=cid,
                name="c",
                base_url="https://192.0.2.10",
                product_kinds=products,
                credentials_blob=credentials(username="u", password="p", api_token="synthetic-key-material"),
                verify_tls=False,
                is_default=True,
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()
    return app, material.plaintext, cid


def install(app, cid: str, cm) -> None:
    app.state.manager_factory._connection_cache[(cid, "innerspace", None)] = cm


def client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def graphql(app, key: str, query: str) -> dict:
    async with client(app) as c:
        response = await c.post("/v1/graphql", headers={"Authorization": f"Bearer {key}"}, json={"query": query})
    assert response.status_code == 200, response.text
    return response.json()
