# UniFi Network Security Benchmarks

This document defines deterministic checks for the firewall auditor skill. Each benchmark maps to a specific condition verifiable via MCP tools, with a defined severity and remediation path. The auditor skill walks these benchmarks in order, builds a per-instance findings list, and pipes the findings through `scripts/unifi-firewall-score` to produce the canonical score.

---

## Segmentation Benchmarks

### SEG-01: IoT VLAN Inter-VLAN Isolation

**Name:** IoT-to-LAN block rule exists

**What to check:** Verify at least one enabled firewall rule exists that blocks traffic from the IoT VLAN (source) to RFC 1918 private address ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16), excluding the IoT subnet itself. The rule must be enabled and positioned before any allow rules for the same traffic.

**MCP tools needed:**
- `list_firewall_rules` — retrieve all firewall rules
- `list_networks` — identify IoT VLAN subnet and VLAN ID
- `list_firewall_groups` — check if RFC 1918 ranges are grouped

**Severity:** critical

**How to fix:** Create a V2 zone-based block rule from the IoT zone to the Internal/Private zone. Discover zone IDs via `unifi_list_firewall_zones`. Place this rule before any inter-zone allow rules.

```yaml
# Security intent: deny all IoT-zone traffic into the Internal/Private zone.
unifi_create_firewall_policy:
  name: "SEG-01 IoT to Internal block"
  action: REJECT
  enabled: true
  source:
    zone_id: <IoT zone ID>
    matching_target: ANY
  destination:
    zone_id: <Internal/Private zone ID>
    matching_target: ANY
```

---

### SEG-02: Guest VLAN Internet-Only Access

**Name:** Guest network restricted to internet egress only

**What to check:** Verify the guest VLAN has an enabled firewall rule blocking access to all private/local subnets (RFC 1918). Additionally verify no allow rules exist for guest-to-LAN traffic above the block rule in rule index order.

**MCP tools needed:**
- `list_firewall_rules` — retrieve all rules, check ruleset, action, source, destination
- `list_networks` — identify guest network VLAN and subnet
- `list_wlans` — confirm which WLAN maps to the guest network

**Severity:** critical

**How to fix:** Create a V2 zone-based block rule from the Guest/Hotspot zone to the Internal/Private zone. Ensure no allow rules covering the same traffic exist with a lower index.

```yaml
# Security intent: deny all Guest-zone traffic into the Internal/Private zone.
unifi_create_firewall_policy:
  name: "SEG-02 Guest to Internal block"
  action: REJECT
  enabled: true
  source:
    zone_id: <Guest/Hotspot zone ID>
    matching_target: ANY
  destination:
    zone_id: <Internal/Private zone ID>
    matching_target: ANY
```

---

### SEG-03: Management VLAN Access Restriction

**Name:** Management VLAN accessible only from admin sources

**What to check:** Verify the management VLAN has an inbound rule that blocks traffic from non-management VLANs. Check that only explicitly whitelisted source IPs or groups (admin workstations) are permitted to initiate connections to the management VLAN.

**MCP tools needed:**
- `list_firewall_rules` — find rules referencing management VLAN as destination
- `list_networks` — identify management VLAN subnet and VLAN ID
- `list_firewall_groups` — check for admin workstation IP group definitions

**Severity:** critical

**How to fix:** Create two V2 rules: (1) ALLOW from a zone scoped to the admin IPs (or an admin zone) to the management network, (2) BLOCK everything else into the management network. The ALLOW rule must have a lower index than the BLOCK rule.

```yaml
# Security intent: only explicitly whitelisted admin IPs may reach the management network.
# Rule 1 — admin allow:
unifi_create_firewall_policy:
  name: "SEG-03 Allow admin IPs to management"
  action: ALLOW
  enabled: true
  source:
    zone_id: <Internal zone ID>
    matching_target: IP
    matching_target_type: SPECIFIC
    ips: [<admin workstation IP / CIDR>, ...]
  destination:
    zone_id: <Internal zone ID>
    matching_target: NETWORK
    matching_target_type: OBJECT
    network_ids: [<management network ID>]

# Rule 2 — catch-all block (must follow rule 1):
unifi_create_firewall_policy:
  name: "SEG-03 Block non-admin to management"
  action: BLOCK
  enabled: true
  source:
    zone_id: <Internal zone ID>
    matching_target: ANY
  destination:
    zone_id: <Internal zone ID>
    matching_target: NETWORK
    matching_target_type: OBJECT
    network_ids: [<management network ID>]
```

