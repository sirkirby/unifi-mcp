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
    assert "region" not in flow.destination.model_dump()


def test_endpoint_name_falls_back_to_host_name():
    flow = traffic_flow_from_controller({"source": {"host_name": "fallback-host"}})
    assert flow.source.name == "fallback-host"


def test_trafficflow_fields_marked_immutable():
    from unifi_core.network.models.traffic_flows import TrafficFlow, TrafficFlowEndpoint

    for model in (TrafficFlow, TrafficFlowEndpoint):
        for name, field in model.model_fields.items():
            extra = field.json_schema_extra or {}
            assert extra.get("mutable") is False, f"{model.__name__}.{name} missing mutable:False"
