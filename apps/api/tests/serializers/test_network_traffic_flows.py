"""Network traffic-flow type unit tests.

Mirrors the ``ClientSession`` / ``ClientSessionPage`` pattern: the
``TrafficFlow`` / ``TrafficFlowEndpoint`` / ``TrafficFlowPage`` Strawberry
types map from the dict shape ``TrafficFlowManager.get_traffic_flows()``
emits and expose a ``to_dict()`` dict contract for the REST routes.
"""

from unifi_api.graphql.types.network.traffic_flow import (
    TrafficFlow,
    TrafficFlowEndpoint,
    TrafficFlowPage,
)


def test_from_manager_output_maps_core_fields() -> None:
    raw = {
        "id": "f1",
        "action": "Allow",
        "risk": "low",
        "service": "HTTPS",
        "bytes_total": 1234,
        "source": {"name": "Lab-Laptop", "mac": "aa:bb:cc:00:00:01"},
        "destination": {"domains": ["example.com"], "ip": "203.0.113.5"},
    }
    tf = TrafficFlow.from_manager_output(raw)
    assert tf.id == "f1"
    assert tf.action == "Allow"
    assert tf.bytes_total == 1234
    assert tf.source.name == "Lab-Laptop"
    assert tf.destination.domains == ["example.com"]
    d = tf.to_dict()
    assert d["id"] == "f1" and "source" in d


def test_to_dict_nests_endpoints() -> None:
    raw = {
        "id": "f2",
        "source": {
            "name": "AP-Office",
            "mac": "aa:bb:cc:00:00:02",
            "ip": "10.0.0.5",
            "network_name": "LAN",
            "zone_name": "Internal",
            "domains": [],
        },
        "destination": {
            "name": "ext",
            "ip": "203.0.113.9",
            "domains": ["example.com"],
        },
    }
    d = TrafficFlow.from_manager_output(raw).to_dict()
    assert isinstance(d["source"], dict)
    assert d["source"]["network_name"] == "LAN"
    assert d["source"]["zone_name"] == "Internal"
    assert d["destination"]["domains"] == ["example.com"]


def test_endpoint_handles_missing_fields() -> None:
    ep = TrafficFlowEndpoint.from_manager_output({})
    assert ep.name is None
    assert ep.domains == []
    none_ep = TrafficFlowEndpoint.from_manager_output(None)
    assert none_ep.name is None
    assert none_ep.domains == []


def test_render_hint() -> None:
    hint = TrafficFlow.render_hint("list")
    assert hint == {
        "kind": "list",
        "primary_key": "id",
        "display_columns": [
            "time",
            "source",
            "destination",
            "service",
            "risk",
            "action",
        ],
        "sort_default": "time:desc",
    }


def test_traffic_flow_page() -> None:
    raw = {"id": "f3", "source": {}, "destination": {}}
    page = TrafficFlowPage(items=[TrafficFlow.from_manager_output(raw)])
    assert page.next_cursor is None
    assert page.items[0].id == "f3"
