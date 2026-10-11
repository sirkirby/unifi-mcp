"""REST and GraphQL exposure of bounded, read-only incident evidence for Network and Protect."""

from __future__ import annotations

import json
from unittest.mock import patch

import jsonschema
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from tests.routes.resources.test_network_misc import _bootstrap, _stub_connection
from tests.unit._incident_evidence_support import (
    NOW,
    PRIVATE,
    REQUEST,
    RESPONSES,
    SCHEMA,
    FrozenDatetime,
    network_pages,
    network_scenario,
    protect_page_rows,
    protect_scenario,
    sdk_network_events,
    sdk_protect_events,
)
from unifi_api.db.models import ApiKey
from unifi_api.graphql.types.incident_evidence import IncidentEvidence
from unifi_core.incident_evidence import validate_incident_evidence

NETWORK_PATH = "/v1/sites/default/incident-evidence/network"
PROTECT_PATH = "/v1/sites/default/incident-evidence/protect"
SENTINEL = "operator-supplied-sentinel-value"


class Harness:
    """An app whose manager factory hands out freshly built event managers."""

    def __init__(self, app, key: str, cid: str) -> None:
        self.app, self.key, self.cid = app, key, cid
        self.headers = {"Authorization": f"Bearer {key}"}
        self.build = None
        self.calls: list[dict] = []

        async def get_event_reader(session, controller_id, product, *, site=None):
            self.calls.append({"product": product, "attr": "event_manager", "site": site})
            return self.build()

        app.state.manager_factory.get_event_reader = get_event_reader

    def client(self) -> AsyncClient:
        return AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test")

    async def rest(self, path: str, build, **params):
        self.build = build
        query = {"controller": self.cid, **{k: v for k, v in {**REQUEST, **params}.items() if v is not None}}
        async with self.client() as client:
            return await client.get(path, params=query, headers=self.headers)

    async def graphql(self, query: str):
        async with self.client() as client:
            return await client.post("/v1/graphql", headers=self.headers, json={"query": query})


@pytest.fixture
def clock():
    with (
        patch("unifi_core.incident_collection.datetime", FrozenDatetime),
        patch("unifi_core.network.managers.event_manager.time.time", return_value=NOW.timestamp()),
    ):
        yield


async def make_harness(tmp_path, monkeypatch, products="network,protect", scopes=None) -> Harness:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, products=products)
    _stub_connection(app, cid)
    if scopes is not None:
        async with app.state.sessionmaker() as session:
            api_key = (await session.execute(select(ApiKey))).scalar_one()
            api_key.scopes = scopes
            await session.commit()
    return Harness(app, key, cid)


def check_document(document: dict) -> None:
    jsonschema.validate(document, SCHEMA)
    validate_incident_evidence(document)


def without_wall_time(document: dict) -> dict:
    """The document minus the one measured wall-clock figure, which differs between two real reads."""
    usage = {**document["budgets"]["usage"], "elapsed_ms": 0}
    return {**document, "budgets": {**document["budgets"], "usage": usage}}