**MAC-based admin allow list:** If the admin sources are identified by client MAC rather than IP, V2 firewall policies cannot match by client MAC — use `unifi_create_acl_rule` instead. The example below restricts management-VLAN access to a specific set of admin workstations by MAC:

```yaml
# Security intent: only the listed admin MACs may originate traffic on the management VLAN.
# ACL rules apply at Layer 2 within a VLAN, so this complements the firewall rules above
# by handling the case where admin identity is keyed on MAC rather than IP.
unifi_create_acl_rule:
  name: "SEG-03 Allow admin MACs on management VLAN"
  acl_index: 10                              # lower = evaluated first
  action: "ALLOW"
  network_id: "<management network ID>"      # from unifi_list_networks
  source_macs: ["<admin-mac-1>", "<admin-mac-2>", ...]
  destination_macs: []                       # empty = any destination
  enabled: true

unifi_create_acl_rule:
  name: "SEG-03 Block all other MACs on management VLAN"
  acl_index: 20                              # higher index = evaluated after the allow
  action: "BLOCK"
  network_id: "<management network ID>"
  source_macs: []                            # empty = any source
  destination_macs: []
  enabled: true
```

Choose the firewall path or the ACL path based on how admin identity is actually tracked in the deployment — both implement the SEG-03 intent, the difference is whether the allow-list keys on IP/CIDR or on MAC.


---

### SEG-04: Explicit Inter-VLAN Policies Required

**Name:** No implicit allow between VLANs

**What to check:** For every VLAN pair (source, destination) identified in `list_networks`, verify that at least one explicit firewall rule exists governing traffic between them (either allow or block). A pair with no matching rule relies on default behavior — flag this as a finding. Exclude the VLAN's own subnet (intra-VLAN traffic is out of scope).

**MCP tools needed:**
- `list_networks` — enumerate all VLANs and their subnets
- `list_firewall_rules` — enumerate all rules and map coverage
- `list_firewall_groups` — resolve group memberships for rule sources/destinations

**Severity:** warning

**How to fix:** Audit each VLAN pair and create explicit ALLOW or REJECT/BLOCK rules covering the traffic intent. Document the intent in the rule name.

```yaml
# Security intent: make every inter-VLAN flow explicit (no implicit reliance on default).
unifi_create_firewall_policy:
  name: "SEG-04 Explicit <src>-to-<dst> policy"
  action: <ALLOW|REJECT|BLOCK>
  enabled: true
  source:
    zone_id: <source zone ID>
    matching_target: NETWORK
    matching_target_type: OBJECT
    network_ids: [<source VLAN network ID>]
  destination:
    zone_id: <destination zone ID>
    matching_target: NETWORK
    matching_target_type: OBJECT
    network_ids: [<destination VLAN network ID>]
```

---

## Egress Control Benchmarks

### EGR-01: High-Risk VLAN Outbound Filtering

**Name:** IoT and Guest VLANs have outbound (External-zone) filtering

**What to check:** Verify that the IoT and guest VLANs have at least one enabled V2 firewall policy whose source references their network and whose destination zone is the External zone. The rule should restrict outbound traffic — for example, scoping the destination to specific allowed IPs/CIDRs, or terminating with a catch-all BLOCK to External. No outbound rule for these high-risk zones is a finding.

**MCP tools needed:**
- `unifi_list_firewall_policies` — find policies whose `source.network_ids` references IoT/guest networks and whose `destination.zone_id` is the External zone
- `unifi_list_firewall_zones` — identify the External zone ID
- `unifi_list_networks` — identify IoT and guest VLAN network IDs

**Severity:** warning

**How to fix:** Create rules from the IoT/Guest zones to the External zone allowing only required outbound services, then terminate with a catch-all BLOCK rule for unmatched traffic.

