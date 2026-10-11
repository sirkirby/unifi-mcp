# Incident Report Examples

Each example is a report written from one golden evidence set in the repository's
incident evidence corpus (`tests/fixtures/incident_evidence/cases/<case>.json`).
A golden set holds both products' sources in one document, so each example has one
document line; a live run has one line for the Network document and one for the
Protect document. The corpus exercises the evidence contract, so its query shapes
and budget usage are fixture values, reported exactly as the set states them.

Every example uses the same incident window: the user asked for 08:00 to 09:00 on
2026-08-08, America/New_York (`-04:00`), which is `2026-08-08T12:00:00Z` to
`2026-08-08T13:00:00Z`.

## Complete evidence

Golden case: `network_protect_real_shapes`

**Incident and Inputs:** AP `aa:bb:cc:00:10:02` (fixture-ap-2) went offline during
the morning. Window `2026-08-08T08:00:00-04:00` to `2026-08-08T09:00:00-04:00`
(UTC `2026-08-08T12:00:00Z` to `2026-08-08T13:00:00Z`). No `device_macs` filter.
Camera scope: every camera as unmapped context, at the user's request; the user
knew of no camera attached to the AP and no lookup tool was listed. Mappings: none
asserted. Budget limits: window 7200 s, events 500, calls 10, elapsed 60000 ms.

**Coverage and Limitations:**

Golden evidence set: overall `complete`, coverage_complete `true`; budgets window 3600/7200 s, events 0/500, calls 2/10, elapsed 850/60000 ms; exhausted: none.
- `network.events` (network, `unifi_list_events`): outcome `complete`; reasons none; failure none; queried 2026-08-08T11:04:59.000000Z to 2026-08-08T13:04:59.000000Z (`covered`); filters none; returned 3, cap 100, has_more `false`, truncation `not_truncated`; received 3, accepted 3, in-window 3, out-of-window 0, untimed 0, malformed 0, duplicates 0, conflicting 0, boundary-uncertain 0.
- `protect.events` (protect, `protect_list_events`): outcome `complete`; reasons none; failure none; queried 2026-08-08T12:00:00.000000Z to 2026-08-08T13:00:00.000000Z (`covered`); filters none; returned 2, cap 100, has_more `false`, truncation `not_truncated`; received 2, accepted 2, in-window 2, out-of-window 0, untimed 0, malformed 0, duplicates 0, conflicting 0, boundary-uncertain 0.

Every source read the full window. Protect events are from cameras with no mapping
to the AP.

**Observations:**

- `network.events|str|evt-net-0001` 2026-08-08T12:10:05.250000Z (network, `unifi_list_events`, record `evt-net-0001`): fixture-phone has connected to fixture-ap-1. `CLIENT_CONNECTED_WIRELESS_2`; mapping `not_evaluated`.
- `protect.events|str|evt-protect-0001` 2026-08-08T12:10:07.500000Z (protect, `protect_list_events`, record `evt-protect-0001`): smartDetectZone: person `smartDetectZone`; mapping `not_evaluated`.
- `network.events|str|evt-net-0002` 2026-08-08T12:30:00.000000Z (network, `unifi_list_events`, record `evt-net-0002`): fixture-laptop was blocked from accessing 198.51.100.24 by the fixture-policy Firewall Policy. `TRAFFIC_BLOCKED_KNOWN_SOURCE_CLIENT`; mapping `not_evaluated`.
- `protect.events|str|evt-protect-0002` 2026-08-08T12:40:00.000000Z (protect, `protect_list_events`, record `evt-protect-0002`): motion `motion`; mapping `not_evaluated`.
- `network.events|str|evt-net-0003` 2026-08-08T12:45:00.000000Z (network, `unifi_list_events`, record `evt-net-0003`): fixture-ap-2 disconnected. `DEVICE_DISCONNECTED_AP`; mapping `not_evaluated`.

**Hypotheses:**

- Correlation: motion on camera `cam-fixture-000b` (`evt-protect-0002`) came 5
  minutes before the disconnect (`evt-net-0003`). The camera has no mapping to the
  AP, so this is timing only. Alternatives: unrelated motion elsewhere; a power or
  uplink fault that no event in this window records.
- No event in the window names the AP's uplink switch or gateway, so an upstream
  failure is neither shown nor ruled out by these records.

