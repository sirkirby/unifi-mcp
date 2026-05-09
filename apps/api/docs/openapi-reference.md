# unifi-api-server REST Reference

> Auto-generated from `openapi.json` by `unifi_api.graphql.docgen`.
> Regenerate with `python -m unifi_api.graphql.docgen`.


## access/credentials

### `GET /v1/sites/{site_id}/credentials` — List Credentials


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_CredentialModel_`

### `GET /v1/sites/{site_id}/credentials/{credential_id}` — Get Credential


**Parameters:**

- `site_id` (path) (required)
- `credential_id` (path) (required)
- `controller` (query)


**Returns:** `Detail_CredentialModel_`


## access/devices

### `GET /v1/sites/{site_id}/access-devices` — List Access Devices


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/access-devices/{device_id}` — Get Access Device


**Parameters:**

- `site_id` (path) (required)
- `device_id` (path) (required)
- `controller` (query)


**Returns:** `object`


## access/doors

### `GET /v1/sites/{site_id}/door-groups` — List Door Groups


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/doors` — List Doors


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_DoorModel_`

### `GET /v1/sites/{site_id}/doors/{door_id}` — Get Door


**Parameters:**

- `site_id` (path) (required)
- `door_id` (path) (required)
- `controller` (query)


**Returns:** `Detail_DoorModel_`

### `GET /v1/sites/{site_id}/doors/{door_id}/status` — Get Door Status


Per-door status (nested under /doors/{door_id}/status).

Mirrors the protect /cameras/{id}/analytics nested-detail pattern.
DoorManager.get_door_status raises UniFiNotFoundError on miss → 404.


**Parameters:**

- `site_id` (path) (required)
- `door_id` (path) (required)
- `controller` (query)


**Returns:** `object`


## access/events

### `GET /v1/sites/{site_id}/access/activity-summary` — Get Access Activity Summary


**Parameters:**

- `site_id` (path) (required)
- `door_id` (query)
- `days` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/access/events` — List Access Events


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/access/events/{event_id}` — Get Access Event


**Parameters:**

- `site_id` (path) (required)
- `event_id` (path) (required)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/access/recent-events` — Recent Access Events


Return a snapshot of the websocket ring buffer.

Differs from the SSE stream at ``/v1/streams/access/events``: this is
a buffer-snapshot REST surface, not a tailing stream. Mirrors PR3's
protect ``/recent-events`` shape: ``{events, count, source, buffer_size}``.
``EventManager.get_recent_from_buffer`` is synchronous (in-memory ring
buffer read).


**Parameters:**

- `site_id` (path) (required)
- `event_type` (query)
- `door_id` (query)
- `limit` (query)
- `controller` (query)


**Returns:** `object`


## access/policies

### `GET /v1/sites/{site_id}/policies` — List Policies


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/policies/{policy_id}` — Get Policy


**Parameters:**

- `site_id` (path) (required)
- `policy_id` (path) (required)
- `controller` (query)


**Returns:** `object`


## access/schedules

### `GET /v1/sites/{site_id}/schedules` — List Schedules


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`


## access/system

### `GET /v1/sites/{site_id}/access/health` — Get Access Health


**Parameters:**

- `site_id` (path) (required)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/access/system-info` — Get Access System Info


**Parameters:**

- `site_id` (path) (required)
- `controller` (query)


**Returns:** `object`


## access/users

### `GET /v1/sites/{site_id}/users` — List Users


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_UserModel_`

### `GET /v1/sites/{site_id}/users/{user_id}` — Get User


Fetch a user by listing then filtering — no native get_user method.


**Parameters:**

- `site_id` (path) (required)
- `user_id` (path) (required)
- `controller` (query)


**Returns:** `Detail_UserModel_`


## access/visitors

### `GET /v1/sites/{site_id}/visitors` — List Visitors


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/visitors/{visitor_id}` — Get Visitor


**Parameters:**

- `site_id` (path) (required)
- `visitor_id` (path) (required)
- `controller` (query)


**Returns:** `object`


## network/clients

### `GET /v1/sites/{site_id}/blocked-clients` — List Blocked Clients


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_BlockedClientModel_`

### `GET /v1/sites/{site_id}/client-sessions` — Get Client Sessions


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/client-wifi-details/{mac}` — Get Client Wifi Details


