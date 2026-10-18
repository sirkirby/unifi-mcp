"""REST and GraphQL exposure of bounded, read-only incident evidence for Network and Protect."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import jsonschema
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from tests.routes.resources.test_network_misc import _bootstrap, _stub_connection
from tests.unit._incident_evidence_support import (
    CORPUS_DIR,
    NOW,
    PRIVATE,
    REQUEST,
    RESPONSES,
    SCHEMA,
    VIEW_SCHEMA,
    FrozenDatetime,
    network_page_rows,
    network_pages,
    network_scenario,
    protect_page_rows,
    protect_scenario,
    sdk_network_events,
    sdk_protect_events,
)
from unifi_api.db.models import ApiKey
from unifi_api.graphql.types.incident_evidence import IncidentEvidence
from unifi_core.incident_evidence import evidence_to_json, validate_incident_evidence
from unifi_core.incident_evidence_view import (
    TEXT_TOKEN_LIMITS,
    VIEW_BYTE_LIMIT,
    VIEW_TOKEN_BUDGET,
    EvidencePresentation,
    IncidentEvidenceView,
    client_view,
    estimated_tokens,
    view_to_json,
)

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
    """The default bounded view, or the full contract document when detail=full was asked for."""
    if document["schema"] == "unifi-incident-evidence-view":
        jsonschema.validate(document, VIEW_SCHEMA)
        IncidentEvidenceView.model_validate(document)
    else:
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


def test_the_type_projection_renders_through_the_core_presentation() -> None:
    case = CORPUS_DIR / "cases" / "network_protect_real_shapes.json"
    evidence = validate_incident_evidence(json.loads(case.read_text())["expected"])
    assert IncidentEvidence.from_manager_output(evidence).to_dict() == view_to_json(client_view(evidence))
    full = IncidentEvidence.from_manager_output(evidence, presentation=EvidencePresentation(detail="full"))
    assert full.to_dict() == evidence_to_json(evidence)


@pytest.mark.asyncio
@pytest.mark.parametrize(("path", "build"), [(NETWORK_PATH, "network"), (PROTECT_PATH, "protect")])
async def test_detail_full_returns_the_contract_document_and_the_view_counts_omissions(
    tmp_path, monkeypatch, clock, path, build
) -> None:
    harness = await make_harness(tmp_path, monkeypatch)
    scenario = network_scenario if build == "network" else protect_scenario
    full = (await harness.rest(path, lambda: scenario("events"), detail="full")).json()["data"]
    view = (await harness.rest(path, lambda: scenario("events"), max_records_returned=1)).json()["data"]
    assert full["schema"] == "unifi-incident-evidence" and view["schema"] == "unifi-incident-evidence-view"
    check_document(full)
    check_document(view)
    assert len(view["records"]) == 1
    assert view["record_selection"]["collected"]["total"] == len(full["records"])
    assert view["record_selection"]["omitted"]["total"] == len(full["records"]) - 1
    for key in ("overall", "coverage_complete", "mappings", "requested_window"):
        assert view[key] == full[key]


@pytest.mark.asyncio
@pytest.mark.parametrize(("path", "product"), [(NETWORK_PATH, "network"), (PROTECT_PATH, "protect")])
async def test_a_view_resumes_after_its_cursor_alike_on_rest_and_graphql(
    tmp_path, monkeypatch, clock, path, product
) -> None:
    harness = await make_harness(tmp_path, monkeypatch)
    scenario = network_scenario if product == "network" else protect_scenario
    first = (await harness.rest(path, lambda: scenario("events"), max_records_returned=1)).json()["data"]
    cursor = first["record_selection"]["next_cursor"]
    assert cursor is not None
    rest = (await harness.rest(path, lambda: scenario("events"), max_records_returned=1, resume_after=cursor)).json()
    resumed = rest["data"]
    check_document(resumed)
    assert resumed["record_selection"]["resume_after"] == cursor
    assert resumed["record_selection"]["before_resume"]["total"] == 1
    assert {r["evidence_id"] for r in resumed["records"]}.isdisjoint(r["evidence_id"] for r in first["records"])
    harness.build = lambda: scenario("events")
    arguments = gql_args(
        harness.cid, locationId='"fixture-location-a"', maxRecordsReturned="1", resumeAfter=json.dumps(cursor)
    )
    gql = await harness.graphql(f"{{ {product} {{ incidentEvidence({arguments}) {{ document }} }} }}")
    assert gql.status_code == 200 and "errors" not in gql.json(), gql.text
    assert without_wall_time(gql.json()["data"][product]["incidentEvidence"]["document"]) == without_wall_time(resumed)


@pytest.mark.asyncio
async def test_a_network_site_is_bounded_like_a_label_before_any_read(tmp_path, monkeypatch, clock) -> None:
    harness = await make_harness(tmp_path, monkeypatch)
    for site in (SENTINEL + '"', "x" * 129):
        response = await harness.rest(f"/v1/sites/{site}/incident-evidence/network", lambda: network_scenario("events"))
        assert response.status_code == 422, response.text
        assert SENTINEL not in response.text and response.json()["detail"].startswith("site:")
    harness.build = lambda: network_scenario("events")
    response = await harness.graphql(
        f"{{ network {{ incidentEvidence({gql_args(harness.cid, site=json.dumps(SENTINEL + chr(92)))}) "
        "{ document } } }"
    )
    assert response.json()["errors"][0]["extensions"]["code"] == "BAD_REQUEST"
    assert SENTINEL not in response.text
    assert harness.calls == []


SPACES = "A" + " " * 4_000_000 + "B"


@pytest.mark.asyncio
@pytest.mark.parametrize("product", ["network", "protect"])
async def test_a_long_whitespace_run_is_cut_and_marked_alike_on_rest_and_graphql(
    tmp_path, monkeypatch, clock, product
) -> None:
    """Four million spaces in a controller event cost a token each: the summary is cut and marked, never sent whole."""
    if product == "network":
        rows, summary = [{**network_page_rows(1)[0], "message_raw": SPACES}], SPACES
        build, path = (lambda: sdk_network_events({"data": rows, "total_element_count": 1})), NETWORK_PATH
    else:
        rows, summary = [{**protect_page_rows(1)[0], "smartDetectTypes": [SPACES]}], f"motion: {SPACES}"
        build, path = (lambda: sdk_protect_events(rows)), PROTECT_PATH
    harness = await make_harness(tmp_path, monkeypatch)
    response = await harness.rest(path, build)
    assert response.status_code == 200, response.text[:500]
    view = response.json()["data"]
    check_document(view)
    (record,) = view["records"]
    assert record["truncated"] == {"summary": len(summary)}
    assert record["summary"] == summary[: TEXT_TOKEN_LIMITS["summary"]]
    assert estimated_tokens({"success": True, "data": view}) <= VIEW_TOKEN_BUDGET
    assert len(response.content) < min(10_000, VIEW_BYTE_LIMIT)
    harness.build = build
    arguments = gql_args(harness.cid, locationId='"fixture-location-a"')
    graphql = await harness.graphql(f"{{ {product} {{ incidentEvidence({arguments}) {{ document }} }} }}")
    assert graphql.status_code == 200 and "errors" not in graphql.json(), graphql.text[:500]
    assert without_wall_time(graphql.json()["data"][product]["incidentEvidence"]["document"]) == without_wall_time(view)
    assert len(graphql.content) < 10_000


@pytest.mark.asyncio
@pytest.mark.parametrize("product", ["network", "protect"])
async def test_graphql_detail_full_returns_the_contract_document(tmp_path, monkeypatch, clock, product) -> None:
    harness = await make_harness(tmp_path, monkeypatch)
    scenario = network_scenario if product == "network" else protect_scenario
    rest = await harness.rest(
        NETWORK_PATH if product == "network" else PROTECT_PATH, lambda: scenario("events"), detail="full"
    )
    harness.build = lambda: scenario("events")
    arguments = gql_args(harness.cid, locationId='"fixture-location-a"', detail='"full"')
    gql = await harness.graphql(f"{{ {product} {{ incidentEvidence({arguments}) {{ document }} }} }}")
    assert gql.status_code == 200 and "errors" not in gql.json(), gql.text
    document = gql.json()["data"][product]["incidentEvidence"]["document"]
    assert document["schema"] == "unifi-incident-evidence"
    assert without_wall_time(document) == without_wall_time(rest.json()["data"])


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
        {"detail": SENTINEL},
        {"max_records_returned": 0},
        {"max_records_returned": 51},
        {"detail": "full", "max_records_returned": 5},
        {"resume_after": SENTINEL},
        {"detail": "full", "resume_after": "1||network.events|int|7"},
        {"location_id": SENTINEL + '"'},
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
    response = await harness.graphql(
        f"{{ {product} {{ incidentEvidence({gql_args(harness.cid, detail=chr(34) + SENTINEL + chr(34))}) "
        "{ document } } }"
    )
    assert response.json()["errors"][0]["extensions"]["code"] == "BAD_REQUEST"
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
async def test_evidence_too_broad_for_its_view_is_refused_alike_on_rest_and_graphql(
    tmp_path, monkeypatch, clock, product
) -> None:
    """A document whose sources and assertions alone overfill the view is refused, never sent oversized."""
    bounds = Path(__file__).resolve().parents[4] / "tests/fixtures/incident_evidence/view-bounds"
    fixture = json.loads((bounds / "skeleton_refusal.json").read_text())
    refused = validate_incident_evidence(fixture["evidence"])
    harness = await make_harness(tmp_path, monkeypatch)
    harness.build = lambda: network_scenario("events")
    path = NETWORK_PATH if product == "network" else PROTECT_PATH
    with patch(f"unifi_api.services.incident_evidence.collect_{product}_incident_evidence", return_value=refused):
        response = await harness.rest(path, lambda: network_scenario("events"))
        assert response.status_code == 422
        assert response.json()["detail"] == fixture["refusal"]
        full = await harness.rest(path, lambda: network_scenario("events"), detail="full")
        assert full.status_code == 200 and full.json()["data"] == evidence_to_json(refused)
        graphql = await harness.graphql(
            f"{{ {product} {{ incidentEvidence({gql_args(harness.cid)}) {{ document }} }} }}"
        )
    error = graphql.json()["errors"][0]
    assert error["extensions"]["code"] == "BAD_REQUEST" and error["message"] == fixture["refusal"]


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


# --- second review: classified cold failures, declared locations, type-only categories -----


@pytest.mark.asyncio
async def test_a_refused_cold_protect_connection_is_permission_denied_without_nvr_text(tmp_path, monkeypatch, caplog):
    """The real factory and ProtectConnectionManager; the SDK's bootstrap raises NotAuthorized (403)."""
    import types

    from uiprotect.exceptions import NotAuthorized
    from unifi_api.services.managers import ManagerFactory
    from unifi_core.protect.managers import connection_manager as pcm

    class RefusingClient:
        def __init__(self, **kwargs) -> None:
            self.session = kwargs.get("session")
            self.public_session = kwargs.get("public_api_session")

        async def update(self) -> None:
            raise NotAuthorized(
                f"Request failed: https://controller.invalid/bootstrap - Status: 403 - Reason: {PRIVATE}"
            )

        async def async_disconnect_ws(self) -> None:
            pass

        async def close_session(self) -> None:
            await self.session.close()
            await self.public_session.close()

    async def once(operation, **_):
        return await operation()

    monkeypatch.setattr(pcm, "ProtectApiClient", RefusingClient)
    monkeypatch.setattr(pcm, "retry_with_backoff", once)
    harness = await make_harness(tmp_path, monkeypatch)
    factory = harness.app.state.manager_factory
    factory.get_event_reader = types.MethodType(ManagerFactory.get_event_reader, factory)
    with caplog.at_level("DEBUG"):
        response = await harness.rest(PROTECT_PATH, lambda: None)
        gql = await harness.graphql(f"{{ protect {{ incidentEvidence({gql_args(harness.cid)}) {{ document }} }} }}")
    for document in (response.json()["data"], gql.json()["data"]["protect"]["incidentEvidence"]["document"]):
        check_document(document)
        assert document["sources"][0]["outcome"] == "permission_denied"
        assert document["sources"][0]["failure"] == {"kind": "permission_denied", "http_status": 403}
    assert PRIVATE not in response.text and PRIVATE not in gql.text
    assert all(PRIVATE not in record.getMessage() and not record.exc_info for record in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("product", ["network", "protect"])
async def test_undeclared_mapping_keys_are_never_echoed(tmp_path, monkeypatch, caplog, product):
    harness = await make_harness(tmp_path, monkeypatch)
    mapping = {
        "entity": {"kind": "network_device", "id_kind": "mac", "id": "aa:bb:cc:00:10:01", SENTINEL: "x"},
        "target": {"kind": "camera", "id_kind": "protect_camera_id", "id": "cam-fixture-000a"},
        "source": "operator_input",
    }
    path = NETWORK_PATH if product == "network" else PROTECT_PATH
    with caplog.at_level("DEBUG"):
        response = await harness.rest(path, lambda: None, mappings=json.dumps([mapping]))
        query = (
            "query Q($c: ID!, $s: String!, $e: String!, $m: JSON) "
            f"{{ {product} {{ incidentEvidence(controller: $c, start: $s, end: $e, mappings: $m) {{ document }} }} }}"
        )
        async with harness.client() as client:
            gql = await client.post(
                "/v1/graphql",
                headers=harness.headers,
                json={
                    "query": query,
                    "variables": {"c": harness.cid, "s": REQUEST["start"], "e": REQUEST["end"], "m": [mapping]},
                },
            )
    assert response.status_code == 422
    assert response.json()["detail"] == "mappings.0.entity: Extra inputs are not permitted"
    assert gql.json()["errors"][0]["message"] == "mappings.0.entity: Extra inputs are not permitted"
    assert gql.json()["errors"][0]["extensions"]["code"] == "BAD_REQUEST"
    assert SENTINEL not in response.text and SENTINEL not in gql.text
    assert all(SENTINEL not in record.getMessage() for record in caplog.records if record.name != "httpx")


@pytest.mark.asyncio
@pytest.mark.parametrize("product", ["network", "protect"])
async def test_rejected_inline_values_stay_out_of_graphql_logs(tmp_path, monkeypatch, caplog, product):
    harness = await make_harness(tmp_path, monkeypatch)
    arguments = f'start: "{SENTINEL}", end: "{REQUEST["end"]}", controller: "{harness.cid}"'
    query = f"{{ {product} {{ incidentEvidence({arguments}) {{ document }} }} }}"
    with caplog.at_level("DEBUG"):
        response = await harness.graphql(query)
    assert response.json()["errors"][0]["extensions"]["code"] == "BAD_REQUEST"
    assert SENTINEL not in response.text
    assert all(SENTINEL not in record.getMessage() and not record.exc_info for record in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("product", ["network", "protect"])
async def test_input_mentioning_scope_never_becomes_forbidden(tmp_path, monkeypatch, product):
    harness = await make_harness(tmp_path, monkeypatch)
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
                "variables": {
                    "c": harness.cid,
                    "s": REQUEST["start"],
                    "e": REQUEST["end"],
                    "m": "private-scope-sentinel",
                },
            },
        )
    assert gql.json()["errors"][0]["extensions"]["code"] == "BAD_REQUEST"
    assert "private-scope-sentinel" not in gql.text


@pytest.mark.asyncio
async def test_a_controller_without_the_product_is_refused_alike_on_rest_and_graphql(tmp_path, monkeypatch):
    harness = await make_harness(tmp_path, monkeypatch, products="network")
    response = await harness.rest(PROTECT_PATH, lambda: None)
    gql = await harness.graphql(f"{{ protect {{ incidentEvidence({gql_args(harness.cid)}) {{ document }} }} }}")
    assert response.status_code == 409 and response.json()["detail"]["kind"] == "capability_mismatch"
    error = gql.json()["errors"][0]
    assert error["extensions"]["code"] == "CAPABILITY_MISMATCH"
    assert error["message"] == "controller does not support protect"
    assert harness.calls == []
