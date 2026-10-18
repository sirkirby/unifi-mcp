"""The MCP tools, REST routes and GraphQL return the same incident evidence for the same bounded input.

Every adapter runs against the same mocked controller answers, decoded by the
product SDKs (aiounifi for Network, uiprotect for Protect), with the same
frozen clocks. After removing each transport's envelope the payloads must be
equal and valid, for both the default client view and ``detail="full"``, and
carry the scenario's per-source status.
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
from unifi_core.incident_evidence_view import IncidentEvidenceView, client_view, view_to_json
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.event_manager import EventManager as NetworkEventManager
from unifi_core.protect.managers.event_manager import EventManager as ProtectEventManager

CORPUS = Path(__file__).parent / "fixtures" / "incident_evidence"
RESPONSES = json.loads((CORPUS / "collection" / "controller_responses.json").read_text())
SCHEMA = json.loads((CORPUS / "incident-evidence.v1.schema.json").read_text())
VIEW_SCHEMA = json.loads((CORPUS / "incident-evidence-view.v1.schema.json").read_text())
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


async def via_mcp(product: str, manager: Any, monkeypatch, presentation: dict[str, Any]) -> dict[str, Any]:
    if product == "network":
        from unifi_network_mcp import runtime
        from unifi_network_mcp.tools import incident_evidence

        monkeypatch.setattr(runtime, "get_event_manager", lambda: manager)
        monkeypatch.setattr(runtime, "get_connection_manager", lambda: SimpleNamespace(site="default"))
    else:
        from unifi_protect_mcp.tools import incident_evidence

        monkeypatch.setattr(incident_evidence, "event_manager", manager)
        monkeypatch.setattr(incident_evidence, "connection_manager", SimpleNamespace(client=object()))
    response = await incident_evidence.get_incident_evidence(**INPUTS[product], **presentation)
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
    controller_id = str(uuid.uuid4())
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
                id=controller_id,
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
    return app, material.plaintext, controller_id


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


async def via_rest(
    product: str, manager: Any, tmp_path: Path, monkeypatch, presentation: dict[str, Any]
) -> dict[str, Any]:
    app, key, _ = await _api_app(tmp_path, product, monkeypatch)
    factory = app.state.manager_factory
    factory.get_event_reader = AsyncMock(return_value=manager)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/sites/default/incident-evidence/{product}",
            params=_query({**INPUTS[product], **presentation}),
            headers={"Authorization": f"Bearer {key}"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"data", "render_hint"}
    return body["data"]


_GRAPHQL_TYPES = {
    "start": "String!",
    "end": "String!",
    "device_macs": "[String!]",
    "camera_ids": "[String!]",
    "location_id": "String",
    "max_window_seconds": "Int",
    "max_events": "Int",
    "max_calls": "Int",
    "max_elapsed_ms": "Int",
    "mappings": "JSON",
    "detail": "String",
    "max_records_returned": "Int",
    "resume_after": "String",
}


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


async def via_graphql(
    product: str, manager: Any, tmp_path: Path, monkeypatch, presentation: dict[str, Any]
) -> dict[str, Any]:
    app, key, controller_id = await _api_app(tmp_path, product, monkeypatch)
    app.state.manager_factory.get_event_reader = AsyncMock(return_value=manager)
    arguments = {**INPUTS[product], **presentation}
    declared = ", ".join(f"${_camel(name)}: {_GRAPHQL_TYPES[name]}" for name in arguments)
    passed = ", ".join(f"{_camel(name)}: ${_camel(name)}" for name in arguments)
    query = (
        f"query Evidence($controller: ID!, {declared}) {{ {product} {{ "
        f"incidentEvidence(controller: $controller, {passed}) {{ document }} }} }}"
    )
    variables = {"controller": controller_id, **{_camel(name): value for name, value in arguments.items()}}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/graphql",
            json={"query": query, "variables": variables},
            headers={"Authorization": f"Bearer {key}"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "errors" not in body, body
    return body["data"][product]["incidentEvidence"]["document"]


CASES = [(product, scenario) for product in ("network", "protect") for scenario in sorted(RESPONSES[product])]
PRESENTATIONS = {"view": {}, "view-1": {"max_records_returned": 1}, "full": {"detail": "full"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("presentation", sorted(PRESENTATIONS))
@pytest.mark.parametrize(("product", "scenario"), CASES, ids=[f"{p}-{s}" for p, s in CASES])
async def test_mcp_rest_and_graphql_return_the_same_evidence(
    product, scenario, presentation, frozen_clocks, monkeypatch, tmp_path
):
    build = network_manager if product == "network" else protect_manager
    arguments = PRESENTATIONS[presentation]
    from_mcp = await via_mcp(product, build(scenario), monkeypatch, arguments)
    from_rest = await via_rest(product, build(scenario), tmp_path / "rest", monkeypatch, arguments)
    from_graphql = await via_graphql(product, build(scenario), tmp_path / "graphql", monkeypatch, arguments)

    assert from_mcp == from_rest == from_graphql
    assert PRIVATE not in json.dumps(from_rest)
    if presentation == "full":
        jsonschema.validate(from_rest, SCHEMA)
        evidence = validate_incident_evidence(from_rest)
        (source,) = evidence.sources
        assert evidence.mappings is not None or product == "protect"
    else:
        jsonschema.validate(from_rest, VIEW_SCHEMA)
        view = IncidentEvidenceView.model_validate(from_rest)
        (source,) = view.sources
        assert view.record_selection.max_records_returned == arguments.get("max_records_returned", 25)
    assert source.outcome.value == RESPONSES[product][scenario]["outcome"]


@pytest.mark.asyncio
async def test_mcp_rest_and_graphql_resume_a_view_alike(frozen_clocks, monkeypatch, tmp_path):
    resumed = 0
    for product, scenario in CASES:
        build = network_manager if product == "network" else protect_manager
        first = await via_mcp(product, build(scenario), monkeypatch, {"max_records_returned": 1})
        cursor = first["record_selection"]["next_cursor"]
        if cursor is None:
            continue
        arguments = {"max_records_returned": 1, "resume_after": cursor}
        from_mcp = await via_mcp(product, build(scenario), monkeypatch, arguments)
        from_rest = await via_rest(product, build(scenario), tmp_path / f"{scenario}-rest", monkeypatch, arguments)
        from_graphql = await via_graphql(
            product, build(scenario), tmp_path / f"{scenario}-graphql", monkeypatch, arguments
        )
        assert from_mcp == from_rest == from_graphql
        assert from_rest["record_selection"]["before_resume"]["total"] == 1
        resumed += 1
    assert resumed, "some recorded answer holds more than one record"


@pytest.mark.asyncio
@pytest.mark.parametrize(("product", "scenario"), CASES, ids=[f"{p}-{s}" for p, s in CASES])
async def test_the_view_is_the_projection_of_the_full_document(product, scenario, frozen_clocks, monkeypatch):
    build = network_manager if product == "network" else protect_manager
    full = await via_mcp(product, build(scenario), monkeypatch, {"detail": "full"})
    view = await via_mcp(product, build(scenario), monkeypatch, {})
    assert view == view_to_json(client_view(validate_incident_evidence(full)))