**Parameters:**

- `site_id` (path) (required)
- `mac` (path) (required)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/clients` — List Clients


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_ClientModel_`

### `GET /v1/sites/{site_id}/clients/{mac}` — Get Client


**Parameters:**

- `site_id` (path) (required)
- `mac` (path) (required)
- `controller` (query)


**Returns:** `Detail_ClientModel_`


## network/devices

### `GET /v1/sites/{site_id}/devices` — List Devices


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_DeviceModel_`

### `GET /v1/sites/{site_id}/devices/{mac}` — Get Device


**Parameters:**

- `site_id` (path) (required)
- `mac` (path) (required)
- `controller` (query)


**Returns:** `Detail_DeviceModel_`

### `GET /v1/sites/{site_id}/devices/{mac}/outlets` — Get Pdu Outlets


**Parameters:**

- `site_id` (path) (required)
- `mac` (path) (required)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/devices/{mac}/radio` — Get Device Radio


**Parameters:**

- `site_id` (path) (required)
- `mac` (path) (required)
- `controller` (query)


**Returns:** `object`


## network/dns

### `GET /v1/sites/{site_id}/dns-records` — List Dns Records


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_DnsRecordModel_`

### `GET /v1/sites/{site_id}/dns-records/{record_id}` — Get Dns Record Details


**Parameters:**

- `site_id` (path) (required)
- `record_id` (path) (required)
- `controller` (query)


**Returns:** `Detail_DnsRecordModel_`


## network/firewall

### `GET /v1/sites/{site_id}/acl-rules` — List Acl Rules


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_AclRuleModel_`

### `GET /v1/sites/{site_id}/acl-rules/{rule_id}` — Get Acl Rule Details


**Parameters:**

- `site_id` (path) (required)
- `rule_id` (path) (required)
- `controller` (query)


**Returns:** `Detail_AclRuleModel_`

### `GET /v1/sites/{site_id}/firewall/groups` — List Firewall Groups


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_FirewallGroupModel_`

### `GET /v1/sites/{site_id}/firewall/groups/{group_id}` — Get Firewall Group Details


**Parameters:**

- `site_id` (path) (required)
- `group_id` (path) (required)
- `controller` (query)


**Returns:** `Detail_FirewallGroupModel_`

### `GET /v1/sites/{site_id}/firewall/rules` — List Firewall Rules


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_FirewallRuleModel_`

### `GET /v1/sites/{site_id}/firewall/rules/{rule_id}` — Get Firewall Rule


**Parameters:**

- `site_id` (path) (required)
- `rule_id` (path) (required)
- `controller` (query)


**Returns:** `Detail_FirewallRuleModel_`

### `GET /v1/sites/{site_id}/firewall/zones` — List Firewall Zones


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_FirewallZoneModel_`


## network/groups

### `GET /v1/sites/{site_id}/ap-groups` — List Ap Groups


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_ApGroupModel_`

### `GET /v1/sites/{site_id}/ap-groups/{group_id}` — Get Ap Group Details


**Parameters:**

- `site_id` (path) (required)
- `group_id` (path) (required)
- `controller` (query)


**Returns:** `Detail_ApGroupModel_`

### `GET /v1/sites/{site_id}/client-groups` — List Client Groups


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_ClientGroupModel_`

### `GET /v1/sites/{site_id}/client-groups/{group_id}` — Get Client Group Details


**Parameters:**

- `site_id` (path) (required)
- `group_id` (path) (required)
- `controller` (query)


**Returns:** `Detail_ClientGroupModel_`

### `GET /v1/sites/{site_id}/user-groups` — List User Groups


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_UserGroupModel_`

### `GET /v1/sites/{site_id}/user-groups/{group_id}` — Get User Group Details


**Parameters:**

- `site_id` (path) (required)
- `group_id` (path) (required)
- `controller` (query)


**Returns:** `Detail_UserGroupModel_`


## network/lldp

### `GET /v1/sites/{site_id}/lldp-neighbors` — List Lldp Neighbors


**Parameters:**