```yaml
# Security intent: deny unmatched outbound from high-risk zone (IoT/Guest) to External.
unifi_create_firewall_policy:
  name: "EGR-01 IoT default outbound deny"
  action: BLOCK
  enabled: true
  source:
    zone_id: <IoT zone ID>
    matching_target: NETWORK
    matching_target_type: OBJECT
    network_ids: [<IoT network ID>]
  destination:
    zone_id: <External zone ID>
    matching_target: ANY
```

---

### EGR-02: DNS Forced Through Approved Resolvers

**Name:** DNS traffic redirected to approved resolvers

**What to check:** Verify a LAN-in or LAN-local rule exists that intercepts DNS traffic (UDP/TCP port 53) from client VLANs and either blocks external DNS or redirects to an approved resolver IP. Check that no rule explicitly allows port 53 to arbitrary destinations before such a rule.

**MCP tools needed:**
- `list_firewall_rules` — check for port 53 rules in LAN_IN and LAN_LOCAL rulesets
- `list_networks` — enumerate client-facing VLANs

**Severity:** warning

**How to fix:** This benchmark cannot be fully enforced through the firewall surface alone. V2 zone-based firewall policies do not match on port, so a literal "block UDP/TCP 53 except to approved resolvers" rule isn't expressible at this layer. The benchmark therefore splits into a **partial firewall fix** (what MCP can do today) and a **manual UniFi UI step** (the rest):

**Part 1 — partial firewall fix (programmatic):** Allow client traffic to reach approved resolver IPs externally. This handles the legitimate-DNS path but does not block port-53 traffic to other destinations.

```yaml
# Security intent: clients may reach the approved DNS resolver IPs externally.
# This is the firewall-layer half of the benchmark.
unifi_create_firewall_policy:
  name: "EGR-02 Allow approved DNS resolvers"
  action: ALLOW
  enabled: true
  source:
    zone_id: <client zone ID>
    matching_target: ANY
  destination:
    zone_id: <External zone ID>
    matching_target: IP
    matching_target_type: SPECIFIC
    ips: [<approved resolver IP>, ...]
```

**Part 2 — full enforcement (operator action in the UniFi UI):** To block direct egress on port 53 to non-approved resolvers and prevent client-side DNS bypass, configure either:

- A **traffic rule** (UniFi UI: Settings → Security → Traffic Rules) that drops outbound TCP/UDP port 53 from client networks, OR
- A **DNS-redirect** policy (UniFi UI: Settings → Security → DNS Filtering or Network → DNS) that intercepts all client DNS and forwards to the approved resolver.

Neither is currently exposed through MCP tooling. Tracked separately for future MCP coverage.

**Auditing this benchmark:** A programmatic audit can confirm Part 1 (the firewall ALLOW rule exists pointing at approved resolver IPs). Part 2 cannot be confirmed via MCP today and must be checked manually in the UniFi UI. Flag the benchmark as `partial-pass` if Part 1 is satisfied but Part 2 cannot be verified programmatically.


---

### EGR-03: Known Malicious IP Ranges Blocked

**Name:** Threat intelligence IP block groups defined and applied

**What to check:** Verify at least one IP group exists named with a threat/block indicator (e.g., contains "threat", "block", "malicious", or "blacklist" in the name). Verify that IP group is referenced in at least one enabled WAN_OUT or LAN_IN drop rule. An empty IP group with no associated rule is also a finding.

**MCP tools needed:**
- `list_firewall_groups` — find threat-related groups, check member count
- `list_firewall_rules` — verify group is referenced in enabled drop rules

**Severity:** informational

**How to fix:** Create a firewall group of known malicious CIDRs (`unifi_create_firewall_group` with the threat-intel addresses), then reference its members as the destination IPs of a V2 BLOCK rule. Alternatively express the destination as `matching_target: IP` with the explicit list of CIDRs.

```yaml
# Security intent: deny outbound from the client zone to known malicious IP ranges.
unifi_create_firewall_policy:
  name: "EGR-03 Block known malicious destinations"
  action: BLOCK
  enabled: true
  source:
    zone_id: <client zone ID>
    matching_target: ANY
  destination:
    zone_id: <External zone ID>
    matching_target: IP
    matching_target_type: SPECIFIC
    ips: [<malicious CIDR>, ...]
```


