# Event Fields and Types

Use actual returned records to classify activity. Controller versions and API
families differ; these examples are not an exhaustive type catalog. Unknown
fields and codes stay unknown. Source events are observations; detections and
credential account names are not proof of a person's physical identity.

## Protect

Use `protect_list_smart_detections` and `protect_list_events` for historical reads.
Both return canonical event rows with `id`, `type`, `start`, `end`, `score`,
`smart_detect_types`, `camera`, and `thumbnail` when present. `score` uses 0–100,
not 0–1. Smart detections have `type="smartDetectZone"`; classify the subtype
from `smart_detect_types` (for example person, vehicle, animal, package, face,
licensePlate), rather than assuming `type="person"`. Missing confidence is unknown.
A high model score is a model classification, not independent confirmation.

The `camera_id` query parameter selects a camera; canonical rows use `camera`.
Likewise, canonical thumbnail references use `thumbnail`; compact queries omit
thumbnail fields. Camera names are optional enrichments: resolve missing names
with `protect_list_cameras` if needed. Never fabricate mappings from similar names.

Supported `protect_list_events` filter examples include motion, smartDetectZone,
ring, sensorMotion, sensorContact and sensorDoorbell. Only pass codes accepted by
the discovered schema; a ring plus a person detection suggests activity, not a
confirmed visitor identity. Use `protect_get_event_thumbnail(event_id="...")`
for a retrieved event when visual review is requested.

## Access

Use `access_list_events` with explicit ISO `start` and `end` bounds. Select
`topic="unlocks"` for door grants/open/close and `topic="access_denial"` for
refused attempts. The default admin topic is not a badge-event inventory.
Other supported topics include ring, updates, critical, admin and admin_activity.
Record topic and caps separately. `access_get_activity_summary(days=1)` is a
relative aggregate; it does not substitute for the requested historical interval.
`access_recent_events` is a bounded websocket buffer, not historical coverage.

Retain source IDs/timestamps and the fields actually returned. Event names and
nested payloads vary; do not assume all records contain door/user names or a
specific uppercase code. A grant records credential/account activity, not who
physically entered; a denied grant does not establish intent. No retrieved grant
is only an absence in the checked records, especially with partial coverage.

## Network

Use `unifi_get_event_types` to discover exact recently observed event keys before
filtering `unifi_list_events`. Legacy EVT codes and newer system-log keys differ.
`within_hours` is a relative lookback, `start` an integer pagination offset, and
`limit` a result cap. Filter returned timestamps to the requested interval; disclose
when that interval cannot be fully covered. Read actual record fields rather than
assuming legacy MAC/name fields exist in every API family.

`unifi_list_alarms` reads alarm state, not the full historical event stream.
An alarm, a client connection and a camera detection near the same time are
separate observations. They do not establish an attacker, device owner or cause.

## Counts and Correlations

Report per-query retrieved counts, bounds, filters, pagination and cap status.
Unavailable, partial and capped sources cannot establish negative evidence or an
all-clear. Apply the conceptual rules in correlation-rules.md only with verified
mappings, adequate coverage and known time alignment; otherwise mark unevaluated.
