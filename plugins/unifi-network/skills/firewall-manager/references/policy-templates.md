# Firewall Policy Templates

Pre-built policy recipes for common network security scenarios. Each template documents the goal, required parameters, tools to call, and expected outcome. All templates emit V2 zone-based payloads for `unifi_create_firewall_policy`.

For machine-readable definitions, see `policy-templates.yaml`.

---

## Template 1: IoT Isolation

**Name:** `iot-isolation`

**Description:**
Blocks IoT devices from initiating connections to the private/internal zone while still allowing them to reach the internet (External zone). This is the most common segmentation pattern for home and small office networks with smart devices, cameras, or home automation hubs.

**Why you need this:**
IoT devices are frequent targets for compromise. Once infected, they can be used to attack other devices on the same network. Isolating them to internet-only access limits the blast radius of a compromised device.

**Parameters required:**
- `iot_zone_id` — Zone ID for the IoT zone (from `unifi_list_firewall_zones`)
- `private_zone_id` — Zone ID for the Internal/Private zone

**Tools to call:**
1. `unifi_list_firewall_zones` — discover zone IDs
2. `unifi_create_firewall_policy` — create the V2 block rule

**Rule details:**
- Action: `REJECT`
- Source: IoT zone, `matching_target: ANY`
- Destination: Internal/Private zone, `matching_target: ANY`
- Protocol: `all`

**Expected outcome:**
IoT devices can reach the External (internet) zone normally. Any attempt to connect to devices in the Internal zone (printers, NAS, computers) is rejected immediately. Devices in the Internal zone can still initiate connections to IoT devices if needed.

**Additional consideration:**
If you also want to prevent the Internal zone from reaching IoT devices, create a second rule with source and destination zone IDs swapped.

---

## Template 2: Guest Lockdown

**Name:** `guest-lockdown`

**Description:**
Restricts the guest zone to internet-only access, blocking all access to private/internal LAN resources (NAS, printers, management interfaces, internal servers).

**Why you need this:**
Guest networks should never have access to internal resources. This rule enforces the separation even if the UniFi guest network isolation setting is misconfigured or bypassed.

**Parameters required:**
- `guest_zone_id` — Guest/Hotspot zone ID
- `private_zone_id` — Internal/Private zone ID

**Tools to call:**
1. `unifi_list_firewall_zones` — discover zone IDs
2. `unifi_create_firewall_policy` — create the V2 block rule

**Rule details:**
- Action: `REJECT`
- Source: Guest zone, `matching_target: ANY`
- Destination: Internal/Private zone, `matching_target: ANY`
- Protocol: `all`

**Expected outcome:**
Guests can browse the internet freely. Any attempt to access internal IPs, printers, NAS shares, or router management pages is rejected.

---

## Template 3: Kids Content Filter (Time-Based)

**Name:** `kids-content-filter`

**Description:**
Blocks egress from a kids VLAN to the internet during specific hours (e.g., school nights, bedtime). Uses zone-based source scoped to the kids network plus a time schedule.

**Why you need this:**
Time-based parental controls allow full internet access during allowed hours while enforcing limits during study time, bedtime, or family time — without manual toggling.

**Parameters required:**
- `kids_zone_id` — Kids zone ID
- `external_zone_id` — External (WAN/internet) zone ID
- `kids_network_id` — Kids VLAN network ID (`unifi_list_networks`)
- `block_days` — Days to enforce the block (e.g., `["mon","tue","wed","thu","fri"]`)
- `block_start` — Block start time in 24-hour format (e.g., `"21:00"`)
- `block_end` — Block end time in 24-hour format (e.g., `"07:00"`)

**Tools to call:**
1. `unifi_list_firewall_zones` — discover zone IDs
2. `unifi_list_networks` — discover the kids network ID
3. `unifi_create_firewall_policy` — create the time-scheduled rule

**Rule details:**
- Action: `REJECT`
- Source: Kids zone, `matching_target: NETWORK`, `matching_target_type: OBJECT`, `network_ids: [<kids_network_id>]`
- Destination: External zone, `matching_target: ANY`
- Schedule: `mode: CUSTOM` with selected days and time range

**Expected outcome:**
During allowed hours, all internet access is unrestricted. During block hours on the selected days, the kids network has no internet egress.

**Note:** The V2 zone-based firewall does **not** match by DPI category (TikTok, YouTube, Steam, etc.). For application-level filtering, complement this rule with `unifi_update_content_filter` (DPI-aware) or other content-filter tooling.

---

## Template 4: Block BitTorrent / P2P Egress

**Name:** `block-bittorrent`

**Description:**
Blocks egress from a target network to the External zone. The V2 zone-based firewall does not have DPI-category matching, so this template is a coarse "no internet from this network" rule. For protocol-aware P2P blocking, layer DPI-aware tooling on top.

**Parameters required:**
- `target_zone_id` — Source zone ID for the target VLAN
- `external_zone_id` — External zone ID
- `target_network_id` — Network ID to restrict

**Tools to call:**
1. `unifi_list_firewall_zones`
2. `unifi_list_networks`
3. `unifi_create_firewall_policy`

**Rule details:**
- Action: `BLOCK`
- Source: target zone, `matching_target: NETWORK`, `matching_target_type: OBJECT`, `network_ids: [<target_network_id>]`
- Destination: External zone, `matching_target: ANY`

**Note:** Using `BLOCK` rather than `REJECT` avoids leaking firewall presence to external peers.

