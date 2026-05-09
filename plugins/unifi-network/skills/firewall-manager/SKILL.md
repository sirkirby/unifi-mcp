---
name: firewall-manager
description: Manage UniFi firewall policies using natural language — create, modify, and review firewall rules, content filters, and traffic policies. Use when asked to block traffic, create firewall rules, manage content filtering, set up time-based access controls, or review firewall configuration.
---

# Firewall Manager

You manage firewall policies on a UniFi network. Translate the user's intent into the right MCP tool calls, always preview before executing, and snapshot state around every mutation so a rollback path always exists.

There are no helper scripts in this skill — only references and tools. You drive the workflow:

- The MCP server provides tools to read, create, update, and toggle policies.
- `references/firewall-schema.md` is the V2 schema reference.
- `references/policy-templates.yaml` is a small library of common-scenario payloads you read directly.
- `references/dpi-categories.md` maps app names to DPI category groups.

---

## Required MCP Server

This skill requires the `unifi-network` MCP server. Verify with `unifi_tool_index`. If it's unavailable, direct the user to `/setup`.

---

## 1. Setup check

Before doing anything else:

- Confirm `UNIFI_NETWORK_HOST` (or `UNIFI_HOST`) is set. If not: *"UNIFI_NETWORK_HOST is not configured. Please run `/setup` before using this skill."*
- Verify the server responds by calling `unifi_tool_index`.

---

## 2. Snapshot before every mutation

You **always** snapshot the current firewall state before any create / update / delete. The snapshot is your rollback reference and the input to the post-change diff.

Gather state via three parallel tool calls:

- `unifi_list_firewall_policies`
- `unifi_list_firewall_zones`
- `unifi_list_firewall_groups`

Combine the results into one JSON document and write it to disk:

```bash
STATE_DIR="${UNIFI_SKILLS_STATE_DIR:-$HOME/.claude/unifi-skills}/firewall-snapshots"
mkdir -p "$STATE_DIR"
SNAPSHOT="$STATE_DIR/firewall_$(date -u +%Y%m%dT%H%M%SZ).json"
# Write the combined JSON ($SNAPSHOT_JSON below is what you composed from the three tool results):
printf '%s\n' "$SNAPSHOT_JSON" > "$SNAPSHOT"
echo "Snapshot saved to $SNAPSHOT"
```

Tell the user the snapshot path. They may want it for manual restore if something goes wrong.

---

## 3. Use templates when one fits

Read `references/policy-templates.yaml` directly — do not invent new templates. The file lists every template's `params`, `tool`, `payload`, and `notes`. Walk the user's request against the template list:

| Template | Use when |
|----------|----------|
| `iot-isolation` | "block IoT from reaching the LAN" / "isolate smart devices" |
| `guest-lockdown` | "lock down guest WiFi to internet only" |
| `kids-content-filter` | "block apps after bedtime" / time-based filtering |
| `block-bittorrent` | "block torrents / P2P" |
| `work-vpn-split-tunnel` | "VPN but keep printer access" |
| `camera-isolation` | "lock cameras to NVR only" |

To apply a template:

1. Read `policy-templates.yaml` and locate the matching entry.
2. Resolve every `params` value:
   - Zone IDs come from `unifi_list_firewall_zones`.
   - Network IDs come from `unifi_list_networks`.
   - Confirm any free-form parameter (times, days, network names) with the user.
3. Substitute the params into the template's `payload` block. Substitution is literal: `"{iot_zone_id}"` → `"<actual ID>"`.
4. Call the template's `tool` with the resolved payload — first **without** `confirm=true` to get the preview.
5. Show the preview to the user, get explicit confirmation, then call again with `confirm=true`.

Do not skip the preview step even when the template is well-known. Templates are starting points, not blanket approval.

---

## 4. Custom rules (when no template fits)

Consult `references/firewall-schema.md` before constructing any V2 payload. It is the authoritative reference for:

- Zones, actions (`ALLOW` / `BLOCK` / `REJECT`)
- `matching_target` / `matching_target_type` combinations
- Port matching, protocols, connection states
- Schedule format

For app-aware rules (TikTok, YouTube, Steam, BitTorrent, etc.), consult `references/dpi-categories.md` to identify the category group, then call `unifi_get_dpi_stats` to confirm the exact category ID **on this controller** before building the rule.

**Tool selection:**

- `unifi_create_firewall_policy` — V2 zone-based create. Wraps the payload in `policy_data`. Pre-resolve zone IDs (`unifi_list_firewall_zones`) and network IDs (`unifi_list_networks`) before constructing it.
- `unifi_update_firewall_policy` — partial update via fetch-merge-put. Pass only the fields you want to change in `update_data` (e.g., `{"enabled": true}`). This is the canonical way to enable/disable a policy because it preserves all other fields.
- `unifi_toggle_firewall_policy` — convenience wrapper for flipping `enabled`. Prefer `unifi_update_firewall_policy` with `update_data={"enabled": …}` — it's the canonical fetch-merge-put path and produces the same result with no special casing.

---

## 5. Verify after every mutation

Take a fresh snapshot using the same procedure as Step 2, then compare to the pre-change snapshot:

```bash
diff -u "$BEFORE" "$AFTER" | head -200
```

For a structural (key-aware) diff that ignores ordering, fall back to:

