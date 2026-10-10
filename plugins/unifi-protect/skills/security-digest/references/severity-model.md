# Severity Model

How the security digest skill classifies and escalates event severity based on time, location,
frequency, and cross-product correlation context.

---

## Evidence Limits

Severity is a review priority for an observed event or explicitly labelled hypothesis,
not certainty of identity, wrongdoing or cause. Use verified site timezone, business
hours and mappings; when unknown, state the assumption and withhold modifiers that
need it. Missing/capped evidence cannot lower severity to an all-clear or support
absence-based correlations. Counts and frequency thresholds apply to retrieved
records unless full interval coverage is established.

## Severity Levels

| Level | Label | Meaning | Digest Behavior |
|-------|-------|---------|-----------------|
| 5 | **Critical** | Immediate threat or service-affecting failure | Always included; digest leads with this section |
| 4 | **High** | Significant security concern requiring prompt review | Always included |
| 3 | **Medium** | Potentially concerning; warrants investigation | Included; grouped after High |
| 2 | **Low** | Informational with minor security implication | Included in summary section |
| 1 | **Informational** | Normal operation, logged for audit trail | Suppressed from narrative; available on request |

---

## Time-Based Factors

Time of day is the primary contextual modifier. All times are local site time.

### Night (22:00–06:00)

| Event Type | Base Severity | Night Modifier | Result |
|------------|--------------|----------------|--------|
| `person` detection | Low | +2 | High |
| `vehicle` detection | Informational | +2 | Medium |
| `motion` (generic) | Informational | +1 | Low |
| `ring` (doorbell) | Low | +1 | Medium |
| `ACCESS_GRANT` | Informational | +1 | Low |
| `EVT_WU_Connected` (unknown MAC) | Low | +1 | Medium |
| `EVT_AP_Disconnected` | Medium | +1 | High |

### Business Hours (08:00–17:00)

| Event Type | Base Severity | Business Hours Modifier | Result |
|------------|--------------|------------------------|--------|
| `person` detection | Low | 0 | Low |
| `vehicle` detection | Informational | 0 | Informational |
| `motion` (generic) | Informational | 0 | Informational |
| `ACCESS_GRANT` | Informational | 0 | Informational |
| `ACCESS_DENY` | Low | 0 | Low |
| `EVT_IPS_IpsAlert` | High | 0 | High |

### Transition Hours (06:00–08:00 and 17:00–22:00)

Apply half the night modifier (round down). For example, `person` detection during transition
hours: Low + 1 = Medium.

---

## Location-Based Factors

Physical location adjusts severity independent of time.

### Entry Points (Doors, Gates, Loading Docks)

Entry points are the highest-sensitivity locations. Events here carry a +1 modifier.

- Applies to cameras with `location_type == "entry_point"` or associated with an Access door
- `DOOR_FORCED_OPEN` at any entry point is always at least High, regardless of time
- `person` detection at an unmanned entry point during night hours combines time (+2) and location (+1) = Critical cap

### Perimeter (Driveway, Fence Line, Parking Lot, Exterior Walls)

Perimeter locations carry no modifier at baseline but escalate faster under frequency rules.

- `vehicle` detection on a perimeter camera is Informational during business hours, Low at night
- Repeated perimeter `person` detections (3+ in 30 min) escalate to Medium

### Interior (Office, Hallway, Server Room, Warehouse Floor)

Interior locations carry a -1 modifier during business hours (expected human traffic) and a +1
modifier during night hours (unexpected presence).

- Server room or secured interior: treat as entry point for severity purposes
- Open-plan office during business hours: `person` and `motion` are Informational

---

## Frequency-Based Factors

Event frequency within a rolling time window escalates severity by one level per threshold crossed.

### Repeated Events at the Same Location

| Condition | Escalation |
|-----------|-----------|
| 3 or more events of the same type at the same camera within 30 minutes | +1 |
| 5 or more events of the same type at the same camera within 30 minutes | +2 |
| Events continuing without interruption for more than 10 minutes | +1 |

**Continuous motion** is defined as overlapping or sequential motion events with gaps of less than
60 seconds between them. A 10-minute continuous motion sequence at an entry point during night
hours reaches: Low (base) + 2 (night) + 1 (entry point) + 1 (continuous) = Critical.

### Repeated Access Denials at the Same Door

