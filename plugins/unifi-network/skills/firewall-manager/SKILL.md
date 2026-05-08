---
name: firewall-manager
description: Manage UniFi firewall policies using natural language — create, modify, and review firewall rules, content filters, and traffic policies. Use when asked to block traffic, create firewall rules, manage content filtering, set up time-based access controls, or review firewall configuration.
---

# Firewall Manager

You are managing firewall policies on a UniFi network. Your goal is to translate natural-language requests into the correct firewall tool calls, always previewing before executing. Use the scripts and reference documents in this skill directory to work safely and efficiently.

## Required MCP Server

This skill requires the `unifi-network` MCP server. Use `unifi_tool_index` to verify available tools, then `unifi_execute` to call them.

---

## 1. Setup Check

Before doing anything else, confirm the environment is ready:

- Check that `UNIFI_NETWORK_HOST` (or `UNIFI_HOST`) is set. If not, tell the user:
  > "UNIFI_NETWORK_HOST is not configured. Please run the setup flow at `/setup` before using this skill."
- Verify the MCP server is reachable by calling `unifi_tool_index`.

---

## 2. Before Making Changes

**Always export a snapshot before any mutation.** This gives you a before-state to diff against and a rollback reference.

```bash
python scripts/export-policies.py
```

Options:
- `--mcp-url URL` — override MCP server URL if not using the default
- `--state-dir DIR` — override the directory where snapshots are saved

The script saves a timestamped JSON snapshot (e.g., `firewall-snapshots/firewall_20260318_143200Z.json`) containing all policies, zones, and IP groups. Run this before **every** mutating operation in the session.

---

## 3. Using Templates

For common security scenarios, use pre-built templates rather than constructing rules from scratch.

**List available templates:**
```bash
python scripts/apply-template.py --list
```

**Apply a template:**
```bash
python scripts/apply-template.py --template <template-name> --param key=value --param key2=value2
```

The script reads `references/policy-templates.yaml`, substitutes parameters, and outputs the MCP tool call payload. It does **not** execute — you review the output, then confirm with the user before calling the tool.

**Example — IoT isolation:**
```bash
python scripts/apply-template.py --template iot-isolation \
  --param iot_network=IoT \
  --param private_network=Main
```

**Available templates** (see `references/policy-templates.md` for full details):

| Template | Description |
|----------|-------------|
| `iot-isolation` | Block IoT VLAN from reaching the main LAN |
| `guest-lockdown` | Restrict guest network to internet-only |
| `kids-content-filter` | Time-based social media and gaming block by DPI category |
| `block-bittorrent` | Block P2P/BitTorrent traffic via DPI |
| `work-vpn-split-tunnel` | Allow corporate VPN while keeping local LAN accessible |
| `camera-isolation` | Lock IP cameras to NVR-only communication |

For parameter details, required tool calls, and expected outcomes for each template, see `references/policy-templates.md`.

---

## 4. Creating Custom Rules

When no template fits, create rules manually. Consult the references before writing any policy payload.

- **`references/firewall-schema.md`** — complete V2 schema reference: zones, actions (`ALLOW`/`BLOCK`/`REJECT`), `matching_target` / `matching_target_type` combinations, port matching, protocols, connection states, and schedule format.
- **`references/dpi-categories.md`** — application-aware blocking. When users mention app names (TikTok, YouTube, Steam, BitTorrent), find the right DPI category here. Always call `unifi_get_dpi_stats` to confirm the exact category IDs on the user's controller before building DPI rules.

**Tool selection:**
- `unifi_create_firewall_policy` — creates V2 zone-based firewall policies. Required: `name`, `action` (`ALLOW`/`BLOCK`/`REJECT`), `source` (`zone_id` + `matching_target`), `destination` (same structure). Use `unifi_list_firewall_zones` to discover zone IDs and `unifi_list_networks` to discover network IDs before constructing the payload. See `references/firewall-schema.md` for the V2 input format and the `matching_target` / `matching_target_type` combinations.

---

## 5. Verifying Changes

After every mutation, run the diff script to confirm the change matches intent:

```bash
python scripts/diff-policies.py
```

The script auto-loads the two most recent snapshots in the state directory and shows added, removed, and modified policies. If the diff looks wrong, report it to the user and do not proceed with further changes.

Options:
- `--current FILE` — path to the after-snapshot
- `--previous FILE` — path to the before-snapshot
- `--state-dir DIR` — directory to scan for the two most recent snapshots (default)

---

## 6. Safety Rules

1. **Always preview first** — every mutation returns a preview when called without `confirm=true`. Show the preview to the user before executing.
2. **Never auto-confirm** — wait for explicit user approval before calling with `confirm=true`.
3. **Check permissions** — if a mutation fails with a permission error, tell the user the relevant env var:
   - Create: `UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_CREATE=true`
   - Update: `UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_UPDATE=true`
   - Delete: `UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_DELETE=true` (disabled by default)
4. **Understand the impact** — call `unifi_list_firewall_policies` before creating rules to check for conflicts or redundancy.
5. **Export before mutating** — always run `scripts/export-policies.py` before any create, update, or delete operation (see Section 2).
6. **Diff after mutating** — always run `scripts/diff-policies.py` after applying changes to verify the result (see Section 5).

