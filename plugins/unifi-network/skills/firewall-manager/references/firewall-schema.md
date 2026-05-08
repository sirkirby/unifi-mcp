# Firewall Policy Schema Reference (V2 Zone-Based)

Complete schema reference for creating firewall policies via `unifi_create_firewall_policy`. The UniFi controller's V2 zone-based firewall API is the canonical and only supported create surface — the legacy V1 `ruleset`-based path was removed in #210.

The V2 model targets traffic by **zone** (a controller-defined grouping of networks/interfaces such as Internal, External, DMZ, Hotspot, Gateway, VPN) and refines that with `matching_target` selectors. Use `unifi_list_firewall_zones` to discover the zone IDs available on a controller — never hardcode them.

---

## Required Top-Level Fields

| Field | Type | Notes |
|-------|------|-------|
| `name` | string | Human-readable policy name (required, non-empty). |
| `action` | enum | `ALLOW`, `BLOCK`, or `REJECT` — uppercase. |
| `source` | object | Zone-based source selector. See [Source / Destination](#source--destination). |
| `destination` | object | Same structure as `source`. |

Optional but commonly used: `enabled`, `protocol`, `index`, `ip_version`, `connection_state_type`, `connection_states`, `schedule`, `logging`, `description`.

---

## Actions

| Action | Behavior | When to Use |
|--------|----------|-------------|
| `ALLOW` | Allow the traffic through. | Explicit allow rules; pair with `create_allow_respond` for stateful return traffic. |
| `BLOCK` | Silently discard the packet (no response). | External-facing rules; avoids revealing firewall presence. |
| `REJECT` | Discard and send RST (TCP) or ICMP unreachable (UDP/ICMP). | Internal rules; clients fail fast instead of timing out. |

**Recommendation:**
- Use `REJECT` for inter-zone blocking (IoT isolation, guest lockdown) — clients fail fast instead of hanging.
- Use `BLOCK` for inbound rules from External zones blocking unsolicited traffic.

---

## Source / Destination

Both `source` and `destination` are objects with the same shape. The required fields are `zone_id` and `matching_target`. Additional fields depend on the chosen `matching_target`.

### Field Reference

| Field | Type | Required For |
|-------|------|--------------|
| `zone_id` | string | always — controller zone ID from `unifi_list_firewall_zones` |
| `matching_target` | enum | always — `ANY`, `IP`, `NETWORK`, or `OBJECT` |
| `matching_target_type` | enum | required when `matching_target` is `IP` or `NETWORK` — `SPECIFIC` (IPs) or `OBJECT` (group/network IDs) |
| `ips` | array of strings | required when `matching_target_type="SPECIFIC"` — list of IPs/CIDRs |
| `network_ids` | array of strings | required when `matching_target="NETWORK"` and `matching_target_type="OBJECT"` |

### `matching_target` Enum (live-probe-confirmed)

- **`ANY`** — match all traffic in the zone. No additional selectors needed.
- **`IP`** — match specific IPs/CIDRs. Pair with `matching_target_type: "SPECIFIC"` and `ips: [...]`.
- **`NETWORK`** — match by network membership. Pair with `matching_target_type: "OBJECT"` and `network_ids: [...]`.
- **`OBJECT`** — match an IP-group object. Pair with `matching_target_type: "OBJECT"` and the relevant object ID.

### Example — any-in-zone to any-in-zone

```json
{
  "source":      { "zone_id": "<source_zone_id>", "matching_target": "ANY" },
  "destination": { "zone_id": "<dest_zone_id>",   "matching_target": "ANY" }
}
```

### Example — specific IPs to a network

```json
{
  "source": {
    "zone_id": "<source_zone_id>",
    "matching_target": "IP",
    "matching_target_type": "SPECIFIC",
    "ips": ["192.168.10.50", "192.168.10.51/32"]
  },
  "destination": {
    "zone_id": "<dest_zone_id>",
    "matching_target": "NETWORK",
    "matching_target_type": "OBJECT",
    "network_ids": ["<network_id>"]
  }
}
```

---

## Discovering IDs

Always discover IDs at runtime. Never hardcode.

| Tool | Returns |
|------|---------|
| `unifi_list_firewall_zones` | Zone IDs and names (Internal, External, DMZ, Hotspot, Gateway, VPN, ...) |
| `unifi_list_networks` | Network IDs, names, VLAN IDs |
| `unifi_list_firewall_groups` | IP group / port group IDs |
| `unifi_list_firewall_policies` | Existing policy IDs and structure (use for examples) |
| `unifi_get_dpi_stats` | Available DPI categories on this controller |

---

## Protocols

| Value | Description |
|-------|-------------|
| `all` | Match all protocols (default). |
| `tcp` | TCP only. |
| `udp` | UDP only. |
| `icmp` | ICMP only. |

---

## IP Version

| Value | Description |
|-------|-------------|
| `BOTH` | Match both IPv4 and IPv6 (default). |
| `IPV4` | IPv4 only. |
| `IPV6` | IPv6 only. |

Mixed-case input (e.g. `"IPv4"`) is normalized server-side, but emit uppercase to be explicit.

---

## Connection States

Controlled by `connection_state_type` and (when CUSTOM) `connection_states`.

| `connection_state_type` | Description |
|-------------------------|-------------|
| `ALL` | Match every state (default). |
| `RESPOND_ONLY` | Match only return traffic. |
| `CUSTOM` | Match the states listed in `connection_states`. |

Allowed `connection_states` (uppercase): `NEW`, `RELATED`, `INVALID`, `ESTABLISHED`.

**Common pattern — stateful allow:**
```json
{
  "connection_state_type": "CUSTOM",
  "connection_states": ["ESTABLISHED", "RELATED"]
}
```

---

## Schedule

`schedule` is an object. Default is always-on:

```json
{ "mode": "ALWAYS" }
```

Time-based example (custom mode):

```json
{
  "mode": "CUSTOM",
  "repeat_on_days": ["mon", "tue", "wed", "thu", "fri"],
  "time_all_day": false,
  "time_range_start": "22:00",
  "time_range_end": "06:00"
}
```

Time ranges that span midnight are supported.

---

## Other Useful Optional Fields

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | `true` | Whether the policy is active. |
| `index` | controller-assigned | Rule priority/order (lower = evaluated first). The controller assigns based on creation order; usually omit. |
| `logging` | `false` | Log matched traffic. |
| `create_allow_respond` | `false` | Auto-create return-traffic rule for ALLOW policies. |
| `match_ip_sec` | `false` | Match IPSec traffic. |
| `match_opposite_protocol` | `false` | Match opposite protocol. |
| `icmp_typename` | `"ANY"` | ICMP type name. |
| `icmp_v6_typename` | `"ANY"` | ICMPv6 type name. |
| `description` | empty | Free-text policy description. |

---

## Full Worked Example — Block IoT zone to Internal zone

```json
{
  "name": "Block IoT to Internal",
  "action": "REJECT",
  "enabled": true,
  "protocol": "all",
  "ip_version": "BOTH",
  "source": {
    "zone_id": "<iot_zone_id>",
    "matching_target": "ANY"
  },
  "destination": {
    "zone_id": "<internal_zone_id>",
    "matching_target": "ANY"
  },
  "connection_state_type": "ALL",
  "schedule": { "mode": "ALWAYS" },
  "logging": false
}
```

---

## MAC-Based Targeting (Important Caveat)

The V2 zone-based firewall does **not** accept client MAC addresses as a matching target. Source/destination is always zone- + IP/network/object-based. To enforce per-client (MAC-level) blocking, use `unifi_create_acl_rule` with `source_macs=[...]` instead of the firewall surface.

---

## Useful Discovery Tools

Before creating policies, use these tools to gather required IDs:

| Tool | What It Returns |
|------|-----------------|
| `unifi_list_firewall_zones` | Zone IDs and names |
| `unifi_list_networks` | Network IDs, names, VLANs |
| `unifi_list_firewall_policies` | Existing policy IDs and structure |
| `unifi_list_firewall_groups` | IP group and port group IDs |
| `unifi_get_clients` | Connected client MACs and hostnames |
| `unifi_get_dpi_stats` | Available DPI categories on this controller |
