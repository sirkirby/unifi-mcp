# Cross-Product Correlation Rules

Deterministic patterns used by the security digest skill to identify security-relevant combinations
of events across the Protect, Access, and Network MCP servers.

Each rule defines the event sources, the time window within which events must co-occur, the logic
to evaluate, the resulting severity, and the recommended response.

## Evidence Preconditions

These are review heuristics, not implemented inference or proof of wrongdoing.
Apply a rule only with verified source mappings and adequate coverage of its
entire window. Missing, partial or capped sources cannot support absence-based
rules. Otherwise report the rule unevaluated with the missing evidence. Mapping
fields in the pseudocode are conceptual inputs, not guaranteed tool fields;
request a user-verified mapping rather than inventing one from names or timing.
A 30-day “new device” claim requires that lookback; otherwise say “not previously
seen in the retrieved records.” Event codes vary: inspect actual records using
`unifi_get_event_types` for Network. Consult event-types.md for returned fields.
Keep all rule results under Hypotheses and cite the underlying Observations.
Credential/account attribution does not prove the person's physical identity,
and a nearby network connection does not establish device ownership.

---

## Rule Index

| ID | Name | Sources | Time Window | Severity |
|----|------|---------|-------------|----------|
| CORR-01 | Motion without badge-in | Protect + Access | 2 min | High |
| CORR-02 | New device + motion | Network + Protect | 5 min | Medium |
| CORR-03 | Access denied + continued motion | Access + Protect | 10 min | High |
| CORR-04 | Device offline + camera offline | Network + Protect | 5 min | High |
| CORR-05 | After-hours access + no motion before | Access + Protect | 5 min | Low |

---

## CORR-01: Motion without badge-in

**Sources:** UniFi Protect, UniFi Access
**Time window:** 2 minutes
**Severity:** High

### Logic

1. Detect a `person` or `motion` event on a camera associated with an entry point (door camera or
   zone tagged as an entrance).
2. Query Access events for any `ACCESS_GRANT` or `REMOTE_UNLOCK` on the nearest door within
   ±2 minutes of the Protect event start time.
3. If no matching Access grant is found: **fire CORR-01**.

```
IF protect.event.type IN ["person", "motion"]
   AND protect.camera.location_type == "entry_point"
   AND NOT EXISTS access.event.type IN ["ACCESS_GRANT", "REMOTE_UNLOCK", "VISITOR_GRANT"]
       WHERE ABS(access.event.timestamp - protect.event.start) <= 120s
       AND access.event.door_id == camera.associated_door_id
THEN CORR-01
```

### Meaning

A person was detected at or near a controlled entry without any corresponding access event. Possible explanations include incomplete logs, an alternate entry path, an open
door, or an access anomaly; the retrieved events do not establish which occurred.

### Response

- Pull the Protect thumbnail and clip for the event (`thumbnail_id`)
- Review the Access event log for the nearest door in the preceding 5 minutes
- Check whether the door has a `DOOR_HELD_OPEN` or `DOOR_FORCED_OPEN` event that could explain entry
- If no explanation: escalate to on-call security or site manager

### Notes

- Requires camera-to-door mapping configuration (camera `associated_door_id` metadata)
- Low-confidence person detections (`score < 70` on the 0–100 scale) should use `motion` event as fallback
- Suppress during known propped-door windows if Access is reporting `DOOR_HELD_OPEN`

---

## CORR-02: New device + motion

**Sources:** UniFi Network, UniFi Protect
**Time window:** 5 minutes
**Severity:** Medium

### Logic

1. Detect a new wireless or wired client connection event (`EVT_WU_Connected`, `EVT_WG_Connected`)
   where the client MAC is not in the known-device list (no prior connection in the last 30 days).
2. Query Protect for `motion`, `person`, or `vehicle` events on cameras near the AP that handled
   the connection within ±5 minutes.
3. If a Protect event is found within the time window: **fire CORR-02**.

```
IF network.event.key IN ["EVT_WU_Connected", "EVT_WG_Connected"]
   AND network.client.is_new == true  # no connections in last 30 days
   AND EXISTS protect.event.type IN ["motion", "person", "vehicle"]
       WHERE ABS(protect.event.start - network.event.time) <= 300s
       AND protect.camera.ap_proximity == network.event.ap
THEN CORR-02
```

### Meaning

An unknown device connected to the network near the same time and location that Protect detected
physical presence. This may indicate an unauthorized person bringing their own device onto the
premises or a visitor not registered in the system.

### Response

- Check the client hostname and manufacturer OUI against expected vendor patterns
- Cross-reference against any visitor Access grants that day
- Review Protect footage at the relevant camera(s)
- If the device cannot be identified: flag for manual review

### Notes

- AP-to-camera proximity must be pre-configured or inferred from physical layout metadata
- Guest SSID connections are lower severity (expected unknown devices); apply a separate threshold
- Repeated occurrences of the same unknown MAC across multiple days should escalate to High

---

## CORR-03: Access denied + continued motion

**Sources:** UniFi Access, UniFi Protect
**Time window:** 10 minutes
**Severity:** High

### Logic

1. Detect an `ACCESS_DENY`, `CREDENTIAL_EXPIRED`, or `SCHEDULE_DENY` event on any door.
2. Query Protect for motion or person events on the camera associated with that door within
   10 minutes after the denial timestamp.
3. If Protect events continue for more than 2 minutes after the denial: **fire CORR-03**.

