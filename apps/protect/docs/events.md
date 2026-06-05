# Event Streaming

The Protect server provides real-time event monitoring through a combination of websocket buffering, MCP resources, and query tools.

## Architecture

```
UniFi Protect NVR
    |
    v  WebSocket (uiprotect library)
    |
EventManager._on_ws_message()
    |
    v  Filters + serializes events
    |
EventBuffer (ring buffer, in-memory)
    |
    +---> MCP Resources (protect://events/stream, protect://events/stream/summary)
    +---> protect_recent_events tool (filtered buffer queries)
    +---> protect_subscribe_events tool (subscription instructions)
```

### How Events Flow

1. **WebSocket connection** -- The server connects to the Protect NVR's websocket endpoint via `uiprotect`. This streams all NVR events in real time: motion, smart detections, doorbell rings, sensor triggers, etc.

2. **Event processing** -- `EventManager._on_ws_message()` receives raw websocket messages, filters for relevant event types (`Event` model updates with `add`/`update` actions), and serializes them to plain dicts.

3. **Ring buffer** -- Processed events are stored in an `EventBuffer` (a `deque` with configurable max size and TTL). When the buffer is full, the oldest event is silently dropped.

4. **Client access** -- MCP clients read buffered events via resources or tools. No events are lost between polls as long as the buffer does not overflow.

## MCP Resources

### `protect://events/stream`

Returns the full contents of the event buffer as a JSON array (newest first). Each event includes:

- `type` -- Event type (motion, smartDetectZone, ring, sensorMotion, etc.)
- `camera_id` -- Source camera ID (if applicable)
- `start` / `end` -- Event timestamps
- `score` -- Detection confidence score (0-100)
- `smart_detect_types` -- Array of detected object types (person, vehicle, animal, package)
- `_buffered_at` -- Unix timestamp when the event entered the buffer

### `protect://events/stream/summary`

A lightweight summary of the buffer: total event count, breakdown by event type, and breakdown by camera. Useful for deciding whether to fetch the full stream.

```json
{
  "total_events": 42,
  "by_type": {"motion": 30, "smartDetectZone": 10, "ring": 2},
  "by_camera": {"camera-id-1": 25, "camera-id-2": 17},
  "buffer_size": 100
}
```

## Tools for Event Access

| Tool | Source | Best for |
|------|--------|----------|
| `protect_recent_events` | Websocket buffer | Real-time monitoring with filters |
| `protect_list_events` | NVR REST API | Historical queries with time ranges |
| `protect_list_smart_detections` | NVR REST API | Filtered smart detection history |
| `protect_detection_search_labels` | NVR REST API | Discover Find Anything labels supported by this controller |
| `protect_search_detections` | NVR REST API | Find Anything searches with labels such as color, vehicle type, detection type, or device |
| `protect_subscribe_events` | -- | Getting subscription instructions |

### protect_recent_events vs protect_list_events

- **`protect_recent_events`** reads from the in-memory buffer. It is fast (no API call) but limited to events received since the server started, up to the buffer size. Supports filtering by event_type, camera_id, and min_confidence.

- **`protect_list_events`** queries the NVR's REST API. It can access the full event history stored on disk. Supports filtering by time range, event type, camera, and result limit.

Use `protect_recent_events` for near-real-time monitoring. Use `protect_list_events` for historical analysis.

Use `protect_list_smart_detections` when a simple detection-type timeline is enough. Use `protect_detection_search_labels` followed by `protect_search_detections` when the user asks for Protect's richer Find Anything filters, such as vehicle type, color, device-specific labels, or controller-specific recognition categories. The label `value` fields returned by `protect_detection_search_labels` are safe to pass directly back in the `labels` argument.

## Recommended Client Pattern

MCP push notifications are not yet available from background websocket callbacks due to a FastMCP limitation: `ServerSession.send_resource_updated(uri)` is only accessible during an active request context. There is no public API for broadcasting notifications from a background callback.

The recommended approach is **polling**:

1. Call `protect_subscribe_events` to get resource URIs and instructions
2. Poll `protect://events/stream/summary` every 5-10 seconds to check for new events
3. When the summary shows new events, read `protect://events/stream` for full details
4. Or use `protect_recent_events` tool with filters for targeted queries

When FastMCP adds broadcast support for background notifications, the server can be updated to push `notifications/resources/updated` automatically from the websocket callback.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `PROTECT_EVENT_BUFFER_SIZE` | `100` | Maximum events in the ring buffer |
| `PROTECT_EVENT_BUFFER_TTL` | `300` | Seconds before buffered events are considered expired |
| `PROTECT_WEBSOCKET_ENABLED` | `true` | Enable/disable the websocket listener |
| `PROTECT_SMART_DETECTION_MIN_CONFIDENCE` | `50` | Default minimum confidence for smart detection queries |

### Tuning the Buffer

- **High-traffic environments** (many cameras, frequent motion): increase `PROTECT_EVENT_BUFFER_SIZE` to 500+ and decrease poll interval to 2-3 seconds
- **Low-traffic environments**: default values work well; poll every 10-30 seconds
- **Memory-constrained**: reduce `PROTECT_EVENT_BUFFER_SIZE`; each event is ~1-2 KB

### Disabling the WebSocket

Set `PROTECT_WEBSOCKET_ENABLED=false` to disable real-time streaming. REST-based tools (`protect_list_events`, `protect_list_smart_detections`) will still work. The buffer-based tools and resources will return empty results.
