"""Tests for TrafficFlowManager — caching, validation, and response shaping."""

import copy
from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.exceptions import UniFiAuthError
from unifi_core.network.managers.traffic_flow_manager import TrafficFlowManager
from unifi_core.network.models.traffic_flows import TrafficFlowQuery

_EMPTY_RESPONSE = {
    "data": [],
    "total_element_count": 0,
    "total_page_count": 1,
    "has_next": False,
    "or_more": False,
    "page_number": 0,
}


def _make_connection(response=None):
    """Build a MagicMock connection with a real in-process cache store."""
    store: dict = {}
    conn = MagicMock()
    conn.site = "default"
    conn.request = AsyncMock(return_value=response if response is not None else _EMPTY_RESPONSE)
    conn.get_cached = lambda key, timeout=None: store.get(key)
    conn._update_cache = lambda key, data, timeout=None: store.update({key: data})
    return conn


# ---------------------------------------------------------------------------
# A. Caching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_identical_query_is_cached_within_ttl():
    """Second call with the same query must NOT issue a second controller request."""
    conn = _make_connection()
    mgr = TrafficFlowManager(conn)
    q = TrafficFlowQuery(time_from=1, time_to=2, page_number=0, page_size=100)

    await mgr.get_traffic_flows(q)
    await mgr.get_traffic_flows(q)

    assert conn.request.await_count == 1


# ---------------------------------------------------------------------------
# B. Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_time_window_raises():
    """get_traffic_flows must raise ValueError when time_from or time_to is absent."""
    conn = _make_connection()
    mgr = TrafficFlowManager(conn)

    with pytest.raises(ValueError, match="time_from and time_to are required"):
        await mgr.get_traffic_flows(TrafficFlowQuery(page_number=0, page_size=100))


def test_port_filters_are_sent_and_default_to_empty():
    mgr = TrafficFlowManager(_make_connection())

    body = mgr._build_body(TrafficFlowQuery(time_from=1, time_to=2, destination_port=[7680]))
    assert body["destination_port"] == [7680]
    assert body["source_port"] == []

    body = mgr._build_body(TrafficFlowQuery(time_from=1, time_to=2, source_port=[51514]))
    assert body["source_port"] == [51514]
    assert body["destination_port"] == []


def test_body_field_set_is_unchanged_by_port_filters():
    mgr = TrafficFlowManager(_make_connection())
    plain = mgr._build_body(TrafficFlowQuery(time_from=1, time_to=2))
    filtered = mgr._build_body(TrafficFlowQuery(time_from=1, time_to=2, source_port=[1], destination_port=[2]))
    assert plain.keys() == filtered.keys()
    assert {"source_port", "destination_port"} <= plain.keys()


# ---------------------------------------------------------------------------
# C. Response shaping — empty and malformed inputs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handles_empty_and_nondict_response():
    """Both {} and [{}] responses must yield flows==[] and total_element_count==0."""
    for raw in ({}, [{}]):
        conn = _make_connection(response=raw)
        mgr = TrafficFlowManager(conn)
        result = await mgr.get_traffic_flows(TrafficFlowQuery(time_from=1, time_to=2, page_number=0, page_size=100))
        assert result["flows"] == [], f"Expected empty flows for response {raw!r}"
        assert result["total_element_count"] == 0, f"Expected 0 for response {raw!r}"


# ---------------------------------------------------------------------------
# D. get_traffic_flow_statistics (latest-statistics)
# ---------------------------------------------------------------------------

_STATS_RESPONSE = {
    "allowed_count_by_risk": {"low": 103, "medium": 2},
    "blocked_count_by_risk": {"low": 7},
    "all_count_by_region": {"US": 100},
    "top_all_count_by_client": [{"count": 500, "client_mac": "aa:bb:cc:00:00:01", "client_name": "Lab-Laptop"}],
    "top_all_count_by_destination": [{"count": 200, "destination": "example.test", "mostFrequentRegion": "US"}],
    "top_all_traffic_by_application": [{"application_id": 470, "bytes": 999, "category_id": 4}],
    "top_blocked_count_by_policy": [
        {"count": 7, "policy_id": "p1", "policy_name": "Region Blocking", "policy_type": "PROTECTION"}
    ],
}


