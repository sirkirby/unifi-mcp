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


# ---------------------------------------------------------------------------
# TrafficFlowStatistics
# ---------------------------------------------------------------------------

_STATS_MANAGER_OUTPUT = {
    "allowed_count_by_risk": {"low": 103, "medium": 2},
    "blocked_count_by_risk": {"low": 7},
    "allowed_count_by_region_by_risk": {"US": {"low": 98, "medium": 2}},
    "all_count_by_region": {"US": 100},
    "blocked_count_by_region": {"US": 7},
    "top_clients": [{"count": 500, "client_mac": "aa:bb:cc:00:00:01", "client_name": "Lab-Laptop"}],
    "top_blocked_clients": [{"count": 7, "client_mac": "aa:bb:cc:00:00:02", "client_name": "Blocked-Host"}],
    "top_destinations": [{"count": 200, "destination": "example.test", "most_frequent_region": "US"}],
    "top_applications": [
        {"application_id": 470, "category_id": 4, "bytes": 999, "application_name": None, "category_name": None}
    ],
    "top_blocked_policies": [
        {"count": 7, "policy_id": "p1", "policy_name": "Region Blocking", "policy_type": "PROTECTION"}
    ],
}


def test_statistics_from_manager_output_maps_fields() -> None:
    from unifi_api.graphql.types.network.traffic_flow import TrafficFlowStatistics

    stats = TrafficFlowStatistics.from_manager_output(_STATS_MANAGER_OUTPUT)
    d = stats.to_dict()
    assert d["allowed_count_by_risk"] == {"low": 103, "medium": 2}
    assert d["allowed_count_by_region_by_risk"]["US"] == {"low": 98, "medium": 2}
    assert d["top_clients"][0] == {"count": 500, "client_mac": "aa:bb:cc:00:00:01", "client_name": "Lab-Laptop"}
    assert d["top_destinations"][0]["most_frequent_region"] == "US"
    assert d["top_blocked_policies"][0]["policy_name"] == "Region Blocking"


def test_statistics_top_application_name_nullable() -> None:
    from unifi_api.graphql.types.network.traffic_flow import TrafficFlowStatistics

    app = TrafficFlowStatistics.from_manager_output(_STATS_MANAGER_OUTPUT).to_dict()["top_applications"][0]
    assert app["application_id"] == 470
    assert app["category_id"] == 4
    assert app["bytes"] == 999
    assert app["application_name"] is None
    assert app["category_name"] is None


def test_statistics_render_hint() -> None:
    from unifi_api.graphql.types.network.traffic_flow import TrafficFlowStatistics

    assert TrafficFlowStatistics.render_hint("detail") == {"kind": "detail"}


def test_statistics_handles_empty() -> None:
    from unifi_api.graphql.types.network.traffic_flow import TrafficFlowStatistics

    d = TrafficFlowStatistics.from_manager_output({}).to_dict()
    assert d["allowed_count_by_risk"] == {}
    assert d["top_clients"] == []
    assert d["top_applications"] == []