**Identity:** No person is identified. The `person` smart detection is an object
class, not an identity. Client MACs `aa:bb:cc:00:20:01` and `aa:bb:cc:00:20:02`
identify devices, not their users.

**Unanswered Questions and Next Reads:**

- Did the AP come back? Offer a bounded read of the following hour with
  `unifi_get_incident_evidence` and the same budgets.
- Which camera, if any, is attached to the AP? Ask the user for the camera ID and
  the relationship, then repeat both calls with the mapping asserted.

## Healthy empty

Golden case: `healthy_empty`

**Incident and Inputs:** The user reported AP `aa:bb:cc:00:10:02` unreachable in
the morning. Window `2026-08-08T08:00:00-04:00` to `2026-08-08T09:00:00-04:00`
(UTC `2026-08-08T12:00:00Z` to `2026-08-08T13:00:00Z`). No `device_macs` filter.
Camera scope: every camera as unmapped context. Mappings: none asserted. Budget
limits: window 7200 s, events 500, calls 10, elapsed 60000 ms.

**Coverage and Limitations:**

Golden evidence set: overall `empty`, coverage_complete `true`; budgets window 3600/7200 s, events 0/500, calls 2/10, elapsed 850/60000 ms; exhausted: none.
- `network.events` (network, `unifi_list_events`): outcome `empty`; reasons none; failure none; queried 2026-08-08T11:04:59.000000Z to 2026-08-08T13:04:59.000000Z (`covered`); filters none; returned 0, cap 100, has_more `false`, truncation `not_truncated`; received 0, accepted 0, in-window 0, out-of-window 0, untimed 0, malformed 0, duplicates 0, conflicting 0, boundary-uncertain 0.
- `protect.events` (protect, `protect_list_events`): outcome `empty`; reasons none; failure none; queried 2026-08-08T12:00:00.000000Z to 2026-08-08T13:00:00.000000Z (`covered`); filters none; returned 0, cap 100, has_more `false`, truncation `not_truncated`; received 0, accepted 0, in-window 0, out-of-window 0, untimed 0, malformed 0, duplicates 0, conflicting 0, boundary-uncertain 0.

Every source read the full window. No events were recorded in the window by any
source.

**Observations:** None. Both sources completed and returned no records.

**Hypotheses:**

- No correlation to assess. The reported outage left no controller event in this
  window. Alternatives: the outage fell outside the window; the problem was on the
  client side; the controller did not log it as an event.

**Identity:** Not applicable; no records.

**Unanswered Questions and Next Reads:**

- When did the user notice the outage? If it was outside 08:00 to 09:00, offer one
  bounded read of the reported time with both evidence tools.

## Partial source from budget exhaustion

Golden case: `budget_exhaustion`

**Incident and Inputs:** Switch `aa:bb:cc:00:10:02` dropped its ports during the
morning. Window `2026-08-08T08:00:00-04:00` to `2026-08-08T09:00:00-04:00` (UTC
`2026-08-08T12:00:00Z` to `2026-08-08T13:00:00Z`). No `device_macs` filter.
Camera scope: every camera as unmapped context. Mappings: none asserted. Budget
limits: window 1800 s, events 500, calls 1, elapsed 60000 ms.

**Coverage and Limitations:**

Golden evidence set: overall `partial`, coverage_complete `false`; budgets window 3600/1800 s, events 1/500, calls 1/1, elapsed 400/60000 ms; exhausted: calls, window.
- `network.events` (network, `unifi_list_events`): outcome `partial`; reasons budget_exhausted, truncation_unknown; failure none; queried 2026-08-08T11:04:59.000000Z to 2026-08-08T13:04:59.000000Z (`covered`); filters none; returned 1, cap 100, has_more `false`, truncation `unknown`; received 1, accepted 1, in-window 1, out-of-window 0, untimed 0, malformed 0, duplicates 0, conflicting 0, boundary-uncertain 0.
- `protect.events` (protect, `protect_list_events`): outcome `not_attempted`; reasons none; failure `budget_exhausted`; queried none (`unknown`); filters none; returned 0, cap 100, has_more `null`, truncation `unknown`; received 0, accepted 0, in-window 0, out-of-window 0, untimed 0, malformed 0, duplicates 0, conflicting 0, boundary-uncertain 0.