def gql_args(cid: str, **extra: str) -> str:
    base = f'controller: "{cid}", start: "{REQUEST["start"]}", end: "{REQUEST["end"]}"'
    return base + "".join(f", {k}: {v}" for k, v in extra.items())


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", sorted(RESPONSES["network"]))
async def test_network_rest_keeps_each_source_outcome(tmp_path, monkeypatch, clock, scenario) -> None:
    harness = await make_harness(tmp_path, monkeypatch)
    response = await harness.rest(NETWORK_PATH, lambda: network_scenario(scenario))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["render_hint"] == {"kind": "detail"}
    check_document(body["data"])
    (source,) = body["data"]["sources"]
    assert source["outcome"] == RESPONSES["network"][scenario]["outcome"]
    assert source["scope"]["site"] == "default"
    assert PRIVATE not in response.text
    assert harness.calls == [{"product": "network", "attr": "event_manager", "site": "default"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", sorted(RESPONSES["protect"]))
async def test_protect_rest_keeps_each_source_outcome(tmp_path, monkeypatch, clock, scenario) -> None:
    harness = await make_harness(tmp_path, monkeypatch)
    response = await harness.rest(PROTECT_PATH, lambda: protect_scenario(scenario))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["render_hint"] == {"kind": "detail"}
    check_document(body["data"])
    (source,) = body["data"]["sources"]
    assert source["outcome"] == RESPONSES["protect"][scenario]["outcome"]
    assert PRIVATE not in response.text
    assert harness.calls == [{"product": "protect", "attr": "event_manager", "site": None}]


@pytest.mark.asyncio
async def test_network_graphql_returns_the_same_document_as_rest(tmp_path, monkeypatch, clock) -> None:
    harness = await make_harness(tmp_path, monkeypatch)
    rest = await harness.rest(NETWORK_PATH, lambda: network_scenario("events"), location_id="fixture-location-a")
    harness.build = lambda: network_scenario("events")
    gql = await harness.graphql(
        f"{{ network {{ incidentEvidence({gql_args(harness.cid, locationId=chr(34) + 'fixture-location-a' + chr(34))}) "
        "{ document } } }"
    )
    assert gql.status_code == 200 and "errors" not in gql.json(), gql.text
    document = gql.json()["data"]["network"]["incidentEvidence"]["document"]
    assert rest.status_code == 200
    assert without_wall_time(document) == without_wall_time(rest.json()["data"])
    check_document(document)
    assert PRIVATE not in gql.text


@pytest.mark.asyncio
async def test_protect_graphql_returns_the_same_document_as_rest(tmp_path, monkeypatch, clock) -> None:
    harness = await make_harness(tmp_path, monkeypatch)
    rest = await harness.rest(PROTECT_PATH, lambda: protect_scenario("events"), location_id="fixture-location-a")
    harness.build = lambda: protect_scenario("events")
    gql = await harness.graphql(
        f"{{ protect {{ incidentEvidence({gql_args(harness.cid, locationId=chr(34) + 'fixture-location-a' + chr(34))}) "
        "{ document } } }"
    )
    assert gql.status_code == 200 and "errors" not in gql.json(), gql.text
    document = gql.json()["data"]["protect"]["incidentEvidence"]["document"]
    assert without_wall_time(document) == without_wall_time(rest.json()["data"])
    check_document(document)


def test_the_type_projection_is_the_document_unchanged() -> None:
    document = {"schema": "unifi-incident-evidence", "records": []}
    with patch("unifi_api.graphql.types.incident_evidence.evidence_to_json", return_value=document):
        projected = IncidentEvidence.from_manager_output(object())
    assert projected.to_dict() is document


@pytest.mark.asyncio
async def test_network_filters_and_mappings_reach_the_collector(tmp_path, monkeypatch, clock) -> None:
    harness = await make_harness(tmp_path, monkeypatch)
    mapping = {
        "entity": {"kind": "network_device", "id_kind": "mac", "id": "aa:bb:cc:00:10:01"},
        "target": {"kind": "camera", "id_kind": "protect_camera_id", "id": "cam-fixture-000a"},
        "source": "operator_input",
    }
    response = await harness.rest(
        NETWORK_PATH,
        lambda: network_scenario("events"),
        device_macs=["aa:bb:cc:00:10:01", "aa:bb:cc:00:10:02"],
        mappings=json.dumps([mapping]),
    )
    assert response.status_code == 200, response.text
    document = response.json()["data"]
    check_document(document)
    assert document["sources"][0]["scope"]["site"] == "default"
    assert '"verified"' in response.text


@pytest.mark.asyncio
async def test_protect_camera_ids_are_each_their_own_source(tmp_path, monkeypatch, clock) -> None:
    harness = await make_harness(tmp_path, monkeypatch)
    response = await harness.rest(
        PROTECT_PATH,
        lambda: sdk_protect_events([]),
        camera_ids=["cam-fixture-000a", "cam-fixture-000b"],
    )
    assert response.status_code == 200, response.text
    document = response.json()["data"]
    check_document(document)
    assert len(document["sources"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [NETWORK_PATH, PROTECT_PATH])
@pytest.mark.parametrize(
    "overrides",
    [
        {"start": SENTINEL},
        {"end": "2026-08-08T12:00:00"},
        {"max_calls": 0},
        {"max_events": 10_001},
        {"mappings": SENTINEL},
        {"mappings": json.dumps({"key": SENTINEL})},
        {"mappings": json.dumps([{"entity": SENTINEL}])},
    ],
)
async def test_invalid_input_is_a_422_that_never_echoes_it(tmp_path, monkeypatch, clock, path, overrides) -> None:
    harness = await make_harness(tmp_path, monkeypatch)
    response = await harness.rest(path, lambda: network_scenario("events"), **overrides)
    assert response.status_code == 422, response.text
    assert isinstance(response.json()["detail"], str) and response.json()["detail"]
    assert SENTINEL not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("product", ["network", "protect"])
async def test_graphql_rejects_invalid_input_without_echoing_it(tmp_path, monkeypatch, clock, product) -> None:
    harness = await make_harness(tmp_path, monkeypatch)
    harness.build = lambda: network_scenario("events")
    response = await harness.graphql(
        f'{{ {product} {{ incidentEvidence(controller: "{harness.cid}", start: "{SENTINEL}", '
        f'end: "{REQUEST["end"]}") {{ document }} }} }}'
    )
    errors = response.json()["errors"]
    assert errors[0]["extensions"]["code"] == "BAD_REQUEST"
    assert SENTINEL not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [NETWORK_PATH, PROTECT_PATH])
async def test_a_key_without_read_scope_is_rejected(tmp_path, monkeypatch, clock, path) -> None:
    harness = await make_harness(tmp_path, monkeypatch, scopes="write")
    response = await harness.rest(path, lambda: network_scenario("events"))
    assert response.status_code == 403
    async with harness.client() as client:
        anonymous = await client.get(path, params={"controller": harness.cid, **REQUEST})
    assert anonymous.status_code == 401
    assert harness.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("product", ["network", "protect"])
async def test_graphql_without_read_scope_is_forbidden(tmp_path, monkeypatch, clock, product) -> None:
    harness = await make_harness(tmp_path, monkeypatch, scopes="write")
    harness.build = lambda: network_scenario("events")
    response = await harness.graphql(f"{{ {product} {{ incidentEvidence({gql_args(harness.cid)}) {{ document }} }} }}")
    assert response.json()["errors"][0]["extensions"]["code"] == "FORBIDDEN"
    assert harness.calls == []


@pytest.mark.asyncio
async def test_a_controller_without_the_product_is_a_capability_mismatch(tmp_path, monkeypatch, clock) -> None:
    harness = await make_harness(tmp_path, monkeypatch, products="network")
    response = await harness.rest(PROTECT_PATH, lambda: protect_scenario("events"))
    assert response.status_code == 409
    assert harness.calls == []


@pytest.mark.asyncio
async def test_network_call_budget_exhaustion_is_reported_as_partial(tmp_path, monkeypatch, clock) -> None:
    harness = await make_harness(tmp_path, monkeypatch)
    pages = network_pages(230)
    response = await harness.rest(NETWORK_PATH, lambda: sdk_network_events(*pages), max_calls=1)
    assert response.status_code == 200, response.text
    document = response.json()["data"]
    check_document(document)
    assert document["budgets"]["exhausted"] == ["calls"]
    assert [s["outcome"] for s in document["sources"]] == ["partial"]
    assert document["coverage_complete"] is False


@pytest.mark.asyncio
async def test_protect_call_budget_exhaustion_is_reported_as_partial(tmp_path, monkeypatch, clock) -> None:
    harness = await make_harness(tmp_path, monkeypatch)
    rows = protect_page_rows(100)
    response = await harness.rest(PROTECT_PATH, lambda: sdk_protect_events(rows), max_calls=1)
    assert response.status_code == 200, response.text
    document = response.json()["data"]
    check_document(document)
    assert document["budgets"]["exhausted"] == ["calls"]
    assert [s["outcome"] for s in document["sources"]] == ["partial"]
    assert document["coverage_complete"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [NETWORK_PATH, PROTECT_PATH])
async def test_unexpected_failures_do_not_leak_exception_text(tmp_path, monkeypatch, clock, path) -> None:
    harness = await make_harness(tmp_path, monkeypatch)
    target = "collect_network_incident_evidence" if path == NETWORK_PATH else "collect_protect_incident_evidence"
    with patch(f"unifi_api.services.incident_evidence.{target}", side_effect=RuntimeError(PRIVATE)):
        response = await harness.rest(path, lambda: network_scenario("events"))
    assert response.status_code == 502
    assert PRIVATE not in response.text
    assert "RuntimeError" in response.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("product", ["network", "protect"])
async def test_graphql_unexpected_failures_do_not_leak_exception_text(tmp_path, monkeypatch, clock, product) -> None:
    harness = await make_harness(tmp_path, monkeypatch)
    harness.build = lambda: network_scenario("events")
    with patch(
        f"unifi_api.services.incident_evidence.collect_{product}_incident_evidence", side_effect=RuntimeError(PRIVATE)
    ):
        response = await harness.graphql(
            f"{{ {product} {{ incidentEvidence({gql_args(harness.cid)}) {{ document }} }} }}"
        )
    assert response.json()["errors"][0]["extensions"]["code"] == "INTERNAL"
    assert PRIVATE not in response.text


# --- acquisition: after validation, inside the budget, never a listener -------------------


class _ColdFactory:
    """The real get_event_reader over a cache miss: connecting is slow, and every action is recorded."""

    def __init__(self, harness: Harness, *, connect=None) -> None:
        import asyncio
        import types

        from unifi_api.services.managers import ManagerFactory

        self.actions: list[str] = []
        factory = harness.app.state.manager_factory
        factory.get_event_reader = types.MethodType(ManagerFactory.get_event_reader, factory)
        factory._domain_cache.clear()

        async def connection(*_args, **_kwargs):
            self.actions.append("connection_initialize")
            if connect is not None:
                connect()
            await asyncio.sleep(0.05)
            return object()

        actions = self.actions
        build = harness.build

        class Events:
            def __init__(self, inner) -> None:
                self._inner = inner

            async def start_listening(self) -> None:
                actions.append("background_listener_started")

            def __getattr__(self, name):
                actions.append("event_read")
                return getattr(self._inner, name)

        factory.get_connection_manager = connection
        factory._builders_for = lambda product: {"event_manager": lambda cm: Events(build())}
        self.factory = factory


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [NETWORK_PATH, PROTECT_PATH])
async def test_invalid_input_and_an_exhausted_window_never_acquire_a_manager(tmp_path, monkeypatch, clock, path):
    harness = await make_harness(tmp_path, monkeypatch)
    harness.build = lambda: (
        network_scenario("healthy_empty") if path == NETWORK_PATH else protect_scenario("healthy_empty")
    )
    cold = _ColdFactory(harness)
    response = await harness.rest(path, harness.build, start="bad-time")
    assert response.status_code == 422 and cold.actions == []
    response = await harness.rest(path, harness.build, max_window_seconds=1)
    assert response.status_code == 200
    document = response.json()["data"]
    assert document["budgets"]["exhausted"] == ["window"] and document["overall"] == "failed"
    assert cold.actions == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [NETWORK_PATH, PROTECT_PATH])