---

## Rule Hygiene Benchmarks

### HYG-01: No Disabled Rules Duplicating Enabled Rules

**Name:** No redundant disabled rules

**What to check:** For every disabled firewall rule, check whether an enabled rule exists with an identical or overlapping source, destination, port, and action. If a disabled rule's traffic is fully covered by an enabled rule, the disabled rule is redundant. Report the disabled rule name and the matching enabled rule name.

**MCP tools needed:**
- `list_firewall_rules` — retrieve all rules with enabled status, source, destination, port, action fields

**Severity:** warning

**How to fix:** Delete the disabled rule if it is fully shadowed by an enabled rule. If the disabled rule was for rollback purposes, document this in the rule description.

```
delete_firewall_rule:
  rule_id: <redundant disabled rule ID>
```

---

### HYG-02: No Conflicting Rules for Same Traffic

**Name:** No rules with conflicting actions for identical traffic

**What to check:** For each pair of enabled rules with overlapping or identical source/destination/port criteria, check whether their actions conflict (one allows, one drops). When a conflict exists, determine whether rule index ordering resolves the conflict predictably. Flag cases where index order causes the less restrictive rule to win.

**MCP tools needed:**
- `list_firewall_rules` — retrieve all enabled rules with index, action, source, destination, port fields

**Severity:** critical

**How to fix:** Reorder rules so the more restrictive (drop) rule has a lower index than the allow rule, or remove one of the conflicting rules after determining the intended behavior.

```
update_firewall_rule:
  rule_id: <rule ID>
  rule_index: <corrected index>
```

---

### HYG-03: No Rules Targeting Non-Existent Networks or Empty Groups

**Name:** All rule references resolve to valid objects

**What to check:** For every firewall rule that references a network ID or IP group ID in its source or destination, verify that the referenced object exists in `list_networks` or `list_firewall_groups` respectively. Also verify that referenced IP groups have at least one member. Report any rule with a dangling reference.

**MCP tools needed:**
- `list_firewall_rules` — extract network and IP group references from each rule
- `list_networks` — validate network IDs exist
- `list_firewall_groups` — validate group IDs exist and are non-empty

**Severity:** warning

**How to fix:** Either delete the rule with the dangling reference or recreate the missing network/IP group it targets.

```
delete_firewall_rule:
  rule_id: <rule with dangling reference>
```

---

### HYG-04: Rules Have Descriptive Names

**Name:** No rules with default or auto-generated names

**What to check:** Inspect the name/description field of every firewall rule. Flag rules whose names match default patterns: empty string, "Rule", "New Rule", "Untitled", numeric-only names, or names matching the pattern `Rule \d+`. A rule with no human-readable description is informational; a rule with a default placeholder name is a warning.

**MCP tools needed:**
- `list_firewall_rules` — retrieve name and description fields for all rules

**Severity:** warning

**How to fix:** Rename flagged rules with descriptive names that communicate traffic intent, source, destination, and purpose.

```
update_firewall_rule:
  rule_id: <rule ID>
  name: "<descriptive name>"
  description: "<intent and traffic details>"
```

---

### HYG-05: No Shadowing by Broader Rules

**Name:** Specific rules not unreachable due to broader rule above them

**What to check:** For each pair of enabled rules in the same ruleset, check whether a rule with a lower index has a source/destination/port that is a superset of a rule with a higher index and the same action. The higher-index rule is then unreachable (shadowed). Also flag cases where a higher-index specific allow rule is preceded by a lower-index broad drop rule (rendering the specific allow dead).

**MCP tools needed:**
- `list_firewall_rules` — retrieve all enabled rules with index, action, source, destination, port, and ruleset fields

**Severity:** warning

**How to fix:** Reorder rules so specific rules appear before broader rules in the index, or remove the unreachable rule if it is no longer needed.

```
update_firewall_rule:
  rule_id: <shadowed rule ID>
  rule_index: <index before the broader rule>
```

---

## Topology Benchmarks

### TOP-01: All Adopted Devices Online

**Name:** No adopted devices in offline state

