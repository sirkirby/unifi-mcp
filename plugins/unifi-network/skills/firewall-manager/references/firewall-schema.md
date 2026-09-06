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
| `matching_target` | enum | always — `ANY`, `IP`, `NETWORK`, or `CLIENT` (see below) |
| `matching_target_type` | enum | required when `matching_target` is `IP` or `NETWORK` — `SPECIFIC` (IPs) or `OBJECT` (group/network IDs) |
| `ips` | array of strings | required when `matching_target="IP"` and `matching_target_type="SPECIFIC"` — list of IPs/CIDRs |
| `ip_group_id` | string | required when `matching_target="IP"` and `matching_target_type="OBJECT"` — address group from `unifi_list_firewall_groups` |
| `network_ids` | array of strings | required when `matching_target="NETWORK"` and `matching_target_type="OBJECT"` |
| `client_macs` | array of strings | required when `matching_target="CLIENT"` — client MAC addresses |
| `match_opposite_ips` | boolean | optional — invert the IP match (everything **except** `ips` / `ip_group_id`) |
| `match_opposite_networks` | boolean | optional — invert the network match |
| `port_matching_type` | enum | optional — `ANY` (default), `SPECIFIC`, or `OBJECT`; see Port Matching |
| `port` | string | required when `port_matching_type="SPECIFIC"` — `"53"`, `"53,853"`, `"1000-2000"` |
| `port_group_id` | string | required when `port_matching_type="OBJECT"` — port group from `unifi_list_firewall_groups` |
| `match_opposite_ports` | boolean | optional — invert the port match |

### `matching_target` Enum

Values observed on Network 10.6 controllers (the tools validate these four and pass any other value through unchanged):

- **`ANY`** — match all traffic in the zone. No additional selectors needed.
- **`IP`** — match specific IPs/CIDRs. Pair with `matching_target_type: "SPECIFIC"` and `ips: [...]`, or `matching_target_type: "OBJECT"` and `ip_group_id`.
- **`NETWORK`** — match by network membership. Pair with `matching_target_type: "OBJECT"` and `network_ids: [...]`.
- **`CLIENT`** — match specific clients by MAC. Pair with `client_macs: [...]`.

The Zone-Based Firewall UI also offers App, Domain ("Web") and Region targets. Their V2 field names are not documented here yet; `unifi_list_firewall_policies` with `summary: false` shows the exact shape of any such policy on your controller, and `unifi_update_firewall_policy` passes those fields through.

### Port Matching

Either side can match on destination or source ports. This is how a policy expresses "DNS", "SSH" or "web" instead of "everything between these zones".

| `port_matching_type` | Pair with | Meaning |
|---|---|---|
| `ANY` (default) | nothing | all ports |
| `SPECIFIC` | `port: "53,853"` | comma-separated ports; `low-high` ranges accepted |
| `OBJECT` | `port_group_id` | a reusable port group from `unifi_list_firewall_groups` |

Set `protocol` to `tcp`, `udp` or `tcp_udp` on a port-matching policy. The controller also stores ports under `protocol: "all"` and existing user policies use that combination; the auditor treats both as port rules.

```json
{
  "name": "Block external DNS",
  "action": "BLOCK",
  "protocol": "tcp_udp",
  "source":      { "zone_id": "<internal_zone_id>", "matching_target": "ANY" },
  "destination": {
    "zone_id": "<external_zone_id>",
    "matching_target": "ANY",
    "port_matching_type": "SPECIFIC",
    "port": "53,853"
  }
}
```

`match_opposite_ports: true` inverts the match (every port except the listed ones); `match_opposite_ips: true` does the same for `ips` / `ip_group_id`.

A selector is only accepted together with the value that activates it: `port` needs `port_matching_type: SPECIFIC`, `port_group_id` needs `OBJECT`, `client_macs` needs `matching_target: CLIENT`. The controller would accept and silently ignore any other combination, so the tools reject it. To turn port matching off on an existing policy, update with `{"destination": {"port_matching_type": "ANY"}}`; the tool retires the stored `port` for you. The same applies when switching between `SPECIFIC` and `OBJECT`, or moving a side off `CLIENT`.

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
| `tcp_udp` | TCP and UDP (the usual choice for port-matching policies). |
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

## Policy Ordering

Zone-based firewall policy ordering is not changed by updating `index`.
Use the dedicated ordering API through the MCP tools:

```text
unifi_get_firewall_policy_ordering
unifi_reorder_firewall_policies
```

Ordering is scoped to a source/destination firewall zone pair and has this
shape:

```json
{
  "orderedFirewallPolicyIds": {
    "beforeSystemDefined": ["<policy-id>"],
    "afterSystemDefined": ["<policy-id>"]
  }
}
```

