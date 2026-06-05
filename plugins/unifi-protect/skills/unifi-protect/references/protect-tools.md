# Protect Server Tool Reference (58 tools)

Complete reference for `protect_*` tools. All read tools are always available. All mutations are **disabled by default** — the user must explicitly enable them because Protect controls physical security hardware.

## Table of Contents
- [Meta-Tools](#meta-tools)
- [Cameras](#cameras)
- [Events](#events)
- [Recordings](#recordings)
- [Devices: Lights, Sensors, Chimes](#devices-lights-sensors-chimes)
- [Liveviews](#liveviews)
- [System](#system)
- [Alarm Manager](#alarm-manager)
- [Known Faces](#known-faces)
- [Common Scenarios](#common-scenarios)
- [Important Limitations](#important-limitations)

---

## Meta-Tools

Always available, regardless of registration mode.

| Tool | Purpose |
|------|---------|
| `protect_tool_index` | Discover tools (names+descriptions by default; pass `include_schemas` for full schemas) |
| `protect_execute` | Execute any tool by name (essential in lazy mode) |
| `protect_batch` | Run multiple tools in parallel |
| `protect_batch_status` | Check status of an async batch job |

---

## Cameras

<!-- AUTO:tools:cameras -->
11 tools.

| Tool | Type | Description |
|------|------|-------------|
| `protect_get_camera` | Read | Returns detailed information for a single camera including firmware, IP address, MAC, mic/speaker settings, IR/HDR mode, stream channels,... |
| `protect_get_camera_analytics` | Read | Returns motion and smart detection analytics for a camera including current detection state, last-detected timestamps for each type (pers... |
| `protect_get_camera_streams` | Read | Returns RTSP/RTSPS stream URLs for a camera organized by channel (High, Medium, Low). |
| `protect_get_snapshot` | Read | Fetches a JPEG snapshot from a camera. |
| `protect_list_cameras` | Read | Lists all cameras adopted by the Protect NVR with their name, model, connection state, recording mode, and whether they are currently rec... |
| `protect_ptz_move` | Mutate | Moves a PTZ camera using normalized pan/tilt speeds. |
| `protect_ptz_preset` | Mutate | Moves a PTZ camera to a saved preset position by slot number. |
| `protect_ptz_zoom` | Mutate | Zooms a PTZ camera using normalized zoom speed. |
| `protect_reboot_camera` | Mutate | Reboots a camera. |
| `protect_toggle_recording` | Mutate | Enables or disables recording on a camera. |
| `protect_update_camera_settings` | Mutate | Updates camera settings such as IR LED mode, HDR mode, mic/speaker volume, status light, and motion detection. |
<!-- /AUTO:tools:cameras -->

**Tips:**
- `protect_get_snapshot` with `include_image=true` returns base64 JPEG inline — useful for quick visual checks
- `protect_get_camera_streams` gives RTSP URLs for video player integration — these can be shared with the user
- Camera settings use a dict: `settings={"ir_led_mode": "auto", "hdr_mode": true, "mic_enabled": true}`
- PTZ pan/tilt uses `protect_ptz_move`; PTZ zoom uses `protect_ptz_zoom`; saved positions use `protect_ptz_preset`

**Permission env vars:**
- `UNIFI_POLICY_PROTECT_CAMERAS_UPDATE=true` — enables settings, recording toggle, PTZ, reboot

---

## Events

<!-- AUTO:tools:events -->
9 tools.

| Tool | Type | Description |
|------|------|-------------|
| `protect_detection_search_labels` | Read | List the detection-search filter vocabulary supported by this controller. |
| `protect_get_event` | Read | Get detailed information for a single event by ID. |
| `protect_get_event_thumbnail` | Read | Get the thumbnail image for an event. |
| `protect_list_events` | Read | Query events from the NVR with optional filters. |
| `protect_list_smart_detections` | Read | List smart detection events (person, vehicle, animal, package, etc.) with optional filters. |
| `protect_recent_events` | Read | Get recent events from the in-memory websocket buffer. |
| `protect_search_detections` | Read | Search detections across all cameras using Protect's 'Find Anything' filter vocabulary. |
| `protect_subscribe_events` | Read | Returns instructions for subscribing to real-time Protect events. |
| `protect_acknowledge_event` | Mutate | Acknowledge an event by marking it as a favorite on the NVR. |
<!-- /AUTO:tools:events -->

**Tips:**
- **Real-time vs historical**: Use `protect_recent_events` for "what just happened?" (instant, from websocket buffer). Use `protect_list_events` for "what happened last Tuesday?" (API query, slower)
- **Find Anything searches**: Call `protect_detection_search_labels` first, then pass the returned `value` strings to `protect_search_detections` for attribute searches such as vehicle type, color, device, or smart-detection type.
- Smart detection types: `person`, `vehicle`, `animal`, `package`, `face`, `licensePlate`
- `min_confidence` parameter filters out low-confidence detections (default threshold: 50)
- Event types for filtering: `motion`, `smartDetectZone`, `ring`, `sensorMotion`, `sensorContact`, `sensorDoorbell`
- Time parameters use ISO 8601 format: `2026-03-17T00:00:00Z`

---

## Recordings

<!-- AUTO:tools:recordings -->
4 tools.

| Tool | Type | Description |
|------|------|-------------|
| `protect_export_clip` | Read | Exports a video clip from a camera for a specified time range. |
| `protect_get_recording_status` | Read | Returns the current recording state for one or all cameras. |
| `protect_list_recordings` | Read | Returns recording availability information for a camera within a time range. |
| `protect_delete_recording` | Mutate | Attempts to delete recordings for a camera in a time range. |
<!-- /AUTO:tools:recordings -->

**Tips:**
- `protect_export_clip` produces the video on the NVR. The tool returns metadata (size, duration) — the actual video is too large for MCP
- Timelapse fps values: 4 (60x speed), 8 (120x), 20 (300x), 40 (600x)
- Channel index: 0 = high quality, 1 = medium, 2 = low
- Recording deletion is managed by the NVR's retention policy, not per-request — the delete tool returns info about this limitation

---

## Devices: Lights, Sensors, Chimes

<!-- AUTO:tools:devices -->
6 tools.

| Tool | Type | Description |
|------|------|-------------|
| `protect_list_chimes` | Read | Lists all UniFi Protect chime devices with their name, connection state, volume, ring settings per camera, and available ringtones/tracks. |
| `protect_list_lights` | Read | Lists all UniFi Protect floodlight devices with their name, connection state, brightness level, PIR motion sensitivity, and paired camera. |
| `protect_list_sensors` | Read | Lists all UniFi Protect sensor devices (motion, door/window, temperature, humidity, light level, leak detection). |
| `protect_trigger_chime` | Read | Plays the chime tone on a specific chime device. |
| `protect_update_chime` | Mutate | Updates chime settings such as speaker volume (0-100), repeat times (1-6), and device name. |
| `protect_update_light` | Mutate | Updates light settings such as on/off state, LED brightness level (1-6), PIR motion sensitivity (0-100), motion-triggered duration (15-90... |
<!-- /AUTO:tools:devices -->

**Permission env vars:**
- `UNIFI_POLICY_PROTECT_LIGHTS_UPDATE=true`
- `UNIFI_POLICY_PROTECT_CHIMES_UPDATE=true`

---

## Liveviews

<!-- AUTO:tools:liveviews -->
3 tools.

| Tool | Type | Description |
|------|------|-------------|
| `protect_list_liveviews` | Read | Lists all liveview configurations from the Protect NVR. |
| `protect_create_liveview` | Mutate | Validates input for creating a new liveview with the given name and camera IDs. |
| `protect_delete_liveview` | Mutate | Validates a liveview for deletion by ID. |
<!-- /AUTO:tools:liveviews -->

**Note:** Liveview creation and deletion must be done via the Protect web UI. These tools validate inputs but cannot perform the actual operations.

---

## System

<!-- AUTO:tools:system -->
4 tools.

| Tool | Type | Description |
|------|------|-------------|
| `protect_get_firmware_status` | Read | Returns firmware update availability for the NVR and all adopted devices (cameras, lights, sensors, viewers, chimes, bridges, doorlocks). |
| `protect_get_health` | Read | Returns NVR health summary including CPU load and temperature, memory usage, and storage utilization. |
| `protect_get_system_info` | Read | Returns NVR model, firmware version, uptime, storage usage, and connected device counts. |
| `protect_list_viewers` | Read | Lists all connected Protect viewers (e.g., UP-Viewer, Viewport) with their connection state, firmware version, and assigned liveview. |
<!-- /AUTO:tools:system -->

**Tips:**
- `protect_get_health` is the best "is the NVR healthy?" check — covers CPU, RAM, storage
- `protect_get_firmware_status` shows which devices have updates available

---

## Alarm Manager

Controls the UniFi Protect Alarm Manager (Protect 6.1+). Requires arm profiles configured in the Protect web UI. Mutations gated by `UNIFI_POLICY_PROTECT_ALARM_UPDATE=true`.

<!-- AUTO:tools:alarm -->
9 tools.

| Tool | Type | Description |
|------|------|-------------|
| `protect_alarm_get_rule` | Read | Fetches a single UniFi Protect alarm rule by id (normalized: id, title, enabled, triggers, actions, scope, stats), including AI-powered a... |
| `protect_alarm_get_status` | Read | Returns the current armed/disarmed state of the UniFi Protect Alarm Manager, including the active profile, raw status string, armed-at ti... |
| `protect_alarm_list_profiles` | Read | Lists all configured UniFi Protect Alarm Manager profiles with their id, name, activation delay, schedule count, and automation count. |
| `protect_alarm_list_rules` | Read | Lists every UniFi Protect alarm rule, including AI-powered alarms (e.g. |
| `protect_alarm_arm` | Mutate | Arms the UniFi Protect Alarm Manager. |
| `protect_alarm_create_rule` | Mutate | Creates a new alarm rule via POST. |
| `protect_alarm_delete_rule` | Mutate | Deletes an alarm rule (automation) by id. |
| `protect_alarm_disarm` | Mutate | Disarms the UniFi Protect Alarm Manager system-wide via POST arm/disable. |
| `protect_alarm_update_rule` | Mutate | Updates an alarm rule. |
<!-- /AUTO:tools:alarm -->

**Tips:**
- Call `protect_alarm_get_status` first to see what's currently active before arming/disarming
- Both `protect_alarm_arm` and `protect_alarm_disarm` are idempotent — calling them when the system is already in the target state is a no-op (returns `already_armed` / `already_disarmed`)
- To switch arm profiles while the system is armed, you must **disarm first** — the API does not allow switching profiles mid-arm
- There's typically an activation delay (e.g. 60 seconds) configured per profile — the system enters a pending state (`willBeArmedAt`) before fully arming

---

## Known Faces

Lists and manages UniFi Protect Known Faces / named face recognition groups. Read tools return metadata and controller image references only; mutations use preview-then-confirm.

<!-- AUTO:tools:recognition -->
7 tools.

| Tool | Type | Description |
|------|------|-------------|
| `protect_list_known_faces` | Read | List UniFi Protect face recognition groups, including assigned Known Faces by default and unlabeled groups when group_types includes unkn... |
| `protect_list_known_license_plates` | Read | List UniFi Protect license-plate identities (vehicle recognition groups), including named/known license plates by default and unlabeled p... |
| `protect_delete_known_face` | Mutate | Delete or remove a UniFi Protect face recognition group. |
| `protect_delete_known_license_plate` | Mutate | Delete or remove a UniFi Protect license-plate recognition group. |
| `protect_merge_known_faces` | Mutate | Merge one UniFi Protect face group into another. |
| `protect_update_known_face` | Mutate | Update UniFi Protect Known Face metadata. |
| `protect_update_known_license_plate` | Mutate | Update UniFi Protect Known License Plate (license-plate identity) metadata. |
<!-- /AUTO:tools:recognition -->

**Tips:**
- Use `protect_list_known_faces` to discover configured face labels and last-seen timestamps.
- Use `protect_update_known_face` for metadata changes, `protect_merge_known_faces` to consolidate duplicate groups, and `protect_delete_known_face` only after previewing the exact group.
- Image fields are controller references only; the tool does not fetch or return image bytes.

---

## Common Scenarios

### "What's happening on the cameras right now?"
1. `protect_list_cameras` → see all cameras and their status
2. `protect_recent_events` → what was just detected (instant, from buffer)
3. `protect_get_snapshot(camera_id="...", include_image=true)` → visual check

### "Was anyone detected last night?"
1. `protect_list_smart_detections(detection_type="person", start="<last night>", end="<this morning>")` → person detections
2. `protect_get_event_thumbnail(event_id="...")` → see what was detected
3. `protect_get_event(event_id="...")` → full details including confidence score

### "Export footage from the front door camera"
1. `protect_list_cameras` → find the front door camera ID
2. `protect_list_recordings(camera_id="...", start="...", end="...")` → verify footage exists
3. `protect_export_clip(camera_id="...", start="...", end="...")` → export the clip

### "Check NVR health"
```
protect_batch(tools=[
    {"tool": "protect_get_system_info"},
    {"tool": "protect_get_health"},
    {"tool": "protect_get_firmware_status"},
    {"tool": "protect_get_recording_status"}
])
```

### "A camera seems offline"
1. `protect_list_cameras` → check connection state
2. `protect_get_camera(camera_id="...")` → detailed status including IP and MAC
3. Cross-reference with Network: `unifi_lookup_by_ip(ip="<camera IP>")` → network-level status
4. If needed: `protect_reboot_camera(camera_id="...", confirm=true)` → reboot (requires permission)

---

## Important Limitations

1. **Liveview create/delete** — Not supported by the uiprotect API. Tools validate inputs but the actual operations must be done in the Protect web UI.
2. **Recording deletion** — Managed by NVR retention policy, not per-request.
3. **PTZ pan/tilt** — Only zoom is supported via the API. For pan/tilt control, use saved preset positions via `protect_ptz_preset`.
4. **Video data** — `protect_export_clip` returns metadata about the exported clip, not the video bytes (too large for MCP responses).
5. **Snapshot size** — Base64 snapshots can be large. Use width/height params to resize, or use `include_image=false` for just the reference URI.
