"""Field models for Network Traffic Flows (private v2 /traffic-flows endpoint).

Read-only. Contains:
- ``TrafficFlowQuery``               — typed query input (maps to the v2 request body)
- ``TrafficFlowEndpoint``            — a source/destination endpoint in a flow
- ``TrafficFlow``                    — a normalized flow record
- ``traffic_flow_from_controller``   — raw → TrafficFlow factory

No create/update/delete tools exist (read-only); MUTABLE_FIELDS = frozenset().
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class TrafficFlowQuery(BaseModel):
    """Typed inputs for a traffic-flows query (maps to the v2 request body).

    Intentional typed-input model for the wide (~16-field) filter surface;
    upstream managers usually take plain kwargs — this is a deliberate exception.
    """

    time_from: Optional[int] = Field(default=None, description="Window start (epoch ms)")
    time_to: Optional[int] = Field(default=None, description="Window end (epoch ms)")
    page_number: int = Field(default=0, ge=0, description="0-based page number")
    page_size: int = Field(default=100, ge=1, le=1000, description="Rows per page (1-1000)")
    search_text: Optional[str] = Field(default=None, description="Substring match")
    risk: Optional[list[str]] = Field(default=None, description="Filter by risk band (low/medium/high)")
    action: Optional[list[str]] = Field(default=None, description="Filter by action (allowed/blocked)")
    direction: Optional[list[str]] = Field(default=None, description="Filter by direction")
    protocol: Optional[list[str]] = Field(default=None, description="Filter by transport protocol")
    service: Optional[list[str]] = Field(default=None, description="Filter by service")
    source_mac: Optional[list[str]] = Field(default=None, description="Filter by source MAC")
    source_ip: Optional[list[str]] = Field(default=None, description="Filter by source IP")
    source_host: Optional[list[str]] = Field(default=None, description="Filter by source host/client name")
    source_network_id: Optional[list[str]] = Field(default=None, description="Filter by source network id")
    destination_domain: Optional[list[str]] = Field(default=None, description="Filter by destination domain")
    destination_ip: Optional[list[str]] = Field(default=None, description="Filter by destination IP")
    destination_region: Optional[list[str]] = Field(default=None, description="Filter by destination region")


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


class TrafficFlowEndpoint(BaseModel):
    """A source or destination endpoint of a flow."""

    name: Optional[str] = Field(default=None, description="Client or host name", json_schema_extra={"mutable": False})
    mac: Optional[str] = Field(
        default=None, description="MAC address (LAN endpoints)", json_schema_extra={"mutable": False}
    )
    ip: Optional[str] = Field(default=None, description="IP address", json_schema_extra={"mutable": False})
    network_name: Optional[str] = Field(
        default=None, description="Network/VLAN name", json_schema_extra={"mutable": False}
    )
    zone_name: Optional[str] = Field(
        default=None, description="Firewall zone name", json_schema_extra={"mutable": False}
    )
    domains: list[str] = Field(
        default_factory=list, description="Resolved domains (destination)", json_schema_extra={"mutable": False}
    )


class TrafficFlow(BaseModel):
    """A single completed traffic flow."""

    id: Optional[str] = Field(default=None, description="Flow record ID", json_schema_extra={"mutable": False})
    action: Optional[str] = Field(
        default=None, description="Action taken (allowed/blocked)", json_schema_extra={"mutable": False}
    )
    risk: Optional[str] = Field(default=None, description="Risk classification", json_schema_extra={"mutable": False})
    service: Optional[str] = Field(
        default=None, description="Service (HTTPS/DNS/...)", json_schema_extra={"mutable": False}
    )
    protocol: Optional[str] = Field(
        default=None, description="Transport protocol", json_schema_extra={"mutable": False}
    )
    direction: Optional[str] = Field(default=None, description="Flow direction", json_schema_extra={"mutable": False})
    count: Optional[int] = Field(
        default=None, description="Aggregated session count", json_schema_extra={"mutable": False}
    )
    duration_milliseconds: Optional[int] = Field(
        default=None, description="Flow duration (ms)", json_schema_extra={"mutable": False}
    )
    time: Optional[int] = Field(
        default=None, description="Record timestamp (epoch ms)", json_schema_extra={"mutable": False}
    )
    flow_start_time: Optional[int] = Field(
        default=None, description="Flow start (epoch ms)", json_schema_extra={"mutable": False}
    )
    flow_end_time: Optional[int] = Field(
        default=None, description="Flow end (epoch ms)", json_schema_extra={"mutable": False}
    )
    bytes_total: Optional[int] = Field(default=None, description="Total bytes", json_schema_extra={"mutable": False})
    bytes_rx: Optional[int] = Field(default=None, description="Bytes received", json_schema_extra={"mutable": False})
    bytes_tx: Optional[int] = Field(default=None, description="Bytes transmitted", json_schema_extra={"mutable": False})
    source: TrafficFlowEndpoint = Field(default_factory=TrafficFlowEndpoint, json_schema_extra={"mutable": False})
    destination: TrafficFlowEndpoint = Field(default_factory=TrafficFlowEndpoint, json_schema_extra={"mutable": False})
    policies: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Matched policies (raw controller dicts; schema may vary by firmware)",
        json_schema_extra={"mutable": False},
    )


def _endpoint_from_controller(raw: Any) -> TrafficFlowEndpoint:
    name = _get(raw, "client_name") or _get(raw, "host_name")
    return TrafficFlowEndpoint(
        name=name or None,
        mac=_get(raw, "mac") or None,
        ip=_get(raw, "ip") or None,
        network_name=_get(raw, "network_name") or None,
        zone_name=_get(raw, "zone_name") or None,
        domains=list(_get(raw, "domains", []) or []),
    )


def traffic_flow_from_controller(obj: Any) -> TrafficFlow:
    """Normalise a raw flow record into a TrafficFlow."""
    td = _get(obj, "traffic_data", {}) or {}
    return TrafficFlow(
        id=_get(obj, "id"),
        action=_get(obj, "action"),
        risk=_get(obj, "risk"),
        service=_get(obj, "service"),
        protocol=_get(obj, "protocol"),
        direction=_get(obj, "direction"),
        count=_get(obj, "count"),
        duration_milliseconds=_get(obj, "duration_milliseconds"),
        time=_get(obj, "time"),
        flow_start_time=_get(obj, "flow_start_time"),
        flow_end_time=_get(obj, "flow_end_time"),
        bytes_total=_get(td, "bytes_total"),
        bytes_rx=_get(td, "bytes_rx"),
        bytes_tx=_get(td, "bytes_tx"),
        source=_endpoint_from_controller(_get(obj, "source", {}) or {}),
        destination=_endpoint_from_controller(_get(obj, "destination", {}) or {}),
        policies=list(_get(obj, "policies", []) or []),
    )


TRAFFICFLOW_MUTABLE_FIELDS: frozenset[str] = frozenset()
TRAFFICFLOW_READ_ONLY_FIELDS: frozenset[str] = frozenset(TrafficFlow.model_fields.keys())
# Alias required by the model-symmetry test harness — pattern used by all read-only models
MUTABLE_FIELDS = TRAFFICFLOW_MUTABLE_FIELDS


# ---------------------------------------------------------------------------
# Traffic-flow statistics (Insights > Flows "Flow Summary")
#
# Read shape of the private v2 /traffic-flow-latest-statistics endpoint: risk
# and region count breakdowns plus Top-Talker rankings (clients, destinations,
# applications, blocked clients, blocked policies). Read-only.
# ---------------------------------------------------------------------------


class TrafficFlowTopClient(BaseModel):
    """A client in a Top-Talkers ranking (by flow count)."""

    count: Optional[int] = Field(default=None, description="Flow count", json_schema_extra={"mutable": False})
    client_mac: Optional[str] = Field(
        default=None, description="Client MAC address", json_schema_extra={"mutable": False}
    )
    client_name: Optional[str] = Field(
        default=None, description="Client display name", json_schema_extra={"mutable": False}
    )


class TrafficFlowTopDestination(BaseModel):
    """A destination in a Top-Talkers ranking (by flow count)."""

    count: Optional[int] = Field(default=None, description="Flow count", json_schema_extra={"mutable": False})
    destination: Optional[str] = Field(
        default=None, description="Destination domain or IP", json_schema_extra={"mutable": False}
    )
    most_frequent_region: Optional[str] = Field(
        default=None,
        description="Most frequent destination region (country code)",
        json_schema_extra={"mutable": False},
    )


class TrafficFlowTopApplication(BaseModel):
    """An application in a Top-Talkers ranking (by bytes).

    ``application_id``/``category_id`` are DPI catalog ids; ``application_name``/
    ``category_name`` are resolved via the DPI catalog and are null when the
    catalog does not cover the application.
    """

    application_id: Optional[int] = Field(
        default=None, description="DPI application id", json_schema_extra={"mutable": False}
    )
    category_id: Optional[int] = Field(
        default=None, description="DPI category id", json_schema_extra={"mutable": False}
    )
    bytes: Optional[int] = Field(default=None, description="Total bytes", json_schema_extra={"mutable": False})
    application_name: Optional[str] = Field(
        default=None,
        description="Resolved DPI application name (null when unresolved)",
        json_schema_extra={"mutable": False},
    )
    category_name: Optional[str] = Field(
        default=None,
        description="Resolved DPI category name (null when unresolved)",
        json_schema_extra={"mutable": False},
    )


class TrafficFlowTopPolicy(BaseModel):
    """A firewall/protection policy in a blocked-flow ranking (by flow count)."""

    count: Optional[int] = Field(default=None, description="Blocked-flow count", json_schema_extra={"mutable": False})
    policy_id: Optional[str] = Field(default=None, description="Policy id", json_schema_extra={"mutable": False})
    policy_name: Optional[str] = Field(default=None, description="Policy name", json_schema_extra={"mutable": False})
    policy_type: Optional[str] = Field(default=None, description="Policy type", json_schema_extra={"mutable": False})


class TrafficFlowStatistics(BaseModel):
    """Aggregated Insights > Flows summary (v2 /traffic-flow-latest-statistics).

    Risk keys are ``low``/``medium``/``high`` (the UI surfaces these as Low /
    Suspicious / Concerning). Region keys are ISO country codes.
    """

    allowed_count_by_risk: dict[str, int] = Field(
        default_factory=dict, description="Allowed flow counts by risk band", json_schema_extra={"mutable": False}
    )
    blocked_count_by_risk: dict[str, int] = Field(
        default_factory=dict, description="Blocked flow counts by risk band", json_schema_extra={"mutable": False}
    )
    allowed_count_by_region_by_risk: dict[str, dict[str, int]] = Field(
        default_factory=dict,
        description="Allowed flow counts by region then risk band",
        json_schema_extra={"mutable": False},
    )
    all_count_by_region: dict[str, int] = Field(
        default_factory=dict, description="All flow counts by region", json_schema_extra={"mutable": False}
    )
    blocked_count_by_region: dict[str, int] = Field(
        default_factory=dict, description="Blocked flow counts by region", json_schema_extra={"mutable": False}
    )
    top_clients: list[TrafficFlowTopClient] = Field(
        default_factory=list, description="Top clients by flow count", json_schema_extra={"mutable": False}
    )
    top_blocked_clients: list[TrafficFlowTopClient] = Field(
        default_factory=list, description="Top blocked clients by flow count", json_schema_extra={"mutable": False}
    )
    top_destinations: list[TrafficFlowTopDestination] = Field(
        default_factory=list, description="Top destinations by flow count", json_schema_extra={"mutable": False}
    )
    top_applications: list[TrafficFlowTopApplication] = Field(
        default_factory=list, description="Top applications by bytes", json_schema_extra={"mutable": False}
    )
    top_blocked_policies: list[TrafficFlowTopPolicy] = Field(
        default_factory=list,
        description="Top blocking policies by blocked-flow count",
        json_schema_extra={"mutable": False},
    )


def _top_client_from_controller(raw: Any) -> TrafficFlowTopClient:
    return TrafficFlowTopClient(
        count=_get(raw, "count"),
        client_mac=_get(raw, "client_mac"),
        client_name=_get(raw, "client_name"),
    )


def _top_destination_from_controller(raw: Any) -> TrafficFlowTopDestination:
    region = _get(raw, "mostFrequentRegion")
    if region is None:
        region = _get(raw, "most_frequent_region")
    return TrafficFlowTopDestination(
        count=_get(raw, "count"),
        destination=_get(raw, "destination"),
        most_frequent_region=region,
    )


def _top_application_from_controller(raw: Any) -> TrafficFlowTopApplication:
    # Name fields are intentionally left None here; DPI-catalog resolution of
    # application_id/category_id is a separate concern layered on top.
    return TrafficFlowTopApplication(
        application_id=_get(raw, "application_id"),
        category_id=_get(raw, "category_id"),
        bytes=_get(raw, "bytes"),
    )


def _top_policy_from_controller(raw: Any) -> TrafficFlowTopPolicy:
    return TrafficFlowTopPolicy(
        count=_get(raw, "count"),
        policy_id=_get(raw, "policy_id"),
        policy_name=_get(raw, "policy_name"),
        policy_type=_get(raw, "policy_type"),
    )


def traffic_flow_statistics_from_controller(obj: Any) -> TrafficFlowStatistics:
    """Normalise a raw /traffic-flow-latest-statistics response into the model."""

    def _region_by_risk(raw: Any) -> dict[str, dict[str, int]]:
        # Guard each sub-entry: a firmware edge case can send {"US": null}.
        return {
            k: dict(v)
            for k, v in (_get(raw, "allowed_count_by_region_by_risk", {}) or {}).items()
            if isinstance(v, dict)
        }

    return TrafficFlowStatistics(
        allowed_count_by_risk=dict(_get(obj, "allowed_count_by_risk", {}) or {}),
        blocked_count_by_risk=dict(_get(obj, "blocked_count_by_risk", {}) or {}),
        allowed_count_by_region_by_risk=_region_by_risk(obj),
        all_count_by_region=dict(_get(obj, "all_count_by_region", {}) or {}),
        blocked_count_by_region=dict(_get(obj, "blocked_count_by_region", {}) or {}),
        top_clients=[_top_client_from_controller(c) for c in (_get(obj, "top_all_count_by_client", []) or [])],
        top_blocked_clients=[
            _top_client_from_controller(c) for c in (_get(obj, "top_blocked_count_by_client", []) or [])
        ],
        top_destinations=[
            _top_destination_from_controller(d) for d in (_get(obj, "top_all_count_by_destination", []) or [])
        ],
        top_applications=[
            _top_application_from_controller(a) for a in (_get(obj, "top_all_traffic_by_application", []) or [])
        ],
        top_blocked_policies=[
            _top_policy_from_controller(p) for p in (_get(obj, "top_blocked_count_by_policy", []) or [])
        ],
    )