- `site_id` (path) (required)
- `device_mac` (query) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`


## network/lookup

### `GET /v1/sites/{site_id}/lookup-by-ip` — Lookup Client By Ip


**Parameters:**

- `site_id` (path) (required)
- `ip` (query) (required)
- `controller` (query)


**Returns:** `object`


## network/networks

### `GET /v1/sites/{site_id}/networks` — List Networks


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_NetworkModel_`

### `GET /v1/sites/{site_id}/networks/{network_id}` — Get Network


**Parameters:**

- `site_id` (path) (required)
- `network_id` (path) (required)
- `controller` (query)


**Returns:** `Detail_NetworkModel_`


## network/observability

### `GET /v1/sites/{site_id}/alerts` — Get Alerts


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/anomalies` — Get Anomalies


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/ips-events` — Get Ips Events


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/speedtest-results` — Get Speedtest Results


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/speedtest-status` — Get Speedtest Status


**Parameters:**

- `site_id` (path) (required)
- `gateway_mac` (query) (required)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/stats/clients/{mac}` — Get Client Stats


TIMESERIES; calls stats_manager.get_client_stats (PR4).


**Parameters:**

- `site_id` (path) (required)
- `mac` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/stats/dashboard` — Get Dashboard Stats


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/stats/devices/{mac}` — Get Device Stats


TIMESERIES; calls stats_manager.get_device_stats (PR4).


**Parameters:**

- `site_id` (path) (required)
- `mac` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/stats/dpi` — Get Dpi Stats


DETAIL kind currently; manager method is stats_manager.get_dpi_stats.


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/stats/dpi/clients/{mac}` — Get Client Dpi Traffic


**Parameters:**

- `site_id` (path) (required)
- `mac` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/stats/dpi/site` — Get Site Dpi Traffic


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/stats/gateway` — Get Gateway Stats


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/stats/network` — Get Network Stats


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`


## network/policy

### `GET /v1/sites/{site_id}/content-filters` — List Content Filters


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_ContentFilterModel_`

### `GET /v1/sites/{site_id}/content-filters/{filter_id}` — Get Content Filter Details


**Parameters:**

- `site_id` (path) (required)
- `filter_id` (path) (required)
- `controller` (query)


**Returns:** `Detail_ContentFilterModel_`

### `GET /v1/sites/{site_id}/dpi-applications` — List Dpi Applications


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_DpiApplicationModel_`

### `GET /v1/sites/{site_id}/dpi-categories` — List Dpi Categories


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_DpiCategoryModel_`

### `GET /v1/sites/{site_id}/oon-policies` — List Oon Policies


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_OonPolicyModel_`

### `GET /v1/sites/{site_id}/oon-policies/{policy_id}` — Get Oon Policy Details


**Parameters:**

- `site_id` (path) (required)
- `policy_id` (path) (required)
- `controller` (query)


**Returns:** `Detail_OonPolicyModel_`

### `GET /v1/sites/{site_id}/port-forwards` — List Port Forwards


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_PortForwardModel_`

### `GET /v1/sites/{site_id}/port-forwards/{port_forward_id}` — Get Port Forward


**Parameters:**

- `site_id` (path) (required)
- `port_forward_id` (path) (required)
- `controller` (query)


**Returns:** `Detail_PortForwardModel_`

### `GET /v1/sites/{site_id}/qos-rules` — List Qos Rules


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_QosRuleModel_`

### `GET /v1/sites/{site_id}/qos-rules/{rule_id}` — Get Qos Rule Details


**Parameters:**

- `site_id` (path) (required)
- `rule_id` (path) (required)
- `controller` (query)


**Returns:** `Detail_QosRuleModel_`


## network/routes

### `GET /v1/sites/{site_id}/active-routes` — List Active Routes


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_ActiveRouteModel_`

### `GET /v1/sites/{site_id}/static-routes` — List Routes


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_RouteModel_`

### `GET /v1/sites/{site_id}/static-routes/{route_id}` — Get Route Details


**Parameters:**

- `site_id` (path) (required)
- `route_id` (path) (required)
- `controller` (query)


**Returns:** `Detail_RouteModel_`

### `GET /v1/sites/{site_id}/traffic-routes` — List Traffic Routes


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_TrafficRouteModel_`

### `GET /v1/sites/{site_id}/traffic-routes/{route_id}` — Get Traffic Route Details


