"""Closed Site Manager data inputs validate without a transport."""

import pytest
from pydantic import ValidationError
from unifi_core.sitemanager.models.isp_metrics import (
    SiteManagerMetricsGetInput,
    SiteManagerMetricsQueryInput,
    SiteManagerMetricsSiteInput,
)
from unifi_core.sitemanager.models.reads import (
    SiteManagerConfigInput,
    SiteManagerDevicesInput,
    SiteManagerHostInput,
    SiteManagerPageInput,
)


@pytest.mark.parametrize("field", ["begin_timestamp", "end_timestamp"])
def test_site_range_endpoints_are_individually_optional(field):
    value = SiteManagerMetricsSiteInput(
        host_id="synthetic-host", site_id="synthetic-site", **{field: "2026-01-01T00:00:00Z"}
    )
    assert value.model_dump(exclude_none=True) == {
        "host_id": "synthetic-host",
        "site_id": "synthetic-site",
        field: "2026-01-01T00:00:00Z",
    }


@pytest.mark.parametrize(
    "sites",
    [
        [],
        [None],
        ["bad"],
        [{"host_id": "synthetic-host"}],
        [{"host_id": "synthetic-host", "site_id": "synthetic-site", "duration": "7d"}],
        [{"host_id": "synthetic-host", "site_id": "synthetic-site", "typo": "KEY-SENTINEL-REJECTED"}],
        [{"host_id": "synthetic-host", "site_id": "synthetic-site"}] * 51,
    ],
)
def test_query_sites_reject_unknown_missing_and_unbounded_inputs(sites):
    with pytest.raises(ValidationError) as error:
        SiteManagerMetricsQueryInput(sites=sites)
    assert "KEY-SENTINEL-REJECTED" not in str(error.value)


@pytest.mark.parametrize(
    "args",
    [
        {"metric_type": "bad"},
        {"period_limit": True},
        {"period_limit": -1},
        {"period_limit": 721},
        {"metric_type": "5m", "duration": "30d"},
        {"begin_timestamp": "2026-01-01T00:00:00Z"},
        {"begin_timestamp": "2026-01-01", "end_timestamp": "2026-01-02"},
        {"duration": "7d", "begin_timestamp": "2026-01-01T00:00:00Z", "end_timestamp": "2026-01-02T00:00:00Z"},
    ],
)
def test_get_window_constraints_are_checked(args):
    with pytest.raises(ValidationError):
        SiteManagerMetricsGetInput.model_validate(args)


def test_defaults_zero_periods_and_cursor_preserve_values():
    assert SiteManagerMetricsGetInput().model_dump(exclude_none=True) == {"metric_type": "1h", "period_limit": 12}
    assert SiteManagerMetricsGetInput(period_limit=0).period_limit == 0
    cursor = " opaque:+/%=\u2603 "
    assert SiteManagerPageInput(page_size=500, cursor=cursor).cursor == cursor
    value = SiteManagerDevicesInput(host_ids=["synthetic-two", "synthetic-one"], updated_since="2026-01-01T00:00:00Z")
    assert value.host_ids == ["synthetic-two", "synthetic-one"]


@pytest.mark.parametrize(
    ("model", "args"),
    [
        (SiteManagerPageInput, {"cursor": " "}),
        (SiteManagerDevicesInput, {"updated_since": "SENTINEL-not-a-timestamp"}),
        (SiteManagerHostInput, {"host_id": "SENTINEL/../escape"}),
        (SiteManagerConfigInput, {"config_id": "SENTINEL/../escape"}),
        (
            SiteManagerMetricsGetInput,
            {"begin_timestamp": "SENTINEL-not-a-timestamp", "end_timestamp": "2026-01-02T00:00:00Z"},
        ),
    ],
)
def test_core_argument_checks_surface_as_value_free_pydantic_errors(model, args):
    with pytest.raises(ValidationError) as error:
        model.model_validate(args)
    assert "SENTINEL" not in str(error.value)
