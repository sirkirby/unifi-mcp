"""Network stats cluster type unit tests.

Phase 6 PR2 Task 23 migrated the TIMESERIES projection to ``StatPoint`` and
the DPI DETAIL wrapper to ``DpiStats`` at
``unifi_api.graphql.types.network.stat``.
"""

from unifi_api.graphql.types.network.stat import DpiStats, StatPoint

# ---- TIMESERIES (list-returning manager methods) ----


def test_timeseries_serializer_normalizes_seconds_to_ms() -> None:
    sample = [
        {"time": 1714000000, "rx_bytes": 1024, "tx_bytes": 2048},
        {"time": 1714000300, "rx_bytes": 4096, "tx_bytes": 8192},
    ]
    rows = [StatPoint.from_manager_output(p).to_dict() for p in sample]
    hint = StatPoint.render_hint("timeseries")
    assert hint["kind"] == "timeseries"
    assert hint["sort_default"] == "ts:desc"
    assert rows[0]["ts"] == 1714000000 * 1000
    assert rows[0]["rx_bytes"] == 1024
    assert rows[1]["ts"] == 1714000300 * 1000
    assert "time" not in rows[0]


def test_timeseries_serializer_passes_ms_through() -> None:
    sample = [{"ts": 1714000000123, "wan_rx": 100}]
    rows = [StatPoint.from_manager_output(p).to_dict() for p in sample]
    assert rows[0]["ts"] == 1714000000123
    assert rows[0]["wan_rx"] == 100


def test_timeseries_handles_non_dict_input() -> None:
    out = StatPoint.from_manager_output("not-a-dict").to_dict()
    assert out == {"ts": 0}


# ---- DETAIL — DPI stats wrapper shape ----


def test_dpi_stats_detail_wrapper_shape() -> None:
    sample = {
        "applications": [{"name": "Netflix"}],
        "categories": [{"name": "Streaming"}],
    }
    out = DpiStats.from_manager_output(sample).to_dict()
    assert DpiStats.render_hint("detail")["kind"] == "detail"
    assert out["applications"][0]["name"] == "Netflix"
    assert out["categories"][0]["name"] == "Streaming"


def test_dpi_stats_handles_empty_or_missing_keys() -> None:
    out = DpiStats.from_manager_output({}).to_dict()
    assert out == {"applications": [], "categories": []}


def test_dpi_stats_unwraps_raw_attribute_objects() -> None:
    class _Wrap:
        def __init__(self, raw):
            self.raw = raw

    sample = {
        "applications": [_Wrap({"name": "Spotify"})],
        "categories": [],
    }
    out = DpiStats.from_manager_output(sample).to_dict()
    assert out["applications"][0]["name"] == "Spotify"