```
IF access.event.type IN ["ACCESS_DENY", "CREDENTIAL_EXPIRED", "SCHEDULE_DENY"]
   AND EXISTS protect.event.type IN ["motion", "person"]
       WHERE protect.event.start > access.event.timestamp
       AND protect.event.start <= access.event.timestamp + 600s
       AND protect.camera.associated_door_id == access.event.door_id
       AND (protect.event.end - protect.event.start) > 120s  # presence > 2 min
THEN CORR-03
```

### Meaning

Access was denied at a door and the person remained in the area rather than leaving. This pattern
is consistent with someone attempting to find an alternative entry method, waiting for an authorized
user to open the door (tailgating opportunity), or casing the entry point.

### Response

- Alert on-call security immediately
- Pull Protect footage for real-time review if cameras support live view
- Dispatch personnel to the location if motion is still active
- Log the denial credential details for follow-up (was the card stolen or cloned?)

### Notes

- A single short motion burst after denial (< 2 min) is acceptable — person may be leaving
- Multiple denials on the same door within 10 minutes compound the severity (treat as Critical)
- If `DOOR_FORCED_OPEN` follows the denial sequence, escalate immediately to Critical

---

## CORR-04: Device offline + camera offline

**Sources:** UniFi Network, UniFi Protect
**Time window:** 5 minutes
**Severity:** High

### Logic

1. Detect a device offline event on the Network server (`EVT_AP_Disconnected`,
   `EVT_SW_Disconnected`) for infrastructure known to serve camera networks.
2. Query Protect for camera connection state changes (camera disconnected) within ±5 minutes of
   the Network event.
3. If one or more Protect cameras go offline in the same time window: **fire CORR-04**.

```
IF network.event.key IN ["EVT_AP_Disconnected", "EVT_SW_Disconnected"]
   AND network.device.serves_camera_vlan == true
   AND EXISTS protect.camera.state == "DISCONNECTED"
       WHERE ABS(protect.camera.state_change_time - network.event.time) <= 300s
THEN CORR-04
```

### Meaning

A network infrastructure device went offline coinciding with camera disconnections. This may
indicate a power failure affecting a specific circuit, a network fault on a PoE switch or VLAN,
or deliberate tampering with network infrastructure to blind cameras before an intrusion.

### Response

- Check the Network server for correlated power events on PoE switches
- Verify physical infrastructure at the affected location
- If cameras are in a security-critical area and tampering is suspected, escalate immediately
- Cross-reference with Access events at nearby doors during and after the outage window

### Notes

- Correlate by physical location: a switch in one building going offline while cameras in a
  different building disconnect is not necessarily CORR-04
- Power-related failures (UPS alarm, PoE budget exceeded) reduce the severity to Medium
- A gateway disconnect (`EVT_GW_Disconnected`) causing all cameras to appear offline is a
  site-wide failure, not a targeted outage — classify differently

---

## CORR-05: After-hours access + no motion before

**Sources:** UniFi Access, UniFi Protect
**Time window:** 5 minutes
**Severity:** Low

### Logic

1. Detect an `ACCESS_GRANT` on any door outside defined business hours (default: before 06:00 or
   after 22:00 local time).
2. Query Protect for motion or person events on the associated camera within the 5 minutes
   before the badge-in.
3. If no Protect motion is found in the pre-badge window: **fire CORR-05** (informational).

```
IF access.event.type == "ACCESS_GRANT"
   AND access.event.timestamp.hour NOT IN [06:00..22:00]  # outside business hours
   AND NOT EXISTS protect.event.type IN ["motion", "person"]
       WHERE protect.event.start >= (access.event.timestamp - 300s)
       AND protect.event.start < access.event.timestamp
       AND protect.camera.associated_door_id == access.event.door_id
THEN CORR-05
```

### Meaning

Someone badged in after hours but there was no motion detected at the entry camera before they
swiped. This is the expected pattern for legitimate after-hours access (the person approaches
quickly, swipes, and enters — motion may not register before the badge event). The rule exists
to create an audit trail of after-hours access events, not to flag them as suspicious.

The inverse (motion before badge, then badge-in) is the normal approach pattern and does not need
a correlation rule.

### Response

- Log in the digest as an after-hours access event with the recorded credential account and door, without asserting who used it
- No immediate action required for a single occurrence
- Review if the same credential is used more than 3 times in a single after-hours period

### Notes

- This rule is intentionally Low severity — it is an informational audit rule
- If the after-hours access is followed by a CORR-01 (no badge for a second person detected),
  escalate the CORR-01 to High
- Business hours should be configurable per site; the default (06:00–22:00) is a reasonable fallback

---

## Applying Multiple Rules

When multiple rules fire on the same set of events, use the following aggregation logic:

1. **Highest severity wins** for the final digest classification of the incident
2. **Co-firing rules compound the narrative** — list all fired rule IDs in the digest entry
3. **Temporal overlap** — if the same events satisfy two rules, create a single merged incident
   record citing both rule IDs rather than two separate incidents

Example: CORR-01 (High) and CORR-02 (Medium) firing on the same time window at the same location
produces one High-severity incident with note "CORR-01, CORR-02".

---

## Rule Maintenance

- Rules reference camera-to-door mappings and AP-to-camera proximity data that must be configured
  in the site metadata
- Business hours used in CORR-05 default to 06:00–22:00 and should be overridden per deployment
- Rules that depend on `is_new` MAC classification use a 30-day lookback window by default