```bash
python3 - "$BEFORE" "$AFTER" <<'PY'
import json, sys
a, b = (json.load(open(p)) for p in sys.argv[1:])
def keyed(items):
    # list output uses 'id', detail output uses '_id' — accept either
    out = {}
    for i, x in enumerate(items):
        k = x.get('id') or x.get('_id') or f'__idx_{i}'
        out[k] = x
    return out
ap, bp = keyed(a.get('policies', [])), keyed(b.get('policies', []))
added   = [bp[k] for k in bp.keys() - ap.keys()]
removed = [ap[k] for k in ap.keys() - bp.keys()]
changed = [(ap[k], bp[k]) for k in ap.keys() & bp.keys() if ap[k] != bp[k]]
print(json.dumps({'added': added, 'removed': removed, 'changed': changed}, indent=2))
PY
```

Read the diff. If it does not match the change you intended (e.g., extra unintended modifications, wrong field touched), **stop and report to the user**. Do not proceed with further mutations until the unexpected change is understood.

---

## 6. Safety rules

1. **Always preview first.** Every mutating tool returns a preview when called without `confirm=true`. Show the preview verbatim before executing.
2. **Never auto-confirm.** Wait for explicit user approval before calling with `confirm=true`. "Sounds good, do it" counts. Silence does not.
3. **Snapshot before, diff after.** No exceptions. The snapshot path is the rollback reference.
4. **Check policy gates on permission errors.** If a mutation fails with a permission error, surface the relevant env var:
   - Create: `UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_CREATE=true`
   - Update: `UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_UPDATE=true`
   - Delete: `UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_DELETE=true` (off by default)
5. **Understand impact before acting.** Call `unifi_list_firewall_policies` before creating new rules to detect conflicts and redundancy.
6. **One change at a time.** When the user asks for several changes, do them sequentially with snapshot/preview/confirm/diff per change. Batching mutations makes rollback impossible.

---

## 7. Common scenarios

### "Block [app/service] on [network/VLAN]"

1. Snapshot (Step 2).
2. Identify the DPI category from `references/dpi-categories.md`, then confirm the ID with `unifi_get_dpi_stats`.
3. If a template matches (e.g., `block-bittorrent`), use it (Step 3).
4. Otherwise: gather zone + network IDs, build a V2 payload with `action="REJECT"` per `references/firewall-schema.md`.
5. Preview → confirm → execute.
6. Diff (Step 5).

### "Block [app] after [time] on [days]"

1. Snapshot.
2. If `kids-content-filter` applies, use it with `block_days`, `block_start`, `block_end`.
3. Otherwise: consult the schedule format in `references/firewall-schema.md` and build the rule.
4. Preview → confirm → diff.

### "Show me all rules affecting [network/VLAN]"

1. `unifi_list_firewall_policies`.
2. Filter to policies whose `source` or `destination` references the target network or its zone.
3. Present as a table: name, action, source → destination, enabled, ruleset.

No mutation, no snapshot needed.

### "Are there any conflicting or redundant rules?"

1. `unifi_list_firewall_policies`.
2. For deeper analysis, also fetch per-policy details via `unifi_get_firewall_policy_details`.
3. Look for: same source/destination but different actions (conflict), strict subsets with the same action (redundant), disabled rules duplicating enabled ones (clutter), broad ALLOW rules indexed before specific REJECT rules (shadowing).
4. Report findings with prioritised recommendations. Hand off to the **firewall-auditor** skill for a scored audit.

### "Set up IoT isolation / guest lockdown / camera isolation"

1. Snapshot.
2. Locate the matching template in `policy-templates.yaml`.
3. Resolve params (zone IDs from `unifi_list_firewall_zones`, network IDs from `unifi_list_networks`).
4. Apply (Step 3).
5. Diff.

### "Clean up / optimize firewall rules"

1. `unifi_list_firewall_policies`.
2. Snapshot.
3. Identify quick wins: disabled duplicates → delete (if delete policy gate is on), shadowed rules → re-order, stale references → remove.
4. Propose changes one at a time with previews.
5. Diff after each change.

For a comprehensive scored audit, use the **firewall-auditor** skill instead.

---

## 8. Manual fallback

When you cannot reach the MCP server (network issue, server crash), there is no fallback that mutates the controller — there's nothing to mutate against. Tell the user the server is unreachable and direct them to `/setup` for diagnosis.

The "manual procedure" sections of older versions of this skill assumed a separate HTTP transport that no longer exists. Removed for simplicity.

---

## 9. Tips

- `unifi_create_firewall_policy` is the canonical create tool. Pre-resolve zone IDs and network IDs before constructing the V2 payload.
- Users say "block" loosely — clarify whether they want `REJECT` (sends RST/ICMP unreachable, faster client failure) or `BLOCK` (silent discard, less informative to the client). `REJECT` is usually right for internal traffic, `BLOCK` for external-facing rules. The action comparison table is in `references/firewall-schema.md`.
- DPI rules are bypassable by VPNs. When blocking social media or gaming, also consider blocking the VPN/Proxy DPI category. See `references/dpi-categories.md`.
- Rule order matters for `camera-isolation` and other multi-rule templates. Confirm ordering with `unifi_list_firewall_policies` after creation.
- A snapshot is just a JSON file. If a change goes wrong, the user can reconstruct the prior state by hand from the snapshot — share the path.