**Parameters:**

- `site_id` (path) (required)
- `route_id` (path) (required)
- `controller` (query)


**Returns:** `Detail_TrafficRouteModel_`


## network/snmp

### `GET /v1/sites/{site_id}/snmp-settings` — Get Snmp Settings


**Parameters:**

- `site_id` (path) (required)
- `controller` (query)


**Returns:** `object`


## network/switch

### `GET /v1/sites/{site_id}/port-profiles` — List Port Profiles


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_PortProfileModel_`

### `GET /v1/sites/{site_id}/port-profiles/{profile_id}` — Get Port Profile Details


**Parameters:**

- `site_id` (path) (required)
- `profile_id` (path) (required)
- `controller` (query)


**Returns:** `Detail_PortProfileModel_`

### `GET /v1/sites/{site_id}/port-stats` — List Port Stats


**Parameters:**

- `site_id` (path) (required)
- `device_mac` (query) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/switch-capabilities` — Get Switch Capabilities


**Parameters:**

- `site_id` (path) (required)
- `device_mac` (query) (required)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/switch-ports` — List Switch Ports


**Parameters:**

- `site_id` (path) (required)
- `device_mac` (query) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`


## network/system

### `GET /v1/sites/{site_id}/alarms` — List Alarms


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/autobackup-settings` — Get Autobackup Settings


**Parameters:**

- `site_id` (path) (required)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/backups` — List Backups


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/event-types` — Get Event Types


DETAIL — event_manager.get_event_type_prefixes (sync method, returns list).


**Parameters:**

- `site_id` (path) (required)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/network-health` — Get Network Health


LIST kind per Phase 4A — manager returns multi-element list of subsystems.


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/site-settings` — Get Site Settings


**Parameters:**

- `site_id` (path) (required)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/system-info` — Get System Info


**Parameters:**

- `site_id` (path) (required)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/top-clients` — Get Top Clients


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`


## network/vouchers

### `GET /v1/sites/{site_id}/voucher-details/{voucher_id}` — Get Voucher Details


**Parameters:**

- `site_id` (path) (required)
- `voucher_id` (path) (required)
- `controller` (query)


**Returns:** `Detail_VoucherModel_`

### `GET /v1/sites/{site_id}/vouchers` — List Vouchers


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_VoucherModel_`


## network/vpn

### `GET /v1/sites/{site_id}/vpn-clients` — List Vpn Clients


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_VpnClientModel_`

### `GET /v1/sites/{site_id}/vpn-clients/{client_id}` — Get Vpn Client Details


**Parameters:**

- `site_id` (path) (required)
- `client_id` (path) (required)
- `controller` (query)


**Returns:** `Detail_VpnClientModel_`

### `GET /v1/sites/{site_id}/vpn-servers` — List Vpn Servers


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_VpnServerModel_`

### `GET /v1/sites/{site_id}/vpn-servers/{server_id}` — Get Vpn Server Details


**Parameters:**

- `site_id` (path) (required)
- `server_id` (path) (required)
- `controller` (query)


**Returns:** `Detail_VpnServerModel_`


## network/wireless

### `GET /v1/sites/{site_id}/available-channels` — List Available Channels


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_AvailableChannelModel_`

### `GET /v1/sites/{site_id}/rf-scan-results` — List Rf Scan Results


**Parameters:**

- `site_id` (path) (required)
- `ap_mac` (query) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_RfScanResultModel_`

### `GET /v1/sites/{site_id}/rogue-aps` — List Rogue Aps


**Parameters:**

- `site_id` (path) (required)
- `within_hours` (query)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`


## network/wlans

### `GET /v1/sites/{site_id}/wlans` — List Wlans


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_WlanModel_`

### `GET /v1/sites/{site_id}/wlans/{wlan_id}` — Get Wlan


**Parameters:**

- `site_id` (path) (required)
- `wlan_id` (path) (required)
- `controller` (query)


**Returns:** `Detail_WlanModel_`


## protect/cameras

### `GET /v1/sites/{site_id}/cameras` — List Cameras


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_CameraModel_`

### `GET /v1/sites/{site_id}/cameras/{camera_id}` — Get Camera


**Parameters:**

