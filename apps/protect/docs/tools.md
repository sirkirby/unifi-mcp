# Tool Catalog

The UniFi Protect MCP server exposes 58 tools (including 5 meta-tools), all prefixed with `protect_`. Read-only tools are always available. Mutating tools are controlled by the [permission system](permissions.md).

Standard MCP clients should use `tools/list` for currently registered tools. For compact manifest-backed metadata in lazy/meta-only workflows, call the `protect_tool_index` compatibility meta-tool at runtime, or inspect `src/unifi_protect_mcp/tools_manifest.json`.

## Meta-Tools

These are always registered regardless of mode:

- `protect_tool_index` -- Discover tools (names+descriptions by default; use `category`/`search`/`include_schemas` to filter)
- `protect_execute` -- Execute a tool by name (for lazy/meta_only modes)
- `protect_batch` -- Execute multiple tools in parallel
- `protect_batch_status` -- Check batch job status

In lazy mode, an additional meta-tool is available:

- `protect_load_tools` -- Load a set of tools by category or name for direct calling

## Cameras (11 tools)

- `protect_list_cameras` -- List all cameras with name, model, state, recording mode
- `protect_get_camera` -- Detailed camera info: firmware, IP, MAC, IR/HDR, smart detection, PTZ
- `protect_get_snapshot` -- Fetch JPEG snapshot (base64 or resource reference)
- `protect_get_camera_streams` -- RTSP/RTSPS stream URLs by channel (High/Medium/Low)
- `protect_get_camera_analytics` -- Motion and smart detection analytics with timestamps
- `protect_update_camera_settings` -- Update IR, HDR, mic, speaker, status light, motion detection (confirm required)
- `protect_toggle_recording` -- Enable/disable recording on a camera (confirm required)
- `protect_ptz_move` -- Move PTZ camera pan/tilt with normalized speeds (confirm required)
- `protect_ptz_zoom` -- Zoom PTZ camera with normalized speed (confirm required)
- `protect_ptz_preset` -- Move PTZ camera to a saved preset position (confirm required)
- `protect_reboot_camera` -- Reboot a camera; interrupts active recordings (confirm required)

## Events (9 tools)

- `protect_list_events` -- Query events from NVR with filters (time range, type, camera, limit)
- `protect_get_event` -- Get single event details by ID
- `protect_get_event_thumbnail` -- Get event thumbnail as base64 JPEG
- `protect_list_smart_detections` -- List smart detections (person, vehicle, animal, package) with confidence filter
- `protect_detection_search_labels` -- List Find Anything filter labels accepted by this controller
- `protect_search_detections` -- Search detections across cameras with Find Anything labels such as `vehicleType:truck` or `color:white`
- `protect_recent_events` -- Get events from the in-memory websocket buffer (fast, no API call)
- `protect_subscribe_events` -- Get instructions for real-time event subscription via MCP resources
- `protect_acknowledge_event` -- Mark event as favorite/acknowledged (confirm required)

## Recordings (4 tools)

- `protect_get_recording_status` -- Recording state for one or all cameras (mode, active, time range)
- `protect_list_recordings` -- Recording availability for a camera within a time range
- `protect_export_clip` -- Export video clip with metadata (max 2 hours, timelapse support)
- `protect_delete_recording` -- Recording deletion info (not supported by uiprotect API)

## Devices (6 tools)

### Lights

- `protect_list_lights` -- List floodlights with brightness, PIR sensitivity, paired camera
- `protect_update_light` -- Update on/off, brightness (1-6), sensitivity (0-100), duration (confirm required)

### Sensors

- `protect_list_sensors` -- List sensors with battery status, readings (temp, humidity, motion, leak)

### Chimes

- `protect_list_chimes` -- List chimes with volume, ring settings, available ringtones
- `protect_update_chime` -- Update volume (0-100), repeat times (1-6), name (confirm required)
- `protect_trigger_chime` -- Play chime tone with optional volume/repeat override

## Liveviews (3 tools)

- `protect_list_liveviews` -- List multi-camera layouts with slots, cameras, cycle settings
- `protect_create_liveview` -- Validate liveview creation (not supported by uiprotect API)
- `protect_delete_liveview` -- Validate liveview deletion (not supported by uiprotect API)

## Alarm Manager (9 tools)

Controls the UniFi Protect Alarm Manager (Protect 6.1+). Requires arm profiles to be configured in the Protect web UI first.

`protect_alarm_list_rules` / `protect_alarm_get_rule` are version-agnostic: they surface **AI-powered alarms** (e.g. AI Natural Language) from the modern Alarm Manager when the account is **SuperAdmin**, and fall back to the legacy automations view otherwise. When the limited view is served, the response carries a standard MCP `_meta` notice that AI alarms require SuperAdmin. See the SuperAdmin note in the README.

- `protect_alarm_list_profiles` -- List all configured arm profiles with id, name, armed state, default flag
- `protect_alarm_get_status` -- Current armed/disarmed state across all profiles
- `protect_alarm_arm` -- Arm the system for a given profile (confirm required; defaults to default profile)
- `protect_alarm_disarm` -- Disarm the system for a given profile (confirm required; defaults to default profile)
- `protect_alarm_list_rules` -- List alarm rules (normalized: id, title, enabled, triggers, actions, scope, stats), including AI alarms
- `protect_alarm_get_rule` -- Fetch a single alarm rule by id (normalized)
- `protect_alarm_create_rule` -- Create an alarm rule (automation) (confirm required)
- `protect_alarm_update_rule` -- Update an alarm rule (pass only changed fields; fetch-merge-put) (confirm required)
- `protect_alarm_delete_rule` -- Delete an alarm rule by id (confirm required)

## Known Faces & License Plates (7 tools)

- `protect_list_known_faces` -- List assigned and optionally unlabeled face recognition groups
- `protect_update_known_face` -- Update Known Face metadata such as name, description, and notifications (confirm required)
- `protect_merge_known_faces` -- Merge one face group into another (confirm required)
- `protect_delete_known_face` -- Delete or remove a face recognition group (confirm required)
- `protect_list_known_license_plates` -- List license-plate recognition groups (vehicle identities)
- `protect_update_known_license_plate` -- Update Known License Plate metadata such as name, description, and notifications (confirm required)
- `protect_delete_known_license_plate` -- Delete or remove a license-plate recognition group (confirm required)

## System (4 tools)

- `protect_get_system_info` -- NVR model, firmware, uptime, storage, device counts
- `protect_get_health` -- CPU load/temp, memory usage, storage utilization
- `protect_list_viewers` -- Connected Protect viewers (Viewport) with firmware and liveview
- `protect_get_firmware_status` -- Firmware update availability for NVR and all devices

## MCP Resources

In addition to tools, the server registers MCP resources for data that benefits from polling:

| Resource URI | Type | Description |
|-------------|------|-------------|
| `protect://events/stream` | JSON | Recent events from the websocket buffer |
| `protect://events/stream/summary` | JSON | Event count summary by type and camera |
| `protect://cameras/{camera_id}/snapshot` | JPEG | Live snapshot from a camera (template) |
| `protect://cameras/snapshots` | JSON | Index of all cameras with snapshot URIs |

See [events.md](events.md) for details on the event streaming resources.
