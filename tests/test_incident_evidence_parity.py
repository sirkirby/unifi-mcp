"""The MCP tools and the API routes return the same incident evidence for the same bounded input.

Both adapters run against the same mocked controller answers, decoded by the
product SDKs (aiounifi for Network, uiprotect for Protect), with the same
frozen clocks. After removing each transport's envelope the documents must
be equal, contract-valid, and carry the scenario's per-source status.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import jsonschema
import pytest
from httpx import ASGITransport, AsyncClient
from uiprotect.api import ProtectApiClient
from uiprotect.exceptions import NotAuthorized, NvrError
from unifi_api.auth.api_key import generate_key, hash_key
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.db.crypto import ColumnCipher, derive_key
from unifi_api.db.models import ApiKey, Base, Controller
from unifi_api.server import create_app
from unifi_core import incident_collection
from unifi_core.incident_evidence import parse_utc, validate_incident_evidence
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.event_manager import EventManager as NetworkEventManager
from unifi_core.protect.managers.event_manager import EventManager as ProtectEventManager

CORPUS = Path(__file__).parent / "fixtures" / "incident_evidence"
RESPONSES = json.loads((CORPUS / "collection" / "controller_responses.json").read_text())
SCHEMA = json.loads((CORPUS / "incident-evidence.v1.schema.json").read_text())
NOW = parse_utc(RESPONSES["now"])
PRIVATE = "fixture-private-controller-text"
NVR_URL = "https://controller.invalid/proxy/protect/api/events"

INPUTS = {
    "network": {
        **RESPONSES["request"],
        "device_macs": ["AA:BB:CC:00:10:01"],
        "max_events": 500,
        "max_calls": 5,
        "max_elapsed_ms": 20_000,
        "mappings": [
            {
                "entity": {"kind": "network_device", "id_kind": "mac", "id": "aa:bb:cc:00:10:01"},
                "target": {"kind": "camera", "id_kind": "protect_camera_id", "id": "cam-fixture-000a"},
                "source": "operator_input",
            }
        ],
    },
    "protect": {**RESPONSES["request"], "camera_ids": ["cam-fixture-000a"], "max_events": 500, "max_calls": 5},
}


# --- controller answers through the real SDK decoders ---------------------------------------


def _network_body(response: Any) -> Any:
    if isinstance(response, dict) and "raise" in response:
        return {"timeout": asyncio.TimeoutError(), "unavailable": aiohttp.ClientConnectionError(PRIVATE)}[
            response["raise"]
        ]
    return response


def _protect_body(response: Any) -> Any:
    if isinstance(response, dict) and "raise" in response:
        return {
            "auth_failure": lambda: NotAuthorized(f"Request failed: {NVR_URL} - Status: 401 - Reason: {PRIVATE}"),
            "permission_denied": lambda: NotAuthorized(f"Request failed: {NVR_URL} - Status: 403 - Reason: {PRIVATE}"),
            "timeout": lambda: TimeoutError(),
            "unavailable": lambda: NvrError(f"Request failed: {NVR_URL} - Status: 503 - Reason: {PRIVATE}"),
        }[response["raise"]]()
    return response


def _answers(bodies: list[Any]):
    remaining = list(bodies)

    def next_body() -> Any:
        body = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        if isinstance(body, BaseException):
            raise body
        return body

    return next_body


def network_manager(scenario: str) -> NetworkEventManager:
    answer = _answers([_network_body(r) for r in RESPONSES["network"][scenario]["responses"]])
    connection = ConnectionManager("controller.invalid", "fixture-user", "fixture-password")
    connection.ensure_connected = AsyncMock(return_value=True)
    connection.controller = MagicMock()

    async def transport(api_request: Any) -> Any:
        return api_request.decode(json.dumps(answer()).encode())

    connection.controller.request = transport
    manager = NetworkEventManager(connection)
    manager._use_v2 = True
    return manager


def protect_manager(scenario: str) -> ProtectEventManager:
    answer = _answers([_protect_body(r) for r in RESPONSES["protect"][scenario]["responses"]])
    client = ProtectApiClient("controller.invalid", 443, "fixture-user", "fixture-password", store_sessions=False)

    async def api_request_raw(url: str, method: str = "get", **_: Any) -> bytes:
        assert method == "get"
        return json.dumps(answer()).encode()

    client.api_request_raw = api_request_raw
    return ProtectEventManager(SimpleNamespace(client=client), {})


@pytest.fixture
def frozen_clocks(monkeypatch):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is None else NOW.astimezone(tz)

    monkeypatch.setattr(incident_collection, "datetime", FrozenDatetime)
    monkeypatch.setattr(incident_collection, "time", SimpleNamespace(monotonic=lambda: 1_000.0))
    with patch("unifi_core.network.managers.event_manager.time.time", return_value=NOW.timestamp()):
        yield


# --- the two adapters -------------------------------------------------------------------------


async def via_mcp(product: str, manager: Any, monkeypatch) -> dict[str, Any]:
    if product == "network":
        from unifi_network_mcp import runtime
        from unifi_network_mcp.tools import incident_evidence

        monkeypatch.setattr(runtime, "get_event_manager", lambda: manager)
        monkeypatch.setattr(runtime, "get_connection_manager", lambda: SimpleNamespace(site="default"))
    else:
        from unifi_protect_mcp.tools import incident_evidence

        monkeypatch.setattr(incident_evidence, "event_manager", manager)
    response = await incident_evidence.get_incident_evidence(**INPUTS[product])
    assert response["success"] is True, response
    assert set(response) == {"success", "data"}
    return response["data"]


async def _api_app(tmp_path: Path, product: str, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app = create_app(
        ApiConfig(
            http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
            logging=LoggingConfig(level="WARNING"),
            db=DbConfig(path=str(tmp_path / "state.db")),
        )
    )
    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    material = generate_key()
    stamp = datetime.now(timezone.utc)
    async with app.state.sessionmaker() as session:
        session.add(
            ApiKey(
                id=str(uuid.uuid4()),
                prefix=material.prefix,
                hash=hash_key(material.plaintext),
                scopes="read",
                name="parity",
                created_at=stamp,
            )
        )
        session.add(
            Controller(
                id=str(uuid.uuid4()),
                name="fixture-controller",
                base_url="https://controller.invalid",
                product_kinds=product,
                credentials_blob=ColumnCipher(derive_key("k")).encrypt(b'{"username":"u","password":"p"}'),
                verify_tls=False,
                is_default=True,
                created_at=stamp,
                updated_at=stamp,
            )
        )
        await session.commit()
    return app, material.plaintext


def _query(arguments: dict[str, Any]) -> list[tuple[str, Any]]:
    params: list[tuple[str, Any]] = []
    for key, value in arguments.items():
        if key == "mappings":
            params.append((key, json.dumps(value)))
        elif isinstance(value, list):
            params.extend((key, item) for item in value)
        else:
            params.append((key, value))
    return params


async def via_api(product: str, manager: Any, tmp_path: Path, monkeypatch) -> dict[str, Any]:
    app, key = await _api_app(tmp_path, product, monkeypatch)
    factory = app.state.manager_factory
    factory.get_event_reader = AsyncMock(return_value=manager)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/sites/default/incident-evidence/{product}",
            params=_query(INPUTS[product]),
            headers={"Authorization": f"Bearer {key}"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"data", "render_hint"}
    return body["data"]


CASES = [(product, scenario) for product in ("network", "protect") for scenario in sorted(RESPONSES[product])]


@pytest.mark.asyncio
@pytest.mark.parametrize(("product", "scenario"), CASES, ids=[f"{p}-{s}" for p, s in CASES])
async def test_mcp_and_api_return_the_same_evidence(product, scenario, frozen_clocks, monkeypatch, tmp_path):
    build = network_manager if product == "network" else protect_manager
    from_mcp = await via_mcp(product, build(scenario), monkeypatch)
    from_api = await via_api(product, build(scenario), tmp_path, monkeypatch)

    assert from_mcp == from_api
    jsonschema.validate(from_api, SCHEMA)
    evidence = validate_incident_evidence(from_api)
    (source,) = evidence.sources
    assert source.outcome.value == RESPONSES[product][scenario]["outcome"]
    assert PRIVATE not in json.dumps(from_api)
    assert evidence.mappings is not None or product == "protect"
