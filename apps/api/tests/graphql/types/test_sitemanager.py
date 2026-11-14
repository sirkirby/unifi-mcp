"""Complete Core-field parity and null/zero/nested privacy for typed account projections."""

import copy

import pytest
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.sitemanager import devices as device_types
from unifi_api.graphql.types.sitemanager import hosts as host_types
from unifi_api.graphql.types.sitemanager import isp_metrics as metric_types
from unifi_api.graphql.types.sitemanager import sdwan as sdwan_types
from unifi_api.graphql.types.sitemanager import sites as site_types
from unifi_core.sitemanager.models import devices, hosts, isp_metrics, sdwan, sites

CASES = [
    (hosts.HostApplication(name="network", is_installed=False, is_running=True), host_types.SiteManagerHostApplication),
    (
        hosts.Host(
            id="synthetic-host",
            owner=False,
            registration_time=0,
            applications=[hosts.HostApplication(name="network")],
            reported_state={"api_key": "sensitive-value"},
        ),
        host_types.SiteManagerHost,
    ),
    (
        sites.Site(
            host_id="synthetic-host",
            site_id="synthetic-site",
            counts={"devices": 0},
            is_owner=False,
            wan_uptime_percent=0,
            gateway={"password": "sensitive-value"},
        ),
        site_types.SiteManagerSite,
    ),
    (
        devices.ManagedDevice(
            id="synthetic-device", startup_time=0, adoption_time="2026-01-01T00:00:00Z", is_console=False
        ),
        device_types.SiteManagerManagedDevice,
    ),
    (
        devices.HostDevices(
            host_id="synthetic-host", updated_at=0, devices=[devices.ManagedDevice(id="synthetic-device")]
        ),
        device_types.SiteManagerHostDevices,
    ),
    (isp_metrics.IspMetricPeriod(time=0, avg_latency_ms=0, download_kbps=0), metric_types.SiteManagerIspMetricPeriod),
    (
        isp_metrics.IspMetricSummary(period_count=1, first_time=0, avg_latency_ms=0),
        metric_types.SiteManagerIspMetricSummary,
    ),
    (
        isp_metrics.IspMetricSeries(
            site_id="synthetic-site",
            summary=isp_metrics.IspMetricSummary(period_count=1),
            periods=[isp_metrics.IspMetricPeriod(time=0)],
            periods_truncated=True,
        ),
        metric_types.SiteManagerIspMetricSeries,
    ),
    (sdwan.SdwanConfigSummary(id="synthetic-config", name="Synthetic"), sdwan_types.SiteManagerSdwanConfigSummary),
    (
        sdwan.SdwanConfig(
            id="synthetic-config", settings={"api_key": "sensitive-value"}, hubs=[{"password": "sensitive-value"}]
        ),
        sdwan_types.SiteManagerSdwanConfig,
    ),
    (
        sdwan.SdwanConfigStatus(id="synthetic-config", updated_at=0, errors=[{"password": "sensitive-value"}]),
        sdwan_types.SiteManagerSdwanConfigStatus,
    ),
]


@pytest.mark.parametrize("value,projection", CASES, ids=[case[1].__name__ for case in CASES])
def test_every_core_field_is_preserved_and_exported(value, projection):
    expected = copy.deepcopy(value.model_dump())
    result = projection.from_manager_output(value, redact_sensitive=False)
    assert result.to_dict() == expected
    assert set(result.to_dict()) == set(type(value).model_fields)
    assert set(to_pydantic_model(projection).model_fields) == set(type(value).model_fields)
    assert result is not value


@pytest.mark.parametrize("raw", [False, True])
def test_recursive_policy_is_applied_before_graphql_object_creation(raw):
    value = sdwan.SdwanConfigStatus(
        id="synthetic-config",
        errors=[{"password": "sensitive-value"}],
        hubs=[{"members": [{"api_key": "sensitive-value", "zero": 0}]}],
    )
    expected = "sensitive-value" if raw else "***REDACTED***"
    result = sdwan_types.SiteManagerSdwanConfigStatus.from_manager_output(value, redact_sensitive=not raw)
    assert result.errors == [{"password": expected}]
    assert result.hubs == [{"members": [{"api_key": expected, "zero": 0}]}]
    assert result.to_dict()["errors"] == [{"password": expected}]
    # Projection never edits the Core model that a second surface may use.
    assert value.errors == [{"password": "sensitive-value"}]
