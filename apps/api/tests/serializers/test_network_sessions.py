"""Network sessions / wifi-details type unit tests.

Phase 6 PR2 Task 23 migrated both projections to Strawberry types in
``unifi_api.graphql.types.network.session``. The legacy serializer-shape
contract (dict → dict for sessions; ``None`` → ``{}`` for wifi details)
is preserved by ``ClientSession.to_dict()`` and ``ClientWifiDetails.to_dict()``.
"""

from unifi_api.graphql.types.network.session import (
    ClientSession,
    ClientWifiDetails,
)


def test_client_sessions_list_serializer_shape() -> None:
    sample = {
        "mac": "aa:bb:cc:dd:ee:ff",
        "hostname": "laptop",
        "ap_mac": "11:22:33:44:55:66",
        "essid": "MyWiFi",
        "assoc_time": 1714000000,
        "disassoc_time": 1714003600,
        "duration": 3600,
    }
    item = ClientSession.from_manager_output(sample).to_dict()
    assert item["mac"] == "aa:bb:cc:dd:ee:ff"
    assert item["hostname"] == "laptop"
    assert item["ap"] == "11:22:33:44:55:66"
    assert item["ssid"] == "MyWiFi"
    assert item["connected_at"] == 1714000000
    assert item["disconnected_at"] == 1714003600
    assert item["duration"] == 3600
    assert ClientSession.render_hint("list")["kind"] == "list"


def test_client_wifi_details_detail_serializer_shape() -> None:
    sample = {
        "mac": "aa:bb:cc:dd:ee:ff",
        "essid": "MyWiFi",
        "ap_mac": "11:22:33:44:55:66",
        "signal": -55,
        "tx_rate": 866000,
        "rx_rate": 433000,
        "channel": 36,
        "noise": -95,
        "satisfaction": 98,
        "tx_retries": 12,
        "wifi_tx_attempts": 900,
        "roam_count": 2,
        "radio": "na",
        "bssid": "11:22:33:44:55:77",
        "nss": 2,
        "is_11r": False,
    }
    out = ClientWifiDetails.from_manager_output(sample).to_dict()
    assert out["mac"] == "aa:bb:cc:dd:ee:ff"
    assert out["ssid"] == "MyWiFi"
    assert out["ap"] == "11:22:33:44:55:66"
    assert out["signal"] == -55
    assert out["tx_rate"] == 866000
    assert out["rx_rate"] == 433000
    assert out["channel"] == 36
    assert {key: out[key] for key in sample if key not in ("mac", "essid", "ap_mac")} == {
        key: value for key, value in sample.items() if key not in ("mac", "essid", "ap_mac")
    }
    assert ClientWifiDetails.render_hint("detail")["kind"] == "detail"


def test_client_wifi_details_handles_none() -> None:
    out = ClientWifiDetails.from_manager_output(None).to_dict()
    assert out == {}
