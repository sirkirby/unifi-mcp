---
name: unifi-protect
description: How to manage UniFi Protect cameras and NVR — view cameras, smart detections, Find Anything detection search, recordings, snapshots, lights, sensors, Known Faces, license plates, and the Alarm Manager. Use this skill when the user mentions UniFi cameras, security cameras, NVR, recordings, motion detection, person detection, vehicle search, face recognition, Known Faces, license plates, snapshots, RTSP streams, floodlights, sensors, chimes, arming/disarming the alarm, or any UniFi Protect task.
---

# UniFi Protect MCP Server

You have access to a UniFi Protect MCP server that lets you query and manage a UniFi Protect NVR. It provides 58 tools covering cameras, smart detections, Find Anything detection search, recordings, snapshots, lights, sensors, chimes, Known Faces, license plates, and the Alarm Manager (arm/disarm).

## Tool Discovery

The server uses **lazy loading** by default — only meta-tools are registered initially:

| Meta-Tool | Purpose |
|-----------|---------|
| `protect_tool_index` | Discover tools by name/description; use `category`, `search`, or `include_schemas` to filter |
| `protect_execute` | Call any tool by name (essential in lazy mode) |
| `protect_batch` | Run multiple tools in parallel |
| `protect_batch_status` | Check async batch job status |

**Workflow:** Call `protect_tool_index` to find the right tool, then `protect_execute` to call it. Use `protect_batch` for multiple independent queries.

## Safety Model

**All mutations are disabled by default** because Protect controls physical security hardware.

**Read operations** — always available. Listing cameras, events, snapshots, sensor readings — all work without permissions.

**Mutations** require explicit opt-in via env vars:
- `UNIFI_POLICY_PROTECT_CAMERAS_UPDATE=true` — camera settings, recording toggle, PTZ, reboot
- `UNIFI_POLICY_PROTECT_LIGHTS_UPDATE=true` — light brightness, PIR sensitivity
- `UNIFI_POLICY_PROTECT_CHIMES_UPDATE=true` — chime volume, trigger
- `UNIFI_POLICY_PROTECT_ALARM_UPDATE=true` — arm/disarm the Alarm Manager (Protect 6.1+)
- `UNIFI_POLICY_PROTECT_RECOGNITION_UPDATE=true` — Known Face rename/merge
- `UNIFI_POLICY_PROTECT_RECOGNITION_DELETE=true` — Known Face deletion

**Confirmation flow** — every mutation uses preview-then-confirm:
1. Default call → returns preview of what would change
2. Call with `confirm=true` → executes the mutation

Always preview first and show the user before confirming.

## Response Format

All tools return: `{"success": true, "data": ...}`, `{"success": false, "error": "..."}`, or `{"success": true, "requires_confirmation": true, "preview": ...}`. Always check `success` first.

## Key Capabilities

- **Snapshots:** `protect_get_snapshot` with `include_image=true` returns base64 JPEG inline
- **RTSP streams:** `protect_get_camera_streams` gives stream URLs for video player integration
- **Smart detections:** `protect_list_smart_detections` filters by type (person, vehicle, animal, package, face, licensePlate). These are the highest-signal events — prioritize over raw motion.
- **Find Anything search:** use `protect_detection_search_labels` to discover controller-supported label values, then pass those values to `protect_search_detections` for richer searches by vehicle type, color, device, or other Protect labels.
- **Event camera names:** All event responses include `camera_name` alongside `camera_id` — no need to call `protect_list_cameras` separately to resolve names.
- **Real-time events:** `protect_recent_events` reads from websocket buffer instantly (no API call). Buffer holds ~100 events with 5-minute TTL. Use `protect_list_events` for historical queries.
- **Video export:** `protect_export_clip` returns metadata (not video data — too large for MCP). Max 2 hours, supports timelapse (fps: 4=60x, 8=120x, 20=300x)
- **PTZ:** Only zoom works via API. For pan/tilt, use `protect_ptz_preset` with saved positions
- **Known Faces:** Use `protect_list_known_faces` to inspect face groups before rename, merge, or delete mutations

## Efficiency Tips

- **Use `protect_batch` for parallel queries** — biggest performance win. Batch smart detections + events in one call.
- **Prefer `protect_list_smart_detections` over `protect_list_events`** for security analysis — smart detections are pre-classified (person, vehicle, etc.) and higher signal than raw motion.
- **Use `protect_search_detections` for Find Anything questions** — if the user asks for "white vans", "animals in the driveway", or other attribute searches, discover labels first and reuse the returned `value` strings.
- **`protect_recent_events` is fast but small** — only a few minutes of buffered data. For anything beyond real-time monitoring, use `protect_list_events` with time range filters.
- **Limit results** — event queries default to 30 but can return large payloads. Use `limit` parameter to keep responses focused.
- **Security digest** — for comprehensive event summaries, use the `security-digest` skill which handles batch calls, severity classification, and cross-product correlation.

## Authentication

Username and password are **required** (local admin credentials, not Ubiquiti SSO). API key support exists but is **experimental** — limited to read-only operations and a subset of tools.

To configure, run `/unifi-protect:unifi-protect-setup` or set env vars manually:
```
UNIFI_PROTECT_HOST=192.168.1.1
UNIFI_PROTECT_USERNAME=admin
UNIFI_PROTECT_PASSWORD=your-password
```

## Other UniFi Servers

If the user also has networking or door access control, other UniFi MCP plugins are available:
- `unifi-network` — network devices, clients, firewall, VPN, routing
- `unifi-access` — door locks, credentials, visitors, access policies

Cameras are network clients — if a camera appears offline, the Network server can help check connectivity via `unifi_lookup_by_ip`.

## Tool Reference

For the complete list of all 58 tools organized by category with descriptions, tips, and common scenarios, read `references/protect-tools.md`.