@pytest.mark.asyncio
async def test_statistics_rejects_invalid_period():
    conn = _make_connection(response=_STATS_RESPONSE)
    mgr = TrafficFlowManager(conn)
    with pytest.raises(ValueError, match="period must be one of"):
        await mgr.get_traffic_flow_statistics(period="YEAR")
    # The controller must not have been called for an invalid period.
    assert conn.request.await_count == 0


@pytest.mark.asyncio
async def test_statistics_builds_period_and_top_query():
    conn = _make_connection(response=_STATS_RESPONSE)
    mgr = TrafficFlowManager(conn)
    await mgr.get_traffic_flow_statistics(period="day", top=5)
    api_request = conn.request.await_args.args[0]
    assert api_request.method == "get"
    assert api_request.path == "/traffic-flow-latest-statistics?period=DAY&top=5"


@pytest.mark.asyncio
async def test_statistics_shapes_response():
    conn = _make_connection(response=_STATS_RESPONSE)
    mgr = TrafficFlowManager(conn)
    result = await mgr.get_traffic_flow_statistics(period="DAY", top=30)
    assert result["allowed_count_by_risk"] == {"low": 103, "medium": 2}
    assert result["top_clients"][0]["client_name"] == "Lab-Laptop"
    assert result["top_destinations"][0]["most_frequent_region"] == "US"
    assert result["top_applications"][0]["application_id"] == 470
    assert result["top_applications"][0]["application_name"] is None
    assert result["top_blocked_policies"][0]["policy_name"] == "Region Blocking"
    assert result["dpi_name_resolution"] == {
        "status": "unavailable",
        "resolved_count": 0,
        "total_count": 1,
        "reason": "dpi_catalogue_unavailable",
        "remediation": "The DPI catalogue could not be read; retry later. IDs and byte counts are complete.",
    }


@pytest.mark.asyncio
async def test_statistics_enriches_names_without_changing_v2_values():
    class DpiCatalog:
        async def get_full_dpi_catalog(self):
            return {
                "applications": [{"id": (4 << 16) | 470, "name": "Example Stream"}],
                "categories": [{"id": 4, "name": "Media streaming services"}],
            }

    conn = _make_connection(response=_STATS_RESPONSE)
    mgr = TrafficFlowManager(conn, dpi_manager=DpiCatalog())

    result = await mgr.get_traffic_flow_statistics(period="DAY", top=30)

    assert result["top_applications"] == [
        {
            "application_id": 470,
            "category_id": 4,
            "bytes": 999,
            "application_name": "Example Stream",
            "category_name": "Media streaming services",
        }
    ]
    assert result["dpi_name_resolution"] == {
        "status": "resolved",
        "resolved_count": 1,
        "total_count": 1,
        "reason": None,
        "remediation": None,
    }


@pytest.mark.asyncio
async def test_statistics_catalog_failure_is_best_effort_and_cached():
    class FailingDpiCatalog:
        def __init__(self):
            self.calls = 0

        async def get_full_dpi_catalog(self):
            self.calls += 1
            raise RuntimeError("API key unavailable")

    conn = _make_connection(response=_STATS_RESPONSE)
    dpi_catalog = FailingDpiCatalog()
    mgr = TrafficFlowManager(conn, dpi_manager=dpi_catalog)

    first = await mgr.get_traffic_flow_statistics(period="DAY", top=30)
    second = await mgr.get_traffic_flow_statistics(period="DAY", top=30)

    assert first == second
    assert first["top_applications"] == [
        {
            "application_id": 470,
            "category_id": 4,
            "bytes": 999,
            "application_name": None,
            "category_name": None,
        }
    ]
    assert conn.request.await_count == 1
    assert dpi_catalog.calls == 1
    assert first["dpi_name_resolution"]["status"] == "unavailable"
    assert first["dpi_name_resolution"]["reason"] == "dpi_catalogue_unavailable"
    assert "API key unavailable" not in str(first)