async def test_acquisition_is_charged_to_the_elapsed_budget_and_starts_no_listener(tmp_path, monkeypatch, path):
    harness = await make_harness(tmp_path, monkeypatch)
    harness.build = lambda: (
        network_scenario("healthy_empty") if path == NETWORK_PATH else protect_scenario("healthy_empty")
    )
    cold = _ColdFactory(harness)
    response = await harness.rest(path, harness.build, max_elapsed_ms=10)
    document = response.json()["data"]
    check_document(document)
    assert document["budgets"]["exhausted"] == ["elapsed"]
    assert document["budgets"]["usage"]["elapsed_ms"] >= 10
    assert document["overall"] == "failed" and document["coverage_complete"] is False
    assert cold.actions == ["connection_initialize"]
    assert cold.factory._listener_tasks == {} and cold.factory._domain_cache == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [NETWORK_PATH, PROTECT_PATH])
async def test_a_cold_read_within_budget_uses_an_uncached_manager_without_a_listener(
    tmp_path, monkeypatch, clock, path
):
    harness = await make_harness(tmp_path, monkeypatch)
    harness.build = lambda: (
        network_scenario("healthy_empty") if path == NETWORK_PATH else protect_scenario("healthy_empty")
    )
    cold = _ColdFactory(harness)
    response = await harness.rest(path, harness.build)
    assert response.json()["data"]["overall"] == "empty"
    assert "background_listener_started" not in cold.actions
    assert cold.factory._listener_tasks == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("product", ["network", "protect"])