Coverage is partial. The one-hour window exceeds the 1800-second window budget, and
the single allowed call was spent before Protect was read. Network was interrupted
after one row, so further Network events may exist. Protect was never read: this is
missing evidence, not an empty result.

**Observations:**

- `network.events|str|evt-net-1201` 2026-08-08T12:05:00.000000Z (network, `unifi_list_events`, record `evt-net-1201`): collected before the stop `K`; mapping `not_evaluated`.

**Hypotheses:**

- No correlation can be assessed from one Network row and no Protect evidence.
  Nothing here explains the port drops.

**Identity:** Station `aa:bb:cc:00:20:01` is named by the record; it identifies a
device, not a person.

**Unanswered Questions and Next Reads:**

- Offer to repeat both calls with `max_window_seconds=3600` and `max_calls=20`, or
  to split the window into two 30-minute reads. Either would change coverage.

## Unavailable Protect source

Golden case: `timeouts`

**Incident and Inputs:** AP `aa:bb:cc:00:10:01` was slow and then unreachable in
the morning. Window `2026-08-08T08:00:00-04:00` to `2026-08-08T09:00:00-04:00`
(UTC `2026-08-08T12:00:00Z` to `2026-08-08T13:00:00Z`). No `device_macs` filter.
Camera scope: every camera as unmapped context. Mappings: none asserted. Budget
limits: window 7200 s, events 500, calls 10, elapsed 60000 ms.

**Coverage and Limitations:**

Golden evidence set: overall `partial`, coverage_complete `false`; budgets window 3600/7200 s, events 0/500, calls 2/10, elapsed 850/60000 ms; exhausted: none.
- `network.events` (network, `unifi_list_events`): outcome `partial`; reasons partial_response, truncation_unknown; failure `timeout`; queried 2026-08-08T11:05:00.000000Z to 2026-08-08T13:04:59.000000Z (`covered`); filters none; returned 1, cap 100, has_more `null`, truncation `unknown`; received 1, accepted 1, in-window 1, out-of-window 0, untimed 0, malformed 0, duplicates 0, conflicting 0, boundary-uncertain 0.
- `protect.events` (protect, `protect_list_events`): outcome `timeout`; reasons none; failure `timeout`; queried none (`unknown`); filters none; returned 0, cap 100, has_more `null`, truncation `unknown`; received 0, accepted 0, in-window 0, out-of-window 0, untimed 0, malformed 0, duplicates 0, conflicting 0, boundary-uncertain 0.

Coverage is partial. Protect timed out with nothing returned: Protect is unavailable
for this window and no camera context exists. Network timed out after its first
page, so further Network events may exist.

**Observations:**

- `network.events|str|evt-net-0301` 2026-08-08T12:15:00.000000Z (network, `unifi_list_events`, record `evt-net-0301`): fixture-phone connected. `CLIENT_CONNECTED_WIRELESS_2`; mapping `not_evaluated`.

**Hypotheses:**

- No correlation can be assessed without camera evidence and with an interrupted
  Network read. Both sources timing out is itself a signal worth checking: the
  controllers or the path to them may have been slow, which is a separate question
  from the AP incident.

**Identity:** Station `aa:bb:cc:00:20:01` identifies a device, not a person.

**Unanswered Questions and Next Reads:**

- Offer to repeat both calls once with `max_elapsed_ms=120000`. If Protect fails
  again, report Protect unavailable and use the Protect setup skill to check the
  connection.

## Ambiguous camera mapping

Golden case: `mapping_outcomes`

**Incident and Inputs:** The front-door AP `aa:bb:cc:00:10:01` was dropping
clients. Window `2026-08-08T08:00:00-04:00` to `2026-08-08T09:00:00-04:00` (UTC
`2026-08-08T12:00:00Z` to `2026-08-08T13:00:00Z`). No `device_macs` filter.
Camera scope: every camera, at the user's request. Mappings asserted:

- `operator_input`: AP `aa:bb:cc:00:10:01` → camera `cam-fixture-000a`, and the
  same AP → camera `cam-fixture-000b` (the user said both cameras hang off it).
- `operator_input`: station `aa:bb:cc:00:10:fe` → location `loc-fixture-1`.
- `product_inventory`: camera `cam-fixture-000a` → itself, confirmed in the Protect
  inventory.