---

## Template 5: Work VPN Split Tunnel

**Name:** `work-vpn-split-tunnel`

**Description:**
Allows the work zone to reach a corporate IP range over the internet (which a separate routing policy then directs through the VPN tunnel) while leaving local access intact.

**Parameters required:**
- `work_zone_id` — Work zone ID
- `external_zone_id` — External zone ID
- `corporate_ips` — List of corporate IP/CIDR strings (e.g., `["10.0.0.0/8","172.16.0.0/12"]`)

**Tools to call:**
1. `unifi_list_firewall_zones`
2. `unifi_create_firewall_policy`

**Rule details:**
- Action: `ALLOW`
- Source: Work zone, `matching_target: ANY`
- Destination: External zone, `matching_target: IP`, `matching_target_type: SPECIFIC`, `ips: <corporate_ips>`

**Note:** Full split-tunnel configuration may also require static routes. Use `unifi_list_static_routes` to review existing routing configuration.

---

## Template 6: Camera Isolation

**Name:** `camera-isolation`

**Description:**
Locks IP cameras to communicate only with their designated NVR. Blocks all other traffic from the camera zone to the internal zone.

**Parameters required:**
- `camera_zone_id` — Camera zone ID
- `internal_zone_id` — Internal zone ID where the NVR lives
- `nvr_ips` — List of NVR IPs (e.g., `["192.168.50.10"]`)

**Tools to call:**
1. `unifi_list_firewall_zones`
2. `unifi_create_firewall_policy` (twice — once per rule)

**Rule details:**

Rule 1 — Allow NVR:
- Action: `ALLOW`
- Source: Camera zone, `matching_target: ANY`
- Destination: Internal zone, `matching_target: IP`, `matching_target_type: SPECIFIC`, `ips: <nvr_ips>`

Rule 2 — Catch-all block:
- Action: `BLOCK`
- Source: Camera zone, `matching_target: ANY`
- Destination: Internal zone, `matching_target: ANY`

**Important:** Rule order matters. The allow rule must be evaluated before the catch-all block. Confirm rule ordering with `unifi_list_firewall_policies` after creation.

---

## Template 7: DNS Egress Lock (External Resolvers)

**Name:** `dns-egress-lock-external`

**Description:**
Forces clients in a zone to use approved external DNS resolvers. Allows DNS (53) and DNS-over-TLS (853) to the resolver IPs, then blocks those ports to every other external destination. Run once per zone that carries client networks.

**Parameters required:**
- `client_zone_id` — Client zone ID
- `external_zone_id` — External zone ID
- `resolver_ips` — Approved resolver IPs, IPv4 and IPv6 (e.g., `["9.9.9.9", "2620:fe::fe"]`)

**Tools to call:**
1. `unifi_list_firewall_zones`
2. `unifi_create_firewall_policy` (twice — allow first, then block)

**Rule details:**

Rule 1 — Allow approved resolvers:
- Action: `ALLOW`, protocol `tcp_udp`, `ip_version: BOTH`
- Source: Client zone, `matching_target: ANY`
- Destination: External zone, `matching_target: IP`, `matching_target_type: SPECIFIC`, `ips: <resolver_ips>`, `port_matching_type: SPECIFIC`, `port: "53,853"`

Rule 2 — Block other external DNS:
- Action: `BLOCK`, protocol `tcp_udp`, `ip_version: BOTH`, `connection_state_type: ALL`
- Source: Client zone, `matching_target: ANY`
- Destination: External zone, `matching_target: ANY`, `port_matching_type: SPECIFIC`, `port: "53,853"`

**Important:** Create the allow rule first. New custom policies append after existing custom policies and before built-ins, so creation order is evaluation order. DNS-over-HTTPS (443) is not addressable at this layer. When the approved resolver lives on the LAN, use Template 8 instead.

---

## Template 8: DNS Egress Lock (Local Resolver)

**Name:** `dns-egress-lock-local`

**Description:**
Forces clients to a local resolver such as a Pi-hole by blocking DNS (53) and DNS-over-TLS (853) to the External zone for every source except the resolver itself. Run once per zone that carries client networks, including the resolver's own zone.

**Parameters required:**
- `client_zone_id` — Client zone ID
- `external_zone_id` — External zone ID
- `resolver_group_id` — Address group holding the resolver IP(s) (`unifi_create_firewall_group`, `group_type: address-group`)

**Tools to call:**
1. `unifi_list_firewall_zones`
2. `unifi_list_firewall_groups` (or `unifi_create_firewall_group` for the resolver group)
3. `unifi_create_firewall_policy`

**Rule details:**

- Action: `BLOCK`, protocol `tcp_udp`, `ip_version: BOTH`, `connection_state_type: ALL`
- Source: Client zone, `matching_target: IP`, `matching_target_type: OBJECT`, `ip_group_id: <resolver_group_id>`, `match_opposite_ips: true`
- Destination: External zone, `matching_target: ANY`, `port_matching_type: SPECIFIC`, `port: "53,853"`

**Important:** The resolver is exempted on the source side. A destination ALLOW cannot name a LAN resolver from the External zone, and a plain BLOCK would cut the resolver's own upstream queries and take DNS down for every VLAN. An IPv6 resolver needs a separate `ipv6-address-group` and an `ip_version: IPV6` copy of the policy. Safe when the gateway itself is the resolver: its upstream queries originate in the Gateway zone.
