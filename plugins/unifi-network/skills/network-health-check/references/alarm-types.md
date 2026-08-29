# Alarm & Event Types Reference

## Exact Event Keys

Call `unifi_get_event_types` to discover exact event keys observed recently on
the controller. Pass a returned `key` unchanged to the `event_type` parameter of
`unifi_list_events`.

Do not pass legacy `EVT_*` prefixes, partial keys, or wildcard patterns. Modern
controllers validate this parameter as an exact enum value. Available keys vary
by controller version, features, and recent activity.

Representative keys include `CLIENT_CONNECTED_WIRELESS_2`,
`CLIENT_DISCONNECTED_WIRELESS_2`, `DEVICE_UNREACHABLE`,
`NETWORK_WAN_FAILED_2`, and `THREAT_DETECTED_V3`. Treat these as examples only;
use a key returned by `unifi_get_event_types` for the controller being checked.

## Alarm Severity Levels

| Severity | Meaning | Action |
|----------|---------|--------|
| `critical` | Service-impacting, immediate attention needed | Investigate now |
| `warning` | Potential issue or degraded state | Review and plan |
| `informational` | Notable event, no action needed | Note for awareness |

## Common Alarms and What They Mean

| Type | Severity | What It Means | What To Do |
|------|----------|---------------|-----------|
| `DEVICE_UNREACHABLE` | critical | A UniFi device stopped responding | Check power and uplink connectivity |
| `DEVICE_RECONNECTED` | info | A UniFi device came back online | Verify clients and downlinks recovered |
| `NETWORK_WAN_FAILED_2` | warning | WAN connectivity failed | Check ISP status and failover configuration |
| `NETWORK_WAN_RESTORED_2` | info | WAN connectivity recovered | Verify primary-path stability |
| `THREAT_DETECTED_V3` | varies | A security threat was detected | Review threat details and the source |
| `TRAFFIC_BLOCKED_KNOWN_SOURCE_CLIENT` | varies | Traffic from a known client was blocked | Review the client and blocking policy |

## Response Fields

**Alarms** (`unifi_list_alarms`): `_id`, `msg`, `severity`, `type`, `timestamp`, device/client MAC

**Events** (`unifi_list_events`): `_id`, `key`, `msg`, `time` (Unix timestamp), `severity`