| Condition | Escalation |
|-----------|-----------|
| 2 denials within 5 minutes at the same door | +1 |
| 3 or more denials within 10 minutes at the same door | +2 |

### Repeated Unknown Device Connections

| Condition | Escalation |
|-----------|-----------|
| Same unknown MAC seen on 3 or more separate days | +1 |
| Multiple unknown MACs on same AP within 30 minutes | +1 |

---

## Cross-Product Escalation

When correlation rules fire (see `correlation-rules.md`), severity is escalated beyond what either
individual event stream would produce alone.

| Condition | Escalation | Notes |
|-----------|-----------|-------|
| Motion + no badge-in (CORR-01) | Minimum High | Overrides any individual event severity below High |
| Motion + unknown device (CORR-02) | Minimum Medium | Combined physical + digital presence |
| Access denied + continued motion (CORR-03) | Minimum High | Person lingering after denial |
| Network device offline + camera offline (CORR-04) | Minimum High | Infrastructure correlation |
| Any active `unifi_list_alarms` alarm (critical/high severity) | +1 on all co-occurring events | Active alarm compounds nearby event severity |
| `EVT_IPS_IpsAlert` co-occurring with physical events | +1 on physical event severity | Cyber + physical correlation |

**Cross-product escalation is additive with time and location modifiers but caps at Critical.**

---

## Default Classification Matrix

The matrix below shows the baseline severity (before modifiers) for each event type by time period.

| Event Type | Night (22–06) | Transition (06–08, 17–22) | Business (08–17) |
|------------|:-------------:|:-------------------------:|:----------------:|
| `person` detection (high confidence) | High | Medium | Low |
| `person` detection (medium confidence) | Medium | Low | Informational |
| `vehicle` detection | Medium | Low | Informational |
| `animal` detection | Informational | Informational | Informational |
| `package` detection | Low | Informational | Informational |
| `motion` (generic, no smart detection) | Low | Informational | Informational |
| `ring` (doorbell) | Medium | Low | Low |
| `sensorOpened` | Low | Informational | Informational |
| `sensorAlarm` | High | High | Medium |
| `ACCESS_GRANT` (known user) | Low | Informational | Informational |
| `ACCESS_GRANT` (visitor pass) | Medium | Low | Low |
| `ACCESS_DENY` (single) | Low | Low | Low |
| `ACCESS_DENY` (repeated, 3+ in 10 min) | High | High | Medium |
| `DOOR_HELD_OPEN` | Medium | Low | Low |
| `DOOR_FORCED_OPEN` | High | High | High |
| `EVT_WU_Connected` (known MAC) | Informational | Informational | Informational |
| `EVT_WU_Connected` (unknown MAC) | Medium | Low | Low |
| `EVT_AP_Disconnected` | High | Medium | Medium |
| `EVT_SW_Disconnected` | High | Medium | Medium |
| `EVT_GW_Disconnected` | Critical | Critical | Critical |
| `EVT_IPS_IpsAlert` | High | High | High |
| `EVT_IPS_IpsBlock` | Medium | Medium | Medium |
| `unifi_list_alarms` critical alarm | Critical | Critical | Critical |
| `unifi_list_alarms` high alarm | High | High | High |
| `unifi_list_alarms` medium alarm | Medium | Medium | Medium |

---

## Applying the Model

The classifier evaluates each event in this order:

1. **Base severity** — look up the event type in the classification matrix using the current time period
2. **Location modifier** — apply +1 for entry points, +1 for secured interiors at night, -1 for open interiors during business hours
3. **Frequency modifier** — apply +1 or +2 if frequency thresholds are crossed
4. **Cross-product modifier** — apply correlation rule escalation if any rules fired on this event
5. **Cap at Critical** — no modifier can push severity above 5 (Critical)
6. **Floor at Informational** — no modifier can push severity below 1; suppress from narrative if Informational

The final severity determines the section of the digest the event appears in and whether an
immediate alert is warranted.

---

## Suppression Rules

To reduce noise in high-activity environments, the following events are suppressed from the digest
narrative (but remain in the raw event log):

- Informational-level events during business hours (unless the user has requested verbose output)
- `motion` events on interior cameras during business hours when no correlation rule fires
- `EVT_WU_Connected` / `EVT_WU_Disconnected` for known devices on guest SSIDs
- `ACCESS_GRANT` events for expected users during their normal access schedule
- Duplicate events of the same type on the same camera within a 5-minute window (de-duplicated to one entry with a count)