- `site_id` (path) (required)
- `camera_id` (path) (required)
- `controller` (query)


**Returns:** `Detail_CameraModel_`

### `GET /v1/sites/{site_id}/cameras/{camera_id}/analytics` — Get Camera Analytics


**Parameters:**

- `site_id` (path) (required)
- `camera_id` (path) (required)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/cameras/{camera_id}/snapshot` — Get Camera Snapshot


Return snapshot metadata (size_bytes / content_type / captured_at).

The manager returns raw JPEG bytes; the SnapshotSerializer surfaces
metadata only. A future ``/snapshot/raw`` endpoint that returns the
binary body is deferred to Phase 5B if a UI consumer needs it.


**Parameters:**

- `site_id` (path) (required)
- `camera_id` (path) (required)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/cameras/{camera_id}/streams` — Get Camera Streams


**Parameters:**

- `site_id` (path) (required)
- `camera_id` (path) (required)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/chimes` — List Chimes


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`


## protect/events

### `GET /v1/sites/{site_id}/event-thumbnails/{event_id}` — Get Event Thumbnail


**Parameters:**

- `site_id` (path) (required)
- `event_id` (path) (required)
- `width` (query)
- `height` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/events` — List Events


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `Page_EventModel_`

### `GET /v1/sites/{site_id}/events/{event_id}` — Get Event


**Parameters:**

- `site_id` (path) (required)
- `event_id` (path) (required)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/recent-events` — Recent Events


Return a snapshot of the websocket ring buffer.

Differs from the SSE stream at ``/v1/streams/protect/events``: this is
a buffer-snapshot REST surface, not a tailing stream. ``DETAIL`` render
kind — the manager's wrapper dict (events / count / source / buffer_size)
is itself the payload.


**Parameters:**

- `site_id` (path) (required)
- `event_type` (query)
- `camera_id` (query)
- `min_confidence` (query)
- `limit` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/recording-status` — Get Recording Status


Return current recording state for one or all cameras.

The ``camera_id`` query is optional: omitting it returns the
aggregate (all cameras), supplying it scopes to one camera and
raises 404 via UniFiNotFoundError if the camera is unknown.


**Parameters:**

- `site_id` (path) (required)
- `camera_id` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/recordings` — List Recordings


**Parameters:**

- `site_id` (path) (required)
- `camera_id` (query) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/recordings/{recording_id}` — Get Recording


**Parameters:**

- `site_id` (path) (required)
- `recording_id` (path) (required)
- `camera_id` (query) (required)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/smart-detections` — List Smart Detections


**Parameters:**

- `site_id` (path) (required)
- `camera_id` (query)
- `detection_type` (query)
- `min_confidence` (query)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`


## protect/lights

### `GET /v1/sites/{site_id}/lights` — List Lights


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/lights/{light_id}` — Get Light Details


No native ``protect_get_light`` tool exists — filter from LIST.

LightManager._get_light raises UniFiNotFoundError, but list_lights
does not invoke that helper. We wrap the manager call defensively
so any future refactor that surfaces UniFiNotFoundError keeps mapping
cleanly to a 404.


**Parameters:**

- `site_id` (path) (required)
- `light_id` (path) (required)
- `controller` (query)


**Returns:** `object`


## protect/liveviews

### `GET /v1/sites/{site_id}/liveviews` — List Liveviews


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/liveviews/{liveview_id}` — Get Liveview


No native ``protect_get_liveview`` tool — filter from LIST.


**Parameters:**

- `site_id` (path) (required)
- `liveview_id` (path) (required)
- `controller` (query)


**Returns:** `object`


## protect/sensors

### `GET /v1/sites/{site_id}/sensors` — List Sensors


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/sensors/{sensor_id}` — Get Sensor Details


No native ``protect_get_sensor`` tool exists — filter from LIST.


**Parameters:**

- `site_id` (path) (required)
- `sensor_id` (path) (required)
- `controller` (query)


**Returns:** `object`


## protect/system

### `GET /v1/sites/{site_id}/alarm-profiles` — Alarm List Profiles


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/alarm-status` — Alarm Get Status


**Parameters:**

- `site_id` (path) (required)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/firmware-status` — Get Firmware Status


**Parameters:**