---

## 7. Common Scenarios

### "Block [app/service] on [network/VLAN]"

1. Run `scripts/export-policies.py` to snapshot current state.
2. Check `references/dpi-categories.md` for the app's DPI category, then call `unifi_get_dpi_stats` to confirm the category ID on this controller.
3. Check `scripts/apply-template.py --list` — if a matching template exists (e.g., `block-bittorrent`), use it.
4. Otherwise: call `unifi_list_networks` and `unifi_list_firewall_zones` to gather IDs, then `unifi_create_firewall_policy` with `action="REJECT"` and zone-based `source`/`destination`.
5. Show preview → wait for confirmation → execute with `confirm=true`.
6. Run `scripts/diff-policies.py` to verify.

### "Block [app] after [time] on [days]"

1. Run `scripts/export-policies.py`.
2. If the `kids-content-filter` template applies, use it with `block_days`, `block_start`, and `block_end` parameters.
3. Otherwise: consult `references/firewall-schema.md` for the schedule format, then use `unifi_create_firewall_policy` with the schedule object.
4. Preview → confirm → diff.

### "Show me all rules affecting [network/VLAN]"

1. `unifi_list_firewall_policies` — get all policies.
2. Filter by source/destination matching the target network.
3. Present as a readable table: name, action (allow/reject/drop), source → destination, enabled status.

### "Are there any conflicting or redundant rules?"

1. `unifi_list_firewall_policies` — get all policies.
2. Analyze for:
   - Rules with the same source/destination but different actions (conflict).
   - Rules that are subsets of broader rules (redundant).
   - Disabled rules that duplicate enabled ones.
3. Report findings with recommendations.

### "Set up IoT isolation / guest lockdown / camera isolation"

1. Run `scripts/export-policies.py`.
2. Run `scripts/apply-template.py --list` and select the matching template.
3. Run `scripts/apply-template.py --template <name> --param ...` to generate the payload.
4. Review the output with the user, then call the indicated tool with `confirm=false` first (preview).
5. Confirm → execute → diff.

See `references/policy-templates.md` for the full parameter list and expected outcome for each template.

### "Clean up / optimize firewall rules"

1. `unifi_list_firewall_policies` — full audit.
2. Run `scripts/export-policies.py` before making any changes.
3. Identify quick wins: disabled rules that can be deleted, redundant rules, shadowed rules.
4. Propose changes one at a time with previews.
5. Diff after each change.
6. For the comprehensive audit workflow, see the `firewall-auditor` skill.

---

## 8. Manual Procedure (Fallback)

Use these direct tool calls when scripts are unavailable (e.g., no Python runtime, running in a sandboxed environment).

### Read tools (always available)
- `unifi_list_firewall_policies` — all firewall policies
- `unifi_get_firewall_policy_details` — full details for one policy by ID
- `unifi_list_firewall_zones` — available zones (Internal, External, DMZ, etc.)
- `unifi_list_firewall_groups` — Firewall groups (address/port) for use in rules
- `unifi_list_networks` — networks/VLANs (needed for targeting specific segments)
- `unifi_get_dpi_stats` — DPI categories available on this controller

### Create
- `unifi_create_firewall_policy` — V2 zone-based create. Pre-resolve zone IDs (`unifi_list_firewall_zones`) and network IDs (`unifi_list_networks`) before constructing the payload.

### Modify
- `unifi_update_firewall_policy` — update specific fields of an existing policy
- `unifi_toggle_firewall_policy` — enable/disable a policy

### Delete
- Deletion requires `UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_DELETE=true` (disabled by default)

**Response pattern for every mutation:**
1. Confirm understanding: "I'll create a firewall policy that blocks [X] on [network]. Let me check the current configuration first."
2. Gather context (list existing rules, networks, zones).
3. Call the create/update tool **without** `confirm=true`.
4. Present the preview clearly.
5. Ask: "Does this look correct? Confirm to apply."
6. On user confirmation, call with `confirm=true`.

---

## 9. Tips

- `unifi_create_firewall_policy` is the canonical create tool. Always discover zone IDs (`unifi_list_firewall_zones`) and network IDs (`unifi_list_networks`) up front, then build the V2 payload. See `references/firewall-schema.md` for the schema.
- Users often say "block" when they mean `REJECT` (sends RST/ICMP unreachable) vs `BLOCK` (silent discard). `REJECT` is usually better for internal networks; `BLOCK` is better for external-facing rules. See `references/firewall-schema.md` for the action comparison table.
- When users mention app names (TikTok, YouTube, Steam), consult `references/dpi-categories.md` first to identify the category group, then confirm the exact ID with `unifi_get_dpi_stats` on the live controller.
- DPI rules can be bypassed by VPNs — if blocking social media or gaming, consider also blocking the VPN/Proxy DPI category. See `references/dpi-categories.md` for the VPN category group.
- Rule order matters for `camera-isolation` and multi-rule templates — confirm ordering with `unifi_list_firewall_policies` after creation, and use `scripts/diff-policies.py` to verify the final state.
- Snapshots from `scripts/export-policies.py` serve as rollback references. If a change causes unexpected behavior, share the before-snapshot path with the user so they can restore manually.