async def test_acquisition_failures_are_classified_source_failures_without_controller_text(
    tmp_path, monkeypatch, caplog, product
):
    harness = await make_harness(tmp_path, monkeypatch)

    def fail():
        raise RuntimeError(PRIVATE)

    harness.build = lambda: None
    _ColdFactory(harness, connect=fail)
    path = NETWORK_PATH if product == "network" else PROTECT_PATH
    with caplog.at_level("DEBUG"):
        response = await harness.rest(path, harness.build)
        gql = await harness.graphql(f"{{ {product} {{ incidentEvidence({gql_args(harness.cid)}) {{ document }} }} }}")
    assert response.status_code == 200
    document = response.json()["data"]
    check_document(document)
    assert document["overall"] == "failed"
    assert document["sources"][0]["outcome"] == "unavailable"
    assert gql.json()["data"][product]["incidentEvidence"]["document"]["sources"][0]["outcome"] == "unavailable"
    assert PRIVATE not in response.text and PRIVATE not in gql.text
    assert PRIVATE not in caplog.text


# --- framework argument coercion never echoes the rejected value ---------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("path", "product"), [(NETWORK_PATH, "network"), (PROTECT_PATH, "protect")])
async def test_argument_coercion_errors_drop_the_rejected_value(tmp_path, monkeypatch, caplog, path, product):
    harness = await make_harness(tmp_path, monkeypatch)
    with caplog.at_level("DEBUG"):
        response = await harness.rest(path, lambda: None, max_calls=SENTINEL)
        query = (
            "query Q($c: ID!, $s: String!, $e: String!, $m: Int) "
            f"{{ {product} {{ incidentEvidence(controller: $c, start: $s, end: $e, maxCalls: $m) {{ document }} }} }}"
        )
        async with harness.client() as client:
            gql = await client.post(
                "/v1/graphql",
                headers=harness.headers,
                json={
                    "query": query,
                    "variables": {"c": harness.cid, "s": REQUEST["start"], "e": REQUEST["end"], "m": SENTINEL},
                },
            )
        arguments = gql_args(harness.cid, maxCalls=json.dumps(SENTINEL))
        literal = await harness.graphql(f"{{ {product} {{ incidentEvidence({arguments}) {{ document }} }} }}")
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "max_calls"]
    for body in (response.text, gql.text, literal.text):
        assert SENTINEL not in body
    for error in (gql.json()["errors"][0], literal.json()["errors"][0]):
        assert error["extensions"]["code"] == "BAD_REQUEST"
    assert gql.json()["errors"][0]["message"] == "Variable '$m' has an invalid value."
    # The test client logs the URL it sent; nothing the server logged may carry the value.
    assert all(SENTINEL not in record.getMessage() for record in caplog.records if record.name != "httpx")
    assert harness.calls == []
