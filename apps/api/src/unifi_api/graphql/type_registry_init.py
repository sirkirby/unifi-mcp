"""Construct and populate the Phase 6 type_registry.

The type_registry is the projection oracle for every read tool/resource
across network/protect/access. It's instantiated and populated here so
both the FastAPI app factory (server.py) and the test harness can build
the same fully-loaded registry from a single source.
"""

from __future__ import annotations

from unifi_api.graphql.type_registry import TypeRegistry
from unifi_api.graphql.types.access.credentials import (
    Credential as AccessCredentialType,
)
from unifi_api.graphql.types.access.devices import (
    AccessDevice as AccessDeviceType,
)
from unifi_api.graphql.types.access.doors import (
    Door as AccessDoorType,
    DoorGroup as AccessDoorGroupType,
    DoorStatus as AccessDoorStatusType,
)
from unifi_api.graphql.types.access.events import (
    ActivitySummary as AccessActivitySummaryType,
    Event as AccessEventType,
)
from unifi_api.graphql.types.access.policies import (
    Policy as AccessPolicyType,
)
from unifi_api.graphql.types.access.schedules import (
    Schedule as AccessScheduleType,
)
from unifi_api.graphql.types.access.system import (
    AccessHealth as AccessHealthType,
    AccessSystemInfo as AccessSystemInfoType,
)
from unifi_api.graphql.types.access.users import (
    User as AccessUserType,
)
from unifi_api.graphql.types.access.visitors import (
    Visitor as AccessVisitorType,
)
from unifi_api.graphql.types.network.acl import (
    AclRule as NetworkAclRuleType,
)
from unifi_api.graphql.types.network.ap_group import (
    ApGroup as NetworkApGroupType,
)
from unifi_api.graphql.types.network.client import (
    BlockedClient as NetworkBlockedClientType,
    Client as NetworkClientType,
    ClientLookup as NetworkClientLookupType,
)
from unifi_api.graphql.types.network.client_group import (
    ClientGroup as NetworkClientGroupType,
    UserGroup as NetworkUserGroupType,
)
from unifi_api.graphql.types.network.content_filter import (
    ContentFilter as NetworkContentFilterType,
)
from unifi_api.graphql.types.network.device import (
    AvailableChannel as NetworkAvailableChannelType,
    Device as NetworkDeviceType,
    DeviceRadio as NetworkDeviceRadioType,
    LldpNeighbors as NetworkLldpNeighborsType,
    PduOutlets as NetworkPduOutletsType,
    RfScanResult as NetworkRfScanResultType,
    RogueAp as NetworkRogueApType,
    SpeedtestStatus as NetworkSpeedtestStatusType,
)
from unifi_api.graphql.types.network.dns import (
    DnsRecord as NetworkDnsRecordType,
)
from unifi_api.graphql.types.network.dpi import (
    DpiApplication as NetworkDpiApplicationType,
    DpiCategory as NetworkDpiCategoryType,
)
from unifi_api.graphql.types.network.event import (
    EventLog as NetworkEventLogType,
)
from unifi_api.graphql.types.network.firewall import (
    FirewallGroup as NetworkFirewallGroupType,
    FirewallRule as NetworkFirewallRuleType,
    FirewallZone as NetworkFirewallZoneType,
)
from unifi_api.graphql.types.network.network import (
    Network as NetworkNetworkType,
)
from unifi_api.graphql.types.network.oon import (
    OonPolicy as NetworkOonPolicyType,
)
from unifi_api.graphql.types.network.port_forward import (
    PortForward as NetworkPortForwardType,
)
from unifi_api.graphql.types.network.qos import (
    QosRule as NetworkQosRuleType,
)
from unifi_api.graphql.types.network.route import (
    ActiveRoute as NetworkActiveRouteType,
    Route as NetworkRouteType,
    TrafficRoute as NetworkTrafficRouteType,
)
from unifi_api.graphql.types.network.session import (
    ClientSession as NetworkClientSessionType,
    ClientWifiDetails as NetworkClientWifiDetailsType,
)
from unifi_api.graphql.types.network.stat import (
    DpiStats as NetworkDpiStatsType,
    StatPoint as NetworkStatPointType,
)
from unifi_api.graphql.types.network.switch import (
    PortProfile as NetworkPortProfileType,
    PortStats as NetworkPortStatsType,
    SwitchCapabilities as NetworkSwitchCapabilitiesType,
    SwitchPorts as NetworkSwitchPortsType,
)
from unifi_api.graphql.types.network.system import (
    Alarm as NetworkAlarmType,
    AutoBackupSettings as NetworkAutoBackupSettingsType,
    Backup as NetworkBackupType,
    EventTypes as NetworkEventTypesType,
    NetworkHealth as NetworkNetworkHealthType,
    SiteSettings as NetworkSiteSettingsType,
    SnmpSettings as NetworkSnmpSettingsType,
    SpeedtestResult as NetworkSpeedtestResultType,
    SystemInfo as NetworkSystemInfoType,
    TopClient as NetworkTopClientType,
)
from unifi_api.graphql.types.network.voucher import (
    Voucher as NetworkVoucherType,
)
from unifi_api.graphql.types.network.vpn import (
    VpnClient as NetworkVpnClientType,
    VpnServer as NetworkVpnServerType,
)
from unifi_api.graphql.types.network.wlan import (
    Wlan as NetworkWlanType,
)
from unifi_api.graphql.types.protect.alarms import (
    AlarmProfileList as ProtectAlarmProfileListType,
    AlarmStatus as ProtectAlarmStatusType,
)
from unifi_api.graphql.types.protect.cameras import (
    Camera as ProtectCameraType,
    CameraAnalytics as ProtectCameraAnalyticsType,
    CameraStreams as ProtectCameraStreamsType,
    Snapshot as ProtectSnapshotType,
)
from unifi_api.graphql.types.protect.chimes import (
    Chime as ProtectChimeType,
)
from unifi_api.graphql.types.protect.events import (
    Event as ProtectEventType,
    EventThumbnail as ProtectEventThumbnailType,
    SmartDetection as ProtectSmartDetectionType,
)
from unifi_api.graphql.types.protect.lights import (
    Light as ProtectLightType,
)
from unifi_api.graphql.types.protect.liveviews import (
    Liveview as ProtectLiveviewType,
)
from unifi_api.graphql.types.protect.recordings import (
    Recording as ProtectRecordingType,
    RecordingStatusList as ProtectRecordingStatusListType,
)
from unifi_api.graphql.types.protect.sensors import (
    Sensor as ProtectSensorType,
)
from unifi_api.graphql.types.protect.system import (
    FirmwareStatus as ProtectFirmwareStatusType,
    ProtectHealth as ProtectHealthType,
    ProtectSystemInfo as ProtectSystemInfoType,
    Viewer as ProtectViewerType,
    ViewerList as ProtectViewerListType,
)