Budget limits: window 7200 s, events 500, calls 10, elapsed 60000 ms.

**Coverage and Limitations:**

Golden evidence set: overall `complete`, coverage_complete `true`; budgets window 3600/7200 s, events 0/500, calls 2/10, elapsed 850/60000 ms; exhausted: none.
- `network.events` (network, `unifi_list_events`): outcome `complete`; reasons none; failure none; queried 2026-08-08T11:04:59.000000Z to 2026-08-08T13:04:59.000000Z (`covered`); filters none; returned 3, cap 100, has_more `false`, truncation `not_truncated`; received 3, accepted 3, in-window 3, out-of-window 0, untimed 0, malformed 0, duplicates 0, conflicting 0, boundary-uncertain 0.
- `protect.events` (protect, `protect_list_events`): outcome `complete`; reasons none; failure none; queried 2026-08-08T12:00:00.000000Z to 2026-08-08T13:00:00.000000Z (`covered`); filters none; returned 2, cap 100, has_more `false`, truncation `not_truncated`; received 2, accepted 2, in-window 2, out-of-window 0, untimed 0, malformed 0, duplicates 0, conflicting 0, boundary-uncertain 0.

Every source read the full window. Coverage is complete; the AP's camera mapping is
ambiguous, so no AP event is attributed to one camera.

**Observations:**

- `network.events|str|evt-net-1101` 2026-08-08T12:25:00.000000Z (network, `unifi_list_events`, record `evt-net-1101`): fixture-phone has connected to fixture-front-door-ap. `CLIENT_CONNECTED_WIRELESS_2`; mapping `ambiguous` (targets `cam-fixture-000a` and `cam-fixture-000b`).
- `network.events|str|evt-net-1102` 2026-08-08T12:26:00.000000Z (network, `unifi_list_events`, record `evt-net-1102`): fixture-front-door disconnected. `DEVICE_DISCONNECTED_AP`; mapping `missing`. This device is `aa:bb:cc:00:10:02`, not the AP under investigation; the similar name establishes nothing.
- `protect.events|str|evt-protect-1101` 2026-08-08T12:26:00.000000Z (protect, `protect_list_events`, record `evt-protect-1101`): motion `motion`; mapping `verified` (camera `cam-fixture-000a`, from `product_inventory`).
- `protect.events|str|evt-protect-1102` 2026-08-08T12:26:00.000000Z (protect, `protect_list_events`, record `evt-protect-1102`): motion `motion`; mapping `missing` (camera `cam-fixture-unmapped`).
- `network.events|str|evt-net-1103` 2026-08-08T12:27:00.000000Z (network, `unifi_list_events`, record `evt-net-1103`): uppercase dashed MAC still matches exactly `K`; mapping `verified` (location `loc-fixture-1`).

**Hypotheses:**

- Correlation: motion on `cam-fixture-000a` (`evt-protect-1101`) came one minute
  after a client joined the AP (`evt-net-1101`). Because the AP maps to two cameras,
  neither camera is linked to that AP event. Alternatives: routine foot traffic;
  motion unrelated to the AP.
- `evt-protect-1102` happened in the same second as the `fixture-front-door`
  disconnect (`evt-net-1102`), but its camera is unmapped and that device is not the
  AP. Same-second timing establishes neither a mapping nor a cause.

**Identity:** No person is identified. The client and station MACs identify
devices only.

**Unanswered Questions and Next Reads:**

- Which camera is actually attached to `aa:bb:cc:00:10:01`? Ask the user, or check
  each camera's uplink with `protect_get_camera` and `unifi_get_client_details`
  where those tools are directly listed, then repeat both calls with one mapping.
- Does `aa:bb:cc:00:10:02` matter here? Ask the user before widening the
  investigation to a second device.

## Malformed and untimed timestamps

Golden case: `malformed_timestamps`

**Incident and Inputs:** Switch `aa:bb:cc:00:10:01` restarted during the morning.
Window `2026-08-08T08:00:00-04:00` to `2026-08-08T09:00:00-04:00` (UTC
`2026-08-08T12:00:00Z` to `2026-08-08T13:00:00Z`). No `device_macs` filter.
Camera scope: every camera as unmapped context. Mappings: none asserted. Budget
limits: window 7200 s, events 500, calls 10, elapsed 60000 ms.