- `site_id` (path) (required)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/protect/health` — Get Protect Health


**Parameters:**

- `site_id` (path) (required)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/protect/system-info` — Get Protect System Info


**Parameters:**

- `site_id` (path) (required)
- `controller` (query)


**Returns:** `object`

### `GET /v1/sites/{site_id}/viewers` — List Viewers


**Parameters:**

- `site_id` (path) (required)
- `limit` (query)
- `cursor` (query)
- `controller` (query)


**Returns:** `object`


## untagged

### `POST /v1/actions/{tool_name}` — Post Action


**Parameters:**

- `tool_name` (path) (required)


**Returns:** `object`

### `GET /v1/audit` — List Audit


**Parameters:**

- `controller` (query)
- `outcome` (query)
- `since` (query)
- `until` (query)
- `q` (query)
- `limit` (query)
- `cursor` (query)


**Returns:** `object`

### `POST /v1/audit/prune` — Prune Endpoint


**Returns:** `object`

### `GET /v1/catalog/categories` — Get Categories


**Returns:** `object`

### `GET /v1/catalog/render-hints` — Get Render Hints


**Returns:** `object`

### `GET /v1/catalog/resources` — Get Resources


Discoverability endpoint: every registered resource path with render_hint.

Lists every (product, resource_path) pair from the serializer registry.
For paths with placeholders (e.g., 'clients/{mac}'), renders as a path
template under /v1/sites/{site_id}/.


**Returns:** `object`

### `GET /v1/catalog/tools` — Get Tools


**Returns:** `object`

### `GET /v1/controllers` — List Endpoint


**Returns:** `array`

### `POST /v1/controllers` — Post Controller

### `DELETE /v1/controllers/{cid}` — Delete Endpoint


**Parameters:**

- `cid` (path) (required)

### `GET /v1/controllers/{cid}` — Get Endpoint


**Parameters:**

- `cid` (path) (required)


**Returns:** `ControllerOut`

### `PATCH /v1/controllers/{cid}` — Patch Endpoint


**Parameters:**

- `cid` (path) (required)


**Returns:** `ControllerOut`

### `GET /v1/controllers/{cid}/capabilities` — Capabilities Endpoint


**Parameters:**

- `cid` (path) (required)
- `refresh` (query)


**Returns:** `object`

### `POST /v1/controllers/{cid}/probe` — Probe Endpoint


**Parameters:**

- `cid` (path) (required)


**Returns:** `object`

### `GET /v1/diagnostics` — Get Diagnostics


**Returns:** `object`

### `GET /v1/graphql` — Handle Http Get

### `POST /v1/graphql` — Handle Http Post

### `GET /v1/health` — Liveness


**Returns:** `object`

### `GET /v1/health/ready` — Readiness


**Returns:** `object`

### `GET /v1/logs` — Get Logs


**Parameters:**

- `level` (query)
- `logger` (query)
- `q` (query)
- `limit` (query)


**Returns:** `object`

### `GET /v1/settings` — Get Settings


**Returns:** `object`

### `PUT /v1/settings` — Put Settings


**Returns:** `object`

### `GET /v1/streams/access/doors/{door_id}/events` — Stream Access Door Events


**Parameters:**

- `door_id` (path) (required)
- `controller` (query)
- `Last-Event-ID` (header)

### `GET /v1/streams/access/events` — Stream Access Events


**Parameters:**

- `controller` (query)
- `Last-Event-ID` (header)

### `GET /v1/streams/audit` — Stream Audit


SSE stream of audit rows. One frame per row inserted via write_audit.

### `GET /v1/streams/network/devices/{mac}/events` — Stream Network Device Events


**Parameters:**

- `mac` (path) (required)
- `controller` (query)
- `Last-Event-ID` (header)

### `GET /v1/streams/network/events` — Stream Network Events


**Parameters:**

- `controller` (query)
- `Last-Event-ID` (header)

### `GET /v1/streams/protect/cameras/{camera_id}/events` — Stream Protect Camera Events


**Parameters:**

- `camera_id` (path) (required)
- `controller` (query)
- `Last-Event-ID` (header)

### `GET /v1/streams/protect/events` — Stream Protect Events


**Parameters:**

- `controller` (query)
- `Last-Event-ID` (header)