@pytest.mark.asyncio
async def test_statistics_missing_api_key_reports_remediation():
    class NoKeyDpiCatalog:
        async def get_full_dpi_catalog(self):
            raise UniFiAuthError("no Network API key configured")

    conn = _make_connection(response=_STATS_RESPONSE)
    conn.tls_env_prefix = "NETWORK"
    mgr = TrafficFlowManager(conn, dpi_manager=NoKeyDpiCatalog())

    result = await mgr.get_traffic_flow_statistics(period="DAY", top=30)

    assert result["top_applications"][0]["application_name"] is None
    assert result["top_applications"][0]["application_id"] == 470
    assert result["dpi_name_resolution"] == {
        "status": "unavailable",
        "resolved_count": 0,
        "total_count": 1,
        "reason": "network_api_key_required",
        "remediation": (
            "Set UNIFI_NETWORK_API_KEY (or UNIFI_API_KEY on the UNIFI_HOST console) to a valid Network API key "
            "so the DPI catalogue "
            "can be read; application/category IDs and byte counts are complete without it."
        ),
    }


@pytest.mark.asyncio
async def test_statistics_without_applications_reports_no_resolution():
    response = dict(_STATS_RESPONSE)
    response["top_all_traffic_by_application"] = []

    class UnusedDpiCatalog:
        async def get_full_dpi_catalog(self):  # pragma: no cover - must not be called
            raise AssertionError("catalogue read without applications")

    for dpi_manager in (None, UnusedDpiCatalog()):
        conn = _make_connection(response=response)
        result = await TrafficFlowManager(conn, dpi_manager=dpi_manager).get_traffic_flow_statistics(
            period="DAY", top=30
        )
        assert result["top_applications"] == []
        assert result["dpi_name_resolution"] is None


@pytest.mark.asyncio
async def test_statistics_preserves_order_and_resolves_partial_catalog_matches():
    response = dict(_STATS_RESPONSE)
    response["top_all_traffic_by_application"] = [
        {"application_id": 470, "bytes": 999, "category_id": 4},
        {"application_id": 471, "bytes": 500, "category_id": 5},
        {"application_id": 472, "bytes": 250, "category_id": 6},
    ]

    class PartialDpiCatalog:
        async def get_full_dpi_catalog(self):
            return {
                "applications": [{"id": (4 << 16) | 470, "name": "Application only"}],
                "categories": [{"id": 5, "name": "Category only"}],
            }

    conn = _make_connection(response=response)
    mgr = TrafficFlowManager(conn, dpi_manager=PartialDpiCatalog())

    result = await mgr.get_traffic_flow_statistics(period="DAY", top=30)

    assert result["top_applications"] == [
        {
            "application_id": 470,
            "category_id": 4,
            "bytes": 999,
            "application_name": "Application only",
            "category_name": None,
        },
        {
            "application_id": 471,
            "category_id": 5,
            "bytes": 500,
            "application_name": None,
            "category_name": "Category only",
        },
        {
            "application_id": 472,
            "category_id": 6,
            "bytes": 250,
            "application_name": None,
            "category_name": None,
        },
    ]
    # No entry has both names, but some names were found.
    assert result["dpi_name_resolution"] == {
        "status": "partial",
        "resolved_count": 0,
        "total_count": 3,
        "reason": "not_in_dpi_catalogue",
        "remediation": (
            "The controller's public DPI catalogue does not list these applications; IDs and byte counts are complete."
        ),
    }