**What to check:** Retrieve all devices via `list_devices`. For every device with `state != 1` (not connected/online), report it as a finding. Include the device name, MAC address, device type, and last-seen timestamp in the finding detail.

**MCP tools needed:**
- `list_devices` — retrieve all devices with state, name, mac, type, last_seen fields

**Severity:** critical

**How to fix:** Investigate the offline device — check physical connectivity, power status, and controller adoption status. If the device is decommissioned, remove it from the controller.

```
# Investigation only — no automated fix available
get_device_details:
  mac: <device MAC>
```

---

### TOP-02: Firmware Current on All Devices

**Name:** No devices with available firmware upgrades pending

**What to check:** Retrieve all devices via `list_devices`. For every device where `upgradeable = true`, report it as a finding with the device name, current firmware version, and available firmware version. Devices running outdated firmware may have known security vulnerabilities.

**MCP tools needed:**
- `list_devices` — retrieve all devices with upgradeable, version, upgrade_to_firmware fields

**Severity:** warning

**How to fix:** Upgrade the device firmware. Schedule during a maintenance window.

```
upgrade_device_firmware:
  mac: <device MAC>
```

---

### TOP-03: Consistent VLAN Assignments Across Switch Uplinks

**Name:** All switch uplinks carry consistent VLAN trunk configurations

**What to check:** For each managed switch, retrieve its port configuration via `list_switch_ports` or `get_device_details`. For each trunk/uplink port, verify that the set of allowed VLANs matches the expected set defined by the connected VLANs in `list_networks`. Flag any uplink that is missing a VLAN that exists on the network, or carries a VLAN not defined in `list_networks`.

**MCP tools needed:**
- `list_devices` — identify managed switches by type
- `get_device_details` — retrieve port profiles and VLAN assignments per port
- `list_networks` — enumerate defined VLANs

**Severity:** warning

**How to fix:** Update the switch port profile to include all required VLANs, or remove undefined VLAN IDs from the port profile.

```
update_device_port_profile:
  device_mac: <switch MAC>
  port_idx: <uplink port index>
  profile: <corrected port profile>
```

---

### TOP-04: No Orphaned Port Profiles

**Name:** All defined port profiles are in use

**What to check:** Retrieve all port profiles via `list_port_profiles`. For each profile, check whether it is referenced by at least one port on at least one switch (via `get_device_details`). Any profile with zero references across all devices is orphaned. Report profile name and ID.

**MCP tools needed:**
- `list_port_profiles` — retrieve all defined port profiles with IDs and names
- `list_devices` — enumerate managed switches
- `get_device_details` — retrieve per-port profile assignments

**Severity:** informational

**How to fix:** Delete the orphaned port profile to reduce configuration clutter.

```
delete_port_profile:
  profile_id: <orphaned profile ID>
```

---

## Benchmark Summary Table

| ID | Category | Name | Severity |
|----|----------|------|----------|
| SEG-01 | Segmentation | IoT-to-LAN block rule exists | critical |
| SEG-02 | Segmentation | Guest network restricted to internet egress only | critical |
| SEG-03 | Segmentation | Management VLAN accessible only from admin sources | critical |
| SEG-04 | Segmentation | No implicit allow between VLANs | warning |
| EGR-01 | Egress Control | IoT and Guest VLANs have outbound filtering | warning |
| EGR-02 | Egress Control | DNS forced through approved resolvers | warning |
| EGR-03 | Egress Control | Known malicious IP ranges blocked | informational |
| HYG-01 | Rule Hygiene | No redundant disabled rules | warning |
| HYG-02 | Rule Hygiene | No conflicting rules for same traffic | critical |
| HYG-03 | Rule Hygiene | All rule references resolve to valid objects | warning |
| HYG-04 | Rule Hygiene | Rules have descriptive names | warning |
| HYG-05 | Rule Hygiene | No shadowing by broader rules | warning |
| TOP-01 | Topology | All adopted devices online | critical |
| TOP-02 | Topology | Firmware current on all devices | warning |
| TOP-03 | Topology | Consistent VLAN assignments across switch uplinks | warning |
| TOP-04 | Topology | No orphaned port profiles | informational |
