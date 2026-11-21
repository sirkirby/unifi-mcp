"""Public read view for Matter/Thread clients (``shape_thread_client_list``)."""

import copy

import pytest
from unifi_core.network.read_views import (
    THREAD_CLIENT_FIELDS,
    shape_thread_client_list,
    thread_client_from_controller,
)

# Shape verified against a Network 11.0 V2 /clients/active?includeMatterThreadClients=true
# record (values replaced with test data).
THREAD_RECORD = {
    "type": "MATTER_THREAD",
    "id": "abc1234",
    "name": "Smart Plug",
    "display_name": "Smart Plug",
    "model_name": "Plug 20EBO8301",
    "status": "online",
    "first_seen": 1700000000,
    "last_seen": 1700000600,
    "ipv6_address": ["fd00:db8::1", "fe80::1"],
    "network_name": "TestNet",
    "network_id": "0011223344556677",
    "channel": 25,
    "signal": -72,
    "last_rssi": -73,
    "uplink_id": "aa:bb:cc:00:00:10",
    "uplink_name": "Thread Parent",
    "uplink_tbr_mac": "aa:bb:cc:00:00:10",
    "uplink_tbr_name": "Thread Parent",
    "matter": {
        "status": "COMMISSIONED",
        "basic_info": {"vendor_name": "Example Vendor", "product_name": "Plug", "serial_number": "SECRET-SN"},
        "fabrics": [{"fabric_id": "SECRET-FABRIC"}],
    },
}

EXPECTED_SHAPE = {
    "thread_client_id": "abc1234",
    "name": "Smart Plug",
    "model": "Plug 20EBO8301",
    "vendor": "Example Vendor",
    "connection_type": "Thread",
    "status": "online",
    "matter_status": "COMMISSIONED",
    "first_seen": "2023-11-14T22:13:20+00:00",
    "last_seen": "2023-11-14T22:23:20+00:00",
    "ipv6_addresses": ["fd00:db8::1", "fe80::1"],
    "thread_network_name": "TestNet",
    "thread_network_id": "0011223344556677",
    "channel": 25,
    "signal_dbm": -72,
    "parent_mac": "aa:bb:cc:00:00:10",
    "parent_name": "Thread Parent",
    "border_router_mac": "aa:bb:cc:00:00:10",
    "border_router_name": "Thread Parent",
}


def test_thread_client_shape_omits_serials_and_fabric_internals():
    shaped = thread_client_from_controller(copy.deepcopy(THREAD_RECORD))

    assert shaped == EXPECTED_SHAPE
    assert set(shaped) <= set(THREAD_CLIENT_FIELDS)
    assert "SECRET" not in str(shaped)


def test_thread_client_shape_falls_back_and_drops_unknown_values():
    raw = {"type": "MATTER_THREAD", "id": "x1", "display_name": "Sensor", "last_rssi": -80, "ipv6_address": "bad"}

    assert thread_client_from_controller(raw) == {
        "thread_client_id": "x1",
        "name": "Sensor",
        "connection_type": "Thread",
        "signal_dbm": -80,
    }


def test_thread_client_list_envelope():
    result = shape_thread_client_list([copy.deepcopy(THREAD_RECORD)], site="default")

    assert result["success"] is True
    assert result["site"] == "default"
    assert result["filter_type"] == "thread"
    assert result["total_count"] == 1
    assert result["returned_count"] == 1
    assert result["count"] == 1
    assert result["clients"] == [EXPECTED_SHAPE]
    assert "MAC-based client tools" in result["note"]
    assert "unknown_fields" not in result


@pytest.mark.parametrize(
    "kwargs,expected_total,expected_returned",
    [
        ({"search": "fd00:db8"}, 1, 1),
        ({"search": "example vendor"}, 1, 1),
        ({"search": "nomatch"}, 0, 0),
        ({"limit": 0}, 1, 0),
    ],
)
def test_thread_client_list_search_and_limit(kwargs, expected_total, expected_returned):
    result = shape_thread_client_list([copy.deepcopy(THREAD_RECORD)], site="default", **kwargs)

    assert result["total_count"] == expected_total
    assert result["returned_count"] == expected_returned
    assert len(result["clients"]) == expected_returned


def test_thread_client_list_fields_projection_reports_unknown():
    result = shape_thread_client_list([copy.deepcopy(THREAD_RECORD)], site="default", fields="name, channel,bogus")

    assert len(result["clients"]) == 1
    assert result["clients"][0] == {"name": "Smart Plug", "channel": 25}
    assert result["unknown_fields"] == ["bogus"]
