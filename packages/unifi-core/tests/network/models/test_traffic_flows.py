"""Tests for Network Traffic Flows models (TrafficFlowQuery + serializer)."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from unifi_core.network.models.traffic_flows import (
    TrafficFlowQuery,
    traffic_flow_from_controller,
)

# package-local fixture: models -> network (parents[1]) -> fixtures/
_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "traffic_flows_response.json"


def _first_record():
    return json.loads(_FIXTURE.read_text())["data"][0]


def test_query_defaults_and_filters():
    q = TrafficFlowQuery(time_from=1, time_to=2, destination_domain=["x.test"])
    assert q.page_number == 0
    assert q.page_size == 100
    assert q.destination_domain == ["x.test"]
    assert q.source_mac is None
    assert q.search_text is None


def test_query_rejects_out_of_range_pagination():
    for kwargs in ({"page_size": 0}, {"page_size": 1001}, {"page_number": -1}):
        with pytest.raises(ValidationError):
            TrafficFlowQuery(time_from=1, time_to=2, **kwargs)


def test_serializer_maps_core_and_traffic_data():
    flow = traffic_flow_from_controller(_first_record())
    assert flow.id == "flow-0001"
    assert flow.action == "ALLOW"
    assert flow.risk == "low"
    assert flow.source.name == "Lab-Laptop"
    assert flow.source.mac == "aa:bb:cc:00:00:01"
    assert flow.destination.domains == ["example.test"]
    assert flow.bytes_total == 10731
    assert flow.bytes_rx == 8421
    assert flow.bytes_tx == 2310
    assert flow.flow_start_time == 1779742800000
    assert flow.time == 1779742801200
    # This recorded record has no region; the manager's dump must not invent one.
    assert "region" not in flow.destination.model_dump(exclude_none=True)


def test_query_accepts_port_filters_and_rejects_out_of_range():
    q = TrafficFlowQuery(time_from=1, time_to=2, source_port=[51514], destination_port=[443, 7680])
    assert q.source_port == [51514]
    assert q.destination_port == [443, 7680]
    for kwargs in ({"source_port": [-1]}, {"destination_port": [65536]}):
        with pytest.raises(ValidationError):
            TrafficFlowQuery(time_from=1, time_to=2, **kwargs)


def test_serializer_maps_endpoint_ports():
    flow = traffic_flow_from_controller(_first_record())
    assert flow.source.port == 51514
    assert flow.destination.port == 443


@pytest.mark.parametrize("raw_port", [None, "", "443", True, -1, 65536, 1.5])
def test_serializer_drops_malformed_port(raw_port):
    flow = traffic_flow_from_controller({"destination": {"ip": "203.0.113.20", "port": raw_port}})
    assert flow.destination.port is None
    assert flow.destination.ip == "203.0.113.20"
    assert "port" not in flow.model_dump(exclude_none=True)["destination"]


def test_serializer_keeps_port_zero():
    flow = traffic_flow_from_controller({"source": {"port": 0}})
    assert flow.source.port == 0


def test_endpoint_name_falls_back_to_host_name():
    flow = traffic_flow_from_controller({"source": {"host_name": "fallback-host"}})
    assert flow.source.name == "fallback-host"


def test_trafficflow_fields_marked_immutable():
    from unifi_core.network.models.traffic_flows import TrafficFlow, TrafficFlowEndpoint

    for model in (TrafficFlow, TrafficFlowEndpoint):
        for name, field in model.model_fields.items():
            extra = field.json_schema_extra or {}
            assert extra.get("mutable") is False, f"{model.__name__}.{name} missing mutable:False"


# ---------------------------------------------------------------------------
# TrafficFlowStatistics (Insights > Flows "Flow Summary" — latest-statistics)
# ---------------------------------------------------------------------------

# Mirrors the live v2 /traffic-flow-latest-statistics response shape with
# synthetic data (no real identifiers). Risk keys are low/medium/high; the
# top_* arrays drop the UI-only client_fingerprint/icon_* noise.
_RAW_STATS = {
    "all_count_by_region": {"US": 100, "DE": 5},
    "allowed_count_by_region_by_risk": {"US": {"low": 98, "medium": 2}, "DE": {"low": 5}},
    "allowed_count_by_risk": {"low": 103, "medium": 2},
    "blocked_count_by_region": {"US": 7},
    "blocked_count_by_risk": {"low": 7},
    "top_all_count_by_client": [
        {
            "count": 500,
            "client_mac": "aa:bb:cc:00:00:01",
            "client_name": "Lab-Laptop",
            "client_fingerprint": {"dev_id": 1, "dev_vendor": 7},
            "icon_filename": None,
            "icon_resolutions": None,
        }
    ],
    "top_all_count_by_destination": [{"count": 200, "destination": "example.test", "mostFrequentRegion": "US"}],
    "top_all_traffic_by_application": [{"application_id": 470, "bytes": 123456789, "category_id": 4}],
    "top_blocked_count_by_client": [{"count": 7, "client_mac": "aa:bb:cc:00:00:02", "client_name": "Blocked-Host"}],
    "top_blocked_count_by_policy": [
        {"count": 7, "policy_id": "pol-1", "policy_name": "Region Blocking", "policy_type": "PROTECTION"}
    ],
}


def test_statistics_maps_count_breakdowns():
    from unifi_core.network.models.traffic_flows import traffic_flow_statistics_from_controller

    stats = traffic_flow_statistics_from_controller(_RAW_STATS)
    assert stats.allowed_count_by_risk == {"low": 103, "medium": 2}
    assert stats.blocked_count_by_risk == {"low": 7}
    assert stats.all_count_by_region == {"US": 100, "DE": 5}
    assert stats.blocked_count_by_region == {"US": 7}
    assert stats.allowed_count_by_region_by_risk["US"] == {"low": 98, "medium": 2}


def test_statistics_maps_top_clients_dropping_fingerprint_and_icon():
    from unifi_core.network.models.traffic_flows import traffic_flow_statistics_from_controller

    stats = traffic_flow_statistics_from_controller(_RAW_STATS)
    assert len(stats.top_clients) == 1
    client = stats.top_clients[0]
    assert client.count == 500
    assert client.client_mac == "aa:bb:cc:00:00:01"
    assert client.client_name == "Lab-Laptop"
    # The UI-only fingerprint/icon fields are not projected.
    dumped = client.model_dump()
    assert "client_fingerprint" not in dumped
    assert "icon_filename" not in dumped
    assert set(dumped) == {"count", "client_mac", "client_name"}


def test_statistics_maps_top_destinations_camel_to_snake():
    from unifi_core.network.models.traffic_flows import traffic_flow_statistics_from_controller

    stats = traffic_flow_statistics_from_controller(_RAW_STATS)
    dest = stats.top_destinations[0]
    assert dest.count == 200
    assert dest.destination == "example.test"
    assert dest.most_frequent_region == "US"


def test_statistics_top_applications_carry_ids_and_nullable_names():
    from unifi_core.network.models.traffic_flows import traffic_flow_statistics_from_controller

    stats = traffic_flow_statistics_from_controller(_RAW_STATS)
    app = stats.top_applications[0]
    assert app.application_id == 470
    assert app.category_id == 4
    assert app.bytes == 123456789
    # Name resolution is deferred (PR-B / DPI catalog) — fields exist but default None.
    assert app.application_name is None
    assert app.category_name is None


def test_statistics_maps_blocked_clients_and_policies():
    from unifi_core.network.models.traffic_flows import traffic_flow_statistics_from_controller

    stats = traffic_flow_statistics_from_controller(_RAW_STATS)
    assert stats.top_blocked_clients[0].client_name == "Blocked-Host"
    policy = stats.top_blocked_policies[0]
    assert policy.policy_id == "pol-1"
    assert policy.policy_name == "Region Blocking"
    assert policy.policy_type == "PROTECTION"


def test_statistics_handles_empty_response():
    from unifi_core.network.models.traffic_flows import traffic_flow_statistics_from_controller

    stats = traffic_flow_statistics_from_controller({})
    assert stats.allowed_count_by_risk == {}
    assert stats.top_clients == []
    assert stats.top_applications == []
    assert stats.top_blocked_policies == []


def test_statistics_skips_null_region_subentry():
    # A firmware edge case can send a null per-region sub-entry; it must not crash.
    from unifi_core.network.models.traffic_flows import traffic_flow_statistics_from_controller

    stats = traffic_flow_statistics_from_controller({"allowed_count_by_region_by_risk": {"US": {"low": 5}, "DE": None}})
    assert stats.allowed_count_by_region_by_risk == {"US": {"low": 5}}


def test_endpoints_carry_the_region():
    flow = traffic_flow_from_controller({"source": {"region": "DE"}, "destination": {"region": "US"}})
    assert (flow.source.region, flow.destination.region) == ("DE", "US")
    blank = traffic_flow_from_controller({"source": {"region": ""}, "destination": {"region": 7}})
    assert (blank.source.region, blank.destination.region) == (None, None)


def test_destination_region_filter_matches_the_controllers_uppercase_codes():
    # A lowercase code returns 200 with zero flows.
    query = TrafficFlowQuery(time_from=1, time_to=2, destination_region=["us", "De"])
    assert query.destination_region == ["US", "DE"]


def test_filters_that_match_nothing_by_spelling_are_normalized():
    query = TrafficFlowQuery(
        time_from=1, time_to=2, destination_region=[" nl "], destination_domain=[" WWW.Example.Test "], service=[" DNS"]
    )
    assert query.destination_region == ["NL"]
    assert query.destination_domain == ["www.example.test"]
    assert query.service == ["DNS"]


_LIST_FILTERS = [name for name, field in TrafficFlowQuery.model_fields.items() if "list[" in str(field.annotation)]


@pytest.mark.parametrize("name", _LIST_FILTERS)
def test_an_empty_filter_is_refused_not_dropped(name):
    with pytest.raises(ValidationError):
        TrafficFlowQuery(time_from=1, time_to=2, **{name: []})


@pytest.mark.parametrize("name", [name for name in _LIST_FILTERS if not name.endswith("_port")])
@pytest.mark.parametrize("value", ["", "  "])
def test_a_blank_filter_value_is_refused(name, value):
    with pytest.raises(ValidationError):
        TrafficFlowQuery(time_from=1, time_to=2, **{name: [value]})


@pytest.mark.parametrize(
    "policies,domains,expected",
    [
        (["x", None, {"type": "FIREWALL"}], ["a.test", None, 7], ([{"type": "FIREWALL"}], ["a.test"])),
        ({"a": 1}, "a.test", ([], [])),
    ],
)
def test_malformed_entries_do_not_fail_the_page(policies, domains, expected):
    flow = traffic_flow_from_controller({"policies": policies, "destination": {"domains": domains}})
    assert (flow.policies, flow.destination.domains) == expected