For reorder operations, preserve the complete current policy ID set and only
move IDs between or within `beforeSystemDefined` and `afterSystemDefined`.

These tools require a UniFi Network integration API key (`UNIFI_API_KEY` or
`UNIFI_NETWORK_API_KEY`). Local username/password controller cookies are not
accepted by `/proxy/network/integration/v1/sites/.../firewall/policies/ordering`.

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

## Worked Example — DNS Egress Lock (EGR-02)

Force every client to use the approved DNS resolvers by blocking direct DNS (53) and DNS-over-TLS (853) to the External zone. Create one BLOCK per client zone (Internal, Hotspot, IoT, DMZ, VPN — whichever carry client networks on this controller). DNS-over-HTTPS (443) is not addressable at this layer and is out of scope. Use `ip_version: "BOTH"` and `connection_state_type: "ALL"` so IPv6 clients cannot route around the rule.

The shape depends on where the approved resolvers live.

Before creating anything, list the existing policies for the zone pair by ascending `index` (`unifi_list_firewall_policies`, `summary: false`). New custom policies append after existing custom policies and before the controller's built-ins, so an existing ALLOW to External that covers port 53 (a `port_matching_type: ANY` allow counts) is evaluated first and leaves the new BLOCK inert. Narrow or move such a policy before creating.

**Approved resolvers are external** (e.g. a public resolver): allow the resolver IPs first, then block the rest. Create the ALLOW before the BLOCK, since creation order is evaluation order among custom policies.

```json
{
  "name": "EGR-02 Allow approved DNS resolvers",
  "action": "ALLOW",
  "protocol": "tcp_udp",
  "ip_version": "BOTH",
  "source":      { "zone_id": "<client_zone_id>", "matching_target": "ANY" },
  "destination": {
    "zone_id": "<external_zone_id>",
    "matching_target": "IP",
    "matching_target_type": "SPECIFIC",
    "ips": ["<resolver_ipv4>", "<resolver_ipv6>"],
    "port_matching_type": "SPECIFIC",
    "port": "53,853"
  }
}
```

```json
{
  "name": "EGR-02 Block other external DNS",
  "action": "BLOCK",
  "protocol": "tcp_udp",
  "ip_version": "BOTH",
  "connection_state_type": "ALL",
  "source":      { "zone_id": "<client_zone_id>", "matching_target": "ANY" },
  "destination": {
    "zone_id": "<external_zone_id>",
    "matching_target": "ANY",
    "port_matching_type": "SPECIFIC",
    "port": "53,853"
  }
}
```

**Approved resolver is local** (a Pi-hole or similar in an internal zone): a destination ALLOW never matches, because the resolver is not in the External zone, and a plain BLOCK would cut the resolver's own upstream queries and take DNS down for every VLAN. Exempt the resolver on the **source** side instead, so only it may reach external DNS:

```json
{
  "name": "EGR-02 Block external DNS except resolver (IPv4)",
  "action": "BLOCK",
  "protocol": "tcp_udp",
  "ip_version": "IPV4",
  "connection_state_type": "ALL",
  "source": {
    "zone_id": "<client_zone_id>",
    "matching_target": "IP",
    "matching_target_type": "OBJECT",
    "ip_group_id": "<resolver_address_group_id>",
    "match_opposite_ips": true
  },
  "destination": {
    "zone_id": "<external_zone_id>",
    "matching_target": "ANY",
    "port_matching_type": "SPECIFIC",
    "port": "53,853"
  }
}
```

Create the resolver address group with `unifi_create_firewall_group` (`group_type: address-group`). This policy is IPv4-only on purpose: an `address-group` cannot hold an IPv6 address, so an `ip_version: BOTH` policy could not exempt the resolver on its IPv6 leg and would block the resolver's own IPv6 upstream. On a dual-stack network add a second policy with `ip_version: IPV6` whose `ip_group_id` is an `ipv6-address-group` holding the resolver's IPv6 address. Repeat for each client zone; the resolver's own zone needs it too.

**The gateway is the resolver** (clients use the UniFi gateway's own DNS): either recipe is safe. The gateway's upstream queries originate in the Gateway zone, which `<client zone>` → External policies never see.

If a policy lands in the wrong position, `unifi_reorder_firewall_policies` moves it; that tool needs `UNIFI_API_KEY` and the integration UUIDs from `unifi_get_firewall_policy_ordering`.

---

## Client (MAC) Targeting

`matching_target: "CLIENT"` with `client_macs: [...]` matches specific clients on either side of a policy. MACs are lower-cased before they reach the controller. For switch-level (L2) enforcement that does not pass through the gateway, `unifi_create_acl_rule` with `source_macs=[...]` remains the right tool.

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