def build_type_registry() -> TypeRegistry:
    """Construct a TypeRegistry pre-populated with every Phase 6 read
    tool + resource projection across network / protect / access.
    """
    reg = TypeRegistry()

    # network/clients
    reg.register_type("network", "clients", NetworkClientType)
    reg.register_type("network", "clients/{mac}", NetworkClientType)
    reg.register_type("network", "blocked_clients", NetworkBlockedClientType)
    reg.register_type("network", "client_lookup", NetworkClientLookupType)
    reg.register_tool_type("unifi_list_clients", NetworkClientType, "list")
    reg.register_tool_type("unifi_get_client_details", NetworkClientType, "detail")
    reg.register_tool_type(
        "unifi_list_blocked_clients", NetworkBlockedClientType, "list",
    )
    reg.register_tool_type("unifi_lookup_by_ip", NetworkClientLookupType, "detail")

    # network/devices
    reg.register_type("network", "devices", NetworkDeviceType)
    reg.register_type("network", "devices/{mac}", NetworkDeviceType)
    reg.register_tool_type("unifi_list_devices", NetworkDeviceType, "list")
    reg.register_tool_type("unifi_get_device_details", NetworkDeviceType, "detail")
    reg.register_tool_type("unifi_get_device_radio", NetworkDeviceRadioType, "detail")
    reg.register_tool_type(
        "unifi_get_lldp_neighbors", NetworkLldpNeighborsType, "detail",
    )
    reg.register_tool_type("unifi_list_rogue_aps", NetworkRogueApType, "list")
    reg.register_tool_type("unifi_get_rf_scan_results", NetworkRfScanResultType, "list")
    reg.register_tool_type(
        "unifi_list_available_channels", NetworkAvailableChannelType, "list",
    )
    reg.register_tool_type(
        "unifi_get_speedtest_status", NetworkSpeedtestStatusType, "detail",
    )
    reg.register_tool_type("unifi_get_pdu_outlets", NetworkPduOutletsType, "detail")

    # network/networks
    reg.register_type("network", "networks", NetworkNetworkType)
    reg.register_type("network", "networks/{id}", NetworkNetworkType)
    reg.register_tool_type("unifi_list_networks", NetworkNetworkType, "list")
    reg.register_tool_type("unifi_get_network_details", NetworkNetworkType, "detail")

    # network/wlans
    reg.register_type("network", "wlans", NetworkWlanType)
    reg.register_type("network", "wlans/{id}", NetworkWlanType)
    reg.register_tool_type("unifi_list_wlans", NetworkWlanType, "list")
    reg.register_tool_type("unifi_get_wlan_details", NetworkWlanType, "detail")

    # network/vpn (tool-keyed only)
    reg.register_tool_type("unifi_list_vpn_clients", NetworkVpnClientType, "list")
    reg.register_tool_type(
        "unifi_get_vpn_client_details", NetworkVpnClientType, "detail",
    )
    reg.register_tool_type("unifi_list_vpn_servers", NetworkVpnServerType, "list")
    reg.register_tool_type(
        "unifi_get_vpn_server_details", NetworkVpnServerType, "detail",
    )

    # network/dns (tool-keyed only)
    reg.register_tool_type("unifi_list_dns_records", NetworkDnsRecordType, "list")
    reg.register_tool_type(
        "unifi_get_dns_record_details", NetworkDnsRecordType, "detail",
    )

    # network/routes (tool-keyed only)
    reg.register_tool_type("unifi_list_routes", NetworkRouteType, "list")
    reg.register_tool_type("unifi_get_route_details", NetworkRouteType, "detail")
    reg.register_tool_type("unifi_list_active_routes", NetworkActiveRouteType, "list")
    reg.register_tool_type("unifi_list_traffic_routes", NetworkTrafficRouteType, "list")
    reg.register_tool_type(
        "unifi_get_traffic_route_details", NetworkTrafficRouteType, "detail",
    )

    # network/firewall (rules + groups + zones)
    reg.register_type("network", "firewall/rules", NetworkFirewallRuleType)
    reg.register_type("network", "firewall/rules/{id}", NetworkFirewallRuleType)
    reg.register_tool_type(
        "unifi_list_firewall_policies", NetworkFirewallRuleType, "list",
    )
    reg.register_tool_type(
        "unifi_get_firewall_policy_details", NetworkFirewallRuleType, "detail",
    )
    reg.register_tool_type(
        "unifi_list_firewall_groups", NetworkFirewallGroupType, "list",
    )
    reg.register_tool_type(
        "unifi_get_firewall_group_details", NetworkFirewallGroupType, "detail",
    )
    reg.register_tool_type(
        "unifi_list_firewall_zones", NetworkFirewallZoneType, "list",
    )

    # network/qos (tool-keyed only)
    reg.register_tool_type("unifi_list_qos_rules", NetworkQosRuleType, "list")
    reg.register_tool_type("unifi_get_qos_rule_details", NetworkQosRuleType, "detail")

    # network/dpi (tool-keyed only)
    reg.register_tool_type(
        "unifi_list_dpi_applications", NetworkDpiApplicationType, "list",
    )
    reg.register_tool_type(
        "unifi_list_dpi_categories", NetworkDpiCategoryType, "list",
    )

    # network/content_filter (tool-keyed only)
    reg.register_tool_type(
        "unifi_list_content_filters", NetworkContentFilterType, "list",
    )
    reg.register_tool_type(
        "unifi_get_content_filter_details", NetworkContentFilterType, "detail",
    )

    # network/acl (tool-keyed only)
    reg.register_tool_type("unifi_list_acl_rules", NetworkAclRuleType, "list")
    reg.register_tool_type(
        "unifi_get_acl_rule_details", NetworkAclRuleType, "detail",
    )

    # network/oon (tool-keyed only)
    reg.register_tool_type("unifi_list_oon_policies", NetworkOonPolicyType, "list")
    reg.register_tool_type(
        "unifi_get_oon_policy_details", NetworkOonPolicyType, "detail",
    )

    # network/port_forwards (tool-keyed only)
    reg.register_tool_type(
        "unifi_list_port_forwards", NetworkPortForwardType, "list",
    )
    reg.register_tool_type("unifi_get_port_forward", NetworkPortForwardType, "detail")

    # network/vouchers (tool-keyed only)
    reg.register_tool_type("unifi_list_vouchers", NetworkVoucherType, "list")
    reg.register_tool_type("unifi_get_voucher_details", NetworkVoucherType, "detail")

    # network/sessions (tool-keyed only)
    reg.register_tool_type(
        "unifi_get_client_sessions", NetworkClientSessionType, "list",
    )
    reg.register_tool_type(
        "unifi_get_client_wifi_details", NetworkClientWifiDetailsType, "detail",
    )

    # network/stats (multi-kind: timeseries + detail)
    for _stats_tool in (
        "unifi_get_dashboard",
        "unifi_get_network_stats",
        "unifi_get_gateway_stats",
        "unifi_get_client_dpi_traffic",
        "unifi_get_site_dpi_traffic",
        "unifi_get_device_stats",
        "unifi_get_client_stats",
    ):
        reg.register_tool_type(_stats_tool, NetworkStatPointType, "timeseries")
    reg.register_tool_type("unifi_get_dpi_stats", NetworkDpiStatsType, "detail")

    # network/events (tool-keyed only)
    reg.register_tool_type("unifi_list_events", NetworkEventLogType, "event_log")
    reg.register_tool_type("unifi_get_alerts", NetworkEventLogType, "event_log")
    reg.register_tool_type("unifi_get_anomalies", NetworkEventLogType, "event_log")
    reg.register_tool_type("unifi_get_ips_events", NetworkEventLogType, "event_log")

    # network/system (tool-keyed only — 9 read shapes + speedtest_results)
    reg.register_tool_type("unifi_list_alarms", NetworkAlarmType, "list")
    reg.register_tool_type("unifi_list_backups", NetworkBackupType, "list")
    reg.register_tool_type("unifi_get_system_info", NetworkSystemInfoType, "detail")
    reg.register_tool_type(
        "unifi_get_network_health", NetworkNetworkHealthType, "list",
    )
    reg.register_tool_type("unifi_get_site_settings", NetworkSiteSettingsType, "detail")
    reg.register_tool_type("unifi_get_snmp_settings", NetworkSnmpSettingsType, "detail")
    reg.register_tool_type("unifi_get_event_types", NetworkEventTypesType, "detail")
    reg.register_tool_type(
        "unifi_get_autobackup_settings", NetworkAutoBackupSettingsType, "detail",
    )
    reg.register_tool_type("unifi_get_top_clients", NetworkTopClientType, "list")
    reg.register_tool_type(
        "unifi_get_speedtest_results", NetworkSpeedtestResultType, "list",
    )

    # network/switch (tool-keyed only)
    reg.register_tool_type("unifi_list_port_profiles", NetworkPortProfileType, "list")
    reg.register_tool_type(
        "unifi_get_port_profile_details", NetworkPortProfileType, "detail",
    )
    reg.register_tool_type("unifi_get_switch_ports", NetworkSwitchPortsType, "detail")
    reg.register_tool_type("unifi_get_port_stats", NetworkPortStatsType, "detail")
    reg.register_tool_type(
        "unifi_get_switch_capabilities", NetworkSwitchCapabilitiesType, "detail",
    )

    # network/ap_groups (tool-keyed only)
    reg.register_tool_type("unifi_list_ap_groups", NetworkApGroupType, "list")
    reg.register_tool_type(
        "unifi_get_ap_group_details", NetworkApGroupType, "detail",
    )

    # network/client_groups + usergroups (tool-keyed only)
    reg.register_tool_type("unifi_list_client_groups", NetworkClientGroupType, "list")
    reg.register_tool_type(
        "unifi_get_client_group_details", NetworkClientGroupType, "detail",
    )
    reg.register_tool_type("unifi_list_usergroups", NetworkUserGroupType, "list")
    reg.register_tool_type(
        "unifi_get_usergroup_details", NetworkUserGroupType, "detail",
    )

    # protect/cameras
    reg.register_type("protect", "cameras", ProtectCameraType)
    reg.register_type("protect", "cameras/{id}", ProtectCameraType)
    reg.register_tool_type("protect_list_cameras", ProtectCameraType, "list")
    reg.register_tool_type("protect_get_camera", ProtectCameraType, "detail")
    reg.register_tool_type(
        "protect_get_camera_analytics", ProtectCameraAnalyticsType, "detail",
    )
    reg.register_tool_type(
        "protect_get_camera_streams", ProtectCameraStreamsType, "detail",
    )
    reg.register_tool_type("protect_get_snapshot", ProtectSnapshotType, "detail")

    # protect/chimes
    reg.register_type("protect", "chimes", ProtectChimeType)
    reg.register_tool_type("protect_list_chimes", ProtectChimeType, "list")

    # protect/events
    reg.register_type("protect", "events", ProtectEventType)
    reg.register_tool_type("protect_list_events", ProtectEventType, "event_log")
    reg.register_tool_type("protect_get_event", ProtectEventType, "detail")
    reg.register_tool_type(
        "protect_get_event_thumbnail", ProtectEventThumbnailType, "detail",
    )
    reg.register_tool_type(
        "protect_list_smart_detections", ProtectSmartDetectionType, "event_log",
    )

    # protect/recordings
    reg.register_type("protect", "recordings", ProtectRecordingType)
    reg.register_type("protect", "recordings/{id}", ProtectRecordingType)
    reg.register_tool_type("protect_list_recordings", ProtectRecordingType, "list")
    reg.register_tool_type(
        "protect_get_recording_status", ProtectRecordingStatusListType, "detail",
    )

    # protect/alarms (tool-keyed only)
    reg.register_tool_type(
        "protect_alarm_get_status", ProtectAlarmStatusType, "detail",
    )
    reg.register_tool_type(
        "protect_alarm_list_profiles", ProtectAlarmProfileListType, "detail",
    )

    # protect/lights
    reg.register_type("protect", "lights", ProtectLightType)
    reg.register_type("protect", "lights/{id}", ProtectLightType)
    reg.register_tool_type("protect_list_lights", ProtectLightType, "list")

    # protect/sensors
    reg.register_type("protect", "sensors", ProtectSensorType)
    reg.register_type("protect", "sensors/{id}", ProtectSensorType)
    reg.register_tool_type("protect_list_sensors", ProtectSensorType, "list")

    # protect/liveviews
    reg.register_type("protect", "liveviews", ProtectLiveviewType)
    reg.register_type("protect", "liveviews/{id}", ProtectLiveviewType)
    reg.register_tool_type("protect_list_liveviews", ProtectLiveviewType, "list")

    # protect/system (tool-keyed only) + viewers resource
    reg.register_type("protect", "viewers", ProtectViewerType)
    reg.register_tool_type(
        "protect_get_system_info", ProtectSystemInfoType, "detail",
    )
    reg.register_tool_type("protect_get_health", ProtectHealthType, "detail")
    reg.register_tool_type(
        "protect_get_firmware_status", ProtectFirmwareStatusType, "detail",
    )
    reg.register_tool_type(
        "protect_list_viewers", ProtectViewerListType, "detail",
    )

    # access/doors
    reg.register_type("access", "doors", AccessDoorType)
    reg.register_type("access", "doors/{id}", AccessDoorType)
    reg.register_tool_type("access_list_doors", AccessDoorType, "list")
    reg.register_tool_type("access_get_door", AccessDoorType, "detail")
    reg.register_tool_type("access_list_door_groups", AccessDoorGroupType, "list")
    reg.register_tool_type("access_get_door_status", AccessDoorStatusType, "detail")

    # access/devices (tool-keyed only)
    reg.register_tool_type("access_list_devices", AccessDeviceType, "list")
    reg.register_tool_type("access_get_device", AccessDeviceType, "detail")

    # access/users
    reg.register_type("access", "users", AccessUserType)
    reg.register_type("access", "users/{id}", AccessUserType)
    reg.register_tool_type("access_list_users", AccessUserType, "list")

    # access/credentials
    reg.register_type("access", "credentials", AccessCredentialType)
    reg.register_type("access", "credentials/{id}", AccessCredentialType)
    reg.register_tool_type("access_list_credentials", AccessCredentialType, "list")
    reg.register_tool_type("access_get_credential", AccessCredentialType, "detail")

    # access/policies (tool-keyed only)
    reg.register_tool_type("access_list_policies", AccessPolicyType, "list")
    reg.register_tool_type("access_get_policy", AccessPolicyType, "detail")

    # access/schedules (tool-keyed only)
    reg.register_tool_type("access_list_schedules", AccessScheduleType, "list")

    # access/visitors
    reg.register_type("access", "visitors", AccessVisitorType)
    reg.register_type("access", "visitors/{id}", AccessVisitorType)
    reg.register_tool_type("access_list_visitors", AccessVisitorType, "list")
    reg.register_tool_type("access_get_visitor", AccessVisitorType, "detail")

    # access/events
    reg.register_type("access", "events", AccessEventType)
    reg.register_tool_type("access_list_events", AccessEventType, "event_log")
    reg.register_tool_type("access_get_event", AccessEventType, "detail")
    reg.register_tool_type(
        "access_get_activity_summary", AccessActivitySummaryType, "detail",
    )

    # access/system (tool-keyed only)
    reg.register_tool_type("access_get_system_info", AccessSystemInfoType, "detail")
    reg.register_tool_type("access_get_health", AccessHealthType, "detail")

    return reg