**Coverage and Limitations:**

Golden evidence set: overall `partial`, coverage_complete `false`; budgets window 3600/7200 s, events 0/500, calls 2/10, elapsed 850/60000 ms; exhausted: none.
- `network.events` (network, `unifi_list_events`): outcome `partial`; reasons malformed_records, untimed_records; failure none; queried 2026-08-08T11:04:59.000000Z to 2026-08-08T13:04:59.000000Z (`covered`); filters none; returned 10, cap 100, has_more `false`, truncation `not_truncated`; received 10, accepted 7, in-window 1, out-of-window 0, untimed 6, malformed 3, duplicates 0, conflicting 0, boundary-uncertain 0.
- `protect.events` (protect, `protect_list_events`): outcome `partial`; reasons untimed_records; failure none; queried 2026-08-08T12:00:00.000000Z to 2026-08-08T13:00:00.000000Z (`covered`); filters none; returned 3, cap 100, has_more `false`, truncation `not_truncated`; received 3, accepted 3, in-window 0, out-of-window 0, untimed 3, malformed 0, duplicates 0, conflicting 0, boundary-uncertain 0.

Coverage is partial. Both sources queried the whole window, but 9 records have no
usable time and 3 Network rows were unreadable and dropped. Any of them may belong
to the window; none is placed in it.

**Observations:**

- `network.events|str|evt-net-0707` 2026-08-08T12:20:00.000000Z (network, `unifi_list_events`, record `evt-net-0707`): (no summary) `CLIENT_CONNECTED_WIRELESS_2`; mapping `not_evaluated`.

Untimed records, reported with their original values and never placed in the window:

- `network.events|str|evt-net-0701` time `missing` (network, `unifi_list_events`, record `evt-net-0701`): no time field `CLIENT_CONNECTED_WIRELESS_2`; mapping `not_evaluated`.
- `network.events|str|evt-net-0702` time `missing` (network, `unifi_list_events`, record `evt-net-0702`): `time` is null `CLIENT_CONNECTED_WIRELESS_2`; mapping `not_evaluated`.
- `network.events|str|evt-net-0703` time `malformed` (network, `unifi_list_events`, record `evt-net-0703`): `time` is the string "not-a-time" `CLIENT_CONNECTED_WIRELESS_2`; mapping `not_evaluated`.
- `network.events|str|evt-net-0704` time `malformed` (network, `unifi_list_events`, record `evt-net-0704`): `time` is the integer 0 `CLIENT_CONNECTED_WIRELESS_2`; mapping `not_evaluated`.
- `network.events|str|evt-net-0705` time `malformed` (network, `unifi_list_events`, record `evt-net-0705`): `time` is a boolean `CLIENT_CONNECTED_WIRELESS_2`; mapping `not_evaluated`.
- `network.events|str|evt-net-0706` time `malformed` (network, `unifi_list_events`, record `evt-net-0706`): `time` is an object `CLIENT_CONNECTED_WIRELESS_2`; mapping `not_evaluated`.
- `protect.events|str|evt-protect-0701` time `ambiguous_timezone` (protect, `protect_list_events`, record `evt-protect-0701`): `start` "2026-08-08T12:20:00" has no offset `motion`; mapping `not_evaluated`.
- `protect.events|str|evt-protect-0702` time `malformed` (protect, `protect_list_events`, record `evt-protect-0702`): `start` "2026-13-45T12:20:00Z" is not a date `motion`; mapping `not_evaluated`.
- `protect.events|str|evt-protect-0703` time `malformed` (protect, `protect_list_events`, record `evt-protect-0703`): `start` is empty `motion`; mapping `not_evaluated`.

**Hypotheses:**

- No correlation is assessed. The one timed record is a client connection at
  12:20 UTC; the camera events that might sit near it have no usable time. An
  `ambiguous_timezone` value could be 12:20 in any timezone, so reading it as UTC
  would be a guess.

**Identity:** No person is identified; the records name no account.

**Unanswered Questions and Next Reads:**

- When did the untimed events happen? Another read of the same window returns the
  same values, so no follow-up read would change coverage. Ask the user whether
  the controller's clock or firmware recently changed.