@pytest.mark.asyncio
async def test_statistics_ignores_boolean_catalog_ids():
    class MalformedDpiCatalog:
        async def get_full_dpi_catalog(self):
            return {
                "applications": [{"id": True, "name": "Not application one"}],
                "categories": [{"id": True, "name": "Not category one"}],
            }

    response = dict(_STATS_RESPONSE)
    response["top_all_traffic_by_application"] = [
        {"application_id": 1, "bytes": 999, "category_id": 0},
        {"application_id": 470, "bytes": 500, "category_id": 1},
    ]
    conn = _make_connection(response=response)
    mgr = TrafficFlowManager(conn, dpi_manager=MalformedDpiCatalog())

    result = await mgr.get_traffic_flow_statistics(period="DAY", top=30)

    assert result["top_applications"][0]["application_name"] is None
    assert result["top_applications"][1]["category_name"] is None
    assert result["dpi_name_resolution"]["status"] == "unresolved"
    assert result["dpi_name_resolution"]["resolved_count"] == 0


@pytest.mark.asyncio
async def test_statistics_is_cached_within_ttl():
    conn = _make_connection(response=_STATS_RESPONSE)
    mgr = TrafficFlowManager(conn)
    await mgr.get_traffic_flow_statistics(period="DAY", top=10)
    await mgr.get_traffic_flow_statistics(period="DAY", top=10)
    assert conn.request.await_count == 1


@pytest.mark.asyncio
async def test_statistics_handles_list_wrapped_and_empty():
    for raw in ([_STATS_RESPONSE], [{}], {}):
        conn = _make_connection(response=raw)
        mgr = TrafficFlowManager(conn)
        result = await mgr.get_traffic_flow_statistics(period="HOUR", top=10)
        assert isinstance(result["top_clients"], list)
        assert isinstance(result["allowed_count_by_risk"], dict)


@pytest.mark.asyncio
async def test_statistics_missing_api_key_without_env_prefix_names_the_controller_record():
    """A caller without server env vars (the API server) is told to fix the controller record."""

    class NoKeyDpiCatalog:
        async def get_full_dpi_catalog(self):
            raise UniFiAuthError("no Network API key configured")

    conn = _make_connection(response=_STATS_RESPONSE)
    conn.tls_env_prefix = None
    mgr = TrafficFlowManager(conn, dpi_manager=NoKeyDpiCatalog())

    result = await mgr.get_traffic_flow_statistics(period="DAY", top=30)

    resolution = result["dpi_name_resolution"]
    assert resolution["reason"] == "network_api_key_required"
    assert "this controller's configuration" in resolution["remediation"]
    assert "UNIFI_" not in resolution["remediation"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "catalog,expected_names",
    [
        (
            {"applications": [{"id": (4 << 16) | 470, "name": "Example Stream"}], "categories": []},
            ("Example Stream", None),
        ),
        (
            {"applications": [], "categories": [{"id": 4, "name": "Media streaming services"}]},
            (None, "Media streaming services"),
        ),
    ],
    ids=["application-only", "category-only"],
)
async def test_statistics_single_name_match_is_partial_not_resolved(catalog, expected_names):
    class OneSidedDpiCatalog:
        async def get_full_dpi_catalog(self):
            return copy.deepcopy(catalog)

    conn = _make_connection(response=_STATS_RESPONSE)
    mgr = TrafficFlowManager(conn, dpi_manager=OneSidedDpiCatalog())

    result = await mgr.get_traffic_flow_statistics(period="DAY", top=30)

    assert len(result["top_applications"]) == 1
    application = result["top_applications"][0]
    assert (application["application_name"], application["category_name"]) == expected_names
    assert application["application_id"] == 470
    assert result["dpi_name_resolution"] == {
        "status": "partial",
        "resolved_count": 0,
        "total_count": 1,
        "reason": "not_in_dpi_catalogue",
        "remediation": (
            "The controller's public DPI catalogue does not list these applications; IDs and byte counts are complete."
        ),
    }
