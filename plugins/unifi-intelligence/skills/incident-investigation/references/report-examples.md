# Incident Report Examples

Each example is a report written from one golden client view in the repository's
incident evidence corpus (`tests/fixtures/incident_evidence/views/<case>.json`): the
view the evidence tools return for that case's evidence set, with the
`max_records_returned` the example names. A golden set holds both products' sources
in one document, so each example has one document line and one records line; a live
run has a pair for the Network view and a pair for the Protect view. The corpus
exercises the evidence contract, so its query shapes and budget usage are fixture
values, reported exactly as the view states them.

Every example uses the same incident window: the user asked for 08:00 to 09:00 on
2026-08-08, America/New_York (`-04:00`), which is `2026-08-08T12:00:00Z` to
`2026-08-08T13:00:00Z`.

## Complete evidence with records omitted from the view

Golden view: `network_protect_real_shapes`, max_records_returned 2

**Incident and Inputs:** AP `aa:bb:cc:00:10:02` (fixture-ap-2) went offline during
the morning. Window `2026-08-08T08:00:00-04:00` to `2026-08-08T09:00:00-04:00`
(UTC `2026-08-08T12:00:00Z` to `2026-08-08T13:00:00Z`). No `device_macs` filter.
Camera scope: every camera as unmapped context, at the user's request; the user
knew of no camera attached to the AP and no lookup tool was listed. Mappings: none
asserted. Budget limits: window 7200 s, events 500, calls 10, elapsed 60000 ms.
Records per view: `max_records_returned=2`.

**Coverage and Limitations:**

Golden evidence set: overall `complete`, coverage_complete `true`; budgets window 3600/7200 s, events 0/500, calls 2/10, elapsed 850/60000 ms; exhausted: none.
Golden evidence set records: returned 2 of 5 collected (in-window 2 of 5), max_records_returned 2; resumed after none (0 before it); omitted 3 (in-window 3, too large 0), limited by max_records_returned, next cursor 0|2026-08-08T12:10:07.500000Z|protect.events|str|evt-protect-0001; a presentation limit, not a coverage gap.
- `network.events` (network, `unifi_list_events`): outcome `complete`; reasons none; failure none; queried 2026-08-08T11:04:59.000000Z to 2026-08-08T13:04:59.000000Z (`covered`); filters none; returned 3, cap 100, has_more `false`, truncation `not_truncated`, retention `unknown`; received 3, accepted 3, in-window 3, out-of-window 0, untimed 0, malformed 0, duplicates 0, conflicting 0, boundary-uncertain 0.
- `protect.events` (protect, `protect_list_events`): outcome `complete`; reasons none; failure none; queried 2026-08-08T12:00:00.000000Z to 2026-08-08T13:00:00.000000Z (`covered`); filters none; returned 2, cap 100, has_more `false`, truncation `not_truncated`, retention `unknown`; received 2, accepted 2, in-window 2, out-of-window 0, untimed 0, malformed 0, duplicates 0, conflicting 0, boundary-uncertain 0.

Every source read the full window. Protect events are from cameras with no mapping
to the AP. Three in-window records after the cursor were collected but omitted from
the view by `max_records_returned`; they are covered, but this report cannot
describe them.

**Observations:**

- `network.events|str|evt-net-0001` 2026-08-08T12:10:05.250000Z (network, `unifi_list_events`, record `evt-net-0001`): aa:bb:cc:00:20:01 has connected to aa:bb:cc:00:10:01. `CLIENT_CONNECTED_WIRELESS_2`; mapping `not_evaluated`.
- `protect.events|str|evt-protect-0001` 2026-08-08T12:10:07.500000Z (protect, `protect_list_events`, record `evt-protect-0001`): smartDetectZone: person `smartDetectZone`; mapping `not_evaluated`.

**Hypotheses:**

- Correlation: a person detection on camera `cam-fixture-000a`
  (`protect.events|str|evt-protect-0001`) came two seconds after a phone joined a
  different AP (`network.events|str|evt-net-0001`). The camera has no mapping to
  either AP, so this is timing only. Alternatives: routine foot traffic; unrelated
  activity elsewhere.
- Nothing in the view names `aa:bb:cc:00:10:02`. Whether its disconnect was
  recorded is unknown until the omitted records are read.

**Identity:** No person is identified. The `person` smart detection is an object
class, not an identity. Client MACs `aa:bb:cc:00:20:01` and `aa:bb:cc:00:10:01`
identify devices, not their users.

**Unanswered Questions and Next Reads:**

- What do the three omitted records show? Offer to read them: repeat the same
  call with the same window, budgets and `max_records_returned=2`, adding
  `resume_after="0|2026-08-08T12:10:07.500000Z|protect.events|str|evt-protect-0001"`
  to return the records after the last one shown, or repeat the original window
  with `max_records_returned=5`.
- Which camera, if any, is attached to the AP? Ask the user for the camera ID and
  the relationship, then repeat both calls with the mapping asserted.

## Healthy empty

Golden view: `healthy_empty`, max_records_returned 25

**Incident and Inputs:** The user reported AP `aa:bb:cc:00:10:02` unreachable in
the morning. Window `2026-08-08T08:00:00-04:00` to `2026-08-08T09:00:00-04:00`
(UTC `2026-08-08T12:00:00Z` to `2026-08-08T13:00:00Z`). No `device_macs` filter.
Camera scope: every camera as unmapped context. Mappings: none asserted. Budget
limits: window 7200 s, events 500, calls 10, elapsed 60000 ms. Records per view:
`max_records_returned=25`.

**Coverage and Limitations:**

Golden evidence set: overall `empty`, coverage_complete `true`; budgets window 3600/7200 s, events 0/500, calls 2/10, elapsed 850/60000 ms; exhausted: none.
Golden evidence set records: returned 0 of 0 collected (in-window 0 of 0), max_records_returned 25; resumed after none (0 before it); omitted 0 (in-window 0, too large 0), limited by none, next cursor none; a presentation limit, not a coverage gap.
- `network.events` (network, `unifi_list_events`): outcome `empty`; reasons none; failure none; queried 2026-08-08T11:04:59.000000Z to 2026-08-08T13:04:59.000000Z (`covered`); filters none; returned 0, cap 100, has_more `false`, truncation `not_truncated`, retention `unknown`; received 0, accepted 0, in-window 0, out-of-window 0, untimed 0, malformed 0, duplicates 0, conflicting 0, boundary-uncertain 0.
- `protect.events` (protect, `protect_list_events`): outcome `empty`; reasons none; failure none; queried 2026-08-08T12:00:00.000000Z to 2026-08-08T13:00:00.000000Z (`covered`); filters none; returned 0, cap 100, has_more `false`, truncation `not_truncated`, retention `unknown`; received 0, accepted 0, in-window 0, out-of-window 0, untimed 0, malformed 0, duplicates 0, conflicting 0, boundary-uncertain 0.

Every source read the full window. No events were recorded in the window by any
source. Neither controller reports how long it keeps events (retention `unknown`),
so events older than its retention may have been discarded without a trace.

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

Golden view: `budget_exhaustion`, max_records_returned 25

**Incident and Inputs:** Switch `aa:bb:cc:00:10:02` dropped its ports during the
morning. Window `2026-08-08T08:00:00-04:00` to `2026-08-08T09:00:00-04:00` (UTC
`2026-08-08T12:00:00Z` to `2026-08-08T13:00:00Z`). No `device_macs` filter.
Camera scope: every camera as unmapped context. Mappings: none asserted. Budget
limits: window 1800 s, events 500, calls 1, elapsed 60000 ms. Records per view:
`max_records_returned=25`.

**Coverage and Limitations:**

Golden evidence set: overall `partial`, coverage_complete `false`; budgets window 3600/1800 s, events 1/500, calls 1/1, elapsed 400/60000 ms; exhausted: calls, window.
Golden evidence set records: returned 1 of 1 collected (in-window 1 of 1), max_records_returned 25; resumed after none (0 before it); omitted 0 (in-window 0, too large 0), limited by none, next cursor none; a presentation limit, not a coverage gap.
- `network.events` (network, `unifi_list_events`): outcome `partial`; reasons budget_exhausted, truncation_unknown; failure none; queried 2026-08-08T11:04:59.000000Z to 2026-08-08T13:04:59.000000Z (`covered`); filters none; returned 1, cap 100, has_more `false`, truncation `unknown`, retention `unknown`; received 1, accepted 1, in-window 1, out-of-window 0, untimed 0, malformed 0, duplicates 0, conflicting 0, boundary-uncertain 0.
- `protect.events` (protect, `protect_list_events`): outcome `not_attempted`; reasons none; failure `budget_exhausted`; queried none (`unknown`); filters none; returned 0, cap 100, has_more `null`, truncation `unknown`, retention `unknown`; received 0, accepted 0, in-window 0, out-of-window 0, untimed 0, malformed 0, duplicates 0, conflicting 0, boundary-uncertain 0.

Coverage is partial. The one-hour window exceeds the 1800-second window budget, and
the single allowed call was spent before Protect was read. Network was interrupted
after one row, so further Network events may exist. Protect was never read: this is
missing evidence, not an empty result.

**Observations:**

- `network.events|str|evt-net-1201` 2026-08-08T12:05:00.000000Z (network, `unifi_list_events`, record `evt-net-1201`): collected before the stop `K`; mapping `not_evaluated`.

**Hypotheses:**

- No correlation can be assessed from one Network row
  (`network.events|str|evt-net-1201`) and no Protect evidence. Nothing here
  explains the port drops.

**Identity:** Station `aa:bb:cc:00:20:01` is named by the record; it identifies a
device, not a person.

**Unanswered Questions and Next Reads:**

- Network's truncation is unknown. Offer to split the window into two 30-minute
  reads, `2026-08-08T08:00:00-04:00` to `2026-08-08T08:30:00-04:00` and
  `2026-08-08T08:30:00-04:00` to `2026-08-08T09:00:00-04:00`, each with both
  evidence tools and `max_window_seconds=1800`, `max_calls=20`; or to repeat both
  calls once with `max_window_seconds=3600` and `max_calls=20`. Either would change
  coverage.

## Unavailable Protect source

Golden view: `timeouts`, max_records_returned 25

**Incident and Inputs:** AP `aa:bb:cc:00:10:01` was slow and then unreachable in
the morning. Window `2026-08-08T08:00:00-04:00` to `2026-08-08T09:00:00-04:00`
(UTC `2026-08-08T12:00:00Z` to `2026-08-08T13:00:00Z`). No `device_macs` filter.
Camera scope: every camera as unmapped context. Mappings: none asserted. Budget
limits: window 7200 s, events 500, calls 10, elapsed 60000 ms. Records per view:
`max_records_returned=25`.

**Coverage and Limitations:**

Golden evidence set: overall `partial`, coverage_complete `false`; budgets window 3600/7200 s, events 0/500, calls 2/10, elapsed 850/60000 ms; exhausted: none.
Golden evidence set records: returned 1 of 1 collected (in-window 1 of 1), max_records_returned 25; resumed after none (0 before it); omitted 0 (in-window 0, too large 0), limited by none, next cursor none; a presentation limit, not a coverage gap.
- `network.events` (network, `unifi_list_events`): outcome `partial`; reasons partial_response, truncation_unknown; failure `timeout`; queried 2026-08-08T11:05:00.000000Z to 2026-08-08T13:04:59.000000Z (`covered`); filters none; returned 1, cap 100, has_more `null`, truncation `unknown`, retention `unknown`; received 1, accepted 1, in-window 1, out-of-window 0, untimed 0, malformed 0, duplicates 0, conflicting 0, boundary-uncertain 0.
- `protect.events` (protect, `protect_list_events`): outcome `timeout`; reasons none; failure `timeout`; queried none (`unknown`); filters none; returned 0, cap 100, has_more `null`, truncation `unknown`, retention `unknown`; received 0, accepted 0, in-window 0, out-of-window 0, untimed 0, malformed 0, duplicates 0, conflicting 0, boundary-uncertain 0.

Coverage is partial. Protect timed out with nothing returned: Protect is unavailable
for this window and no camera context exists. Network timed out after its first
page, so further Network events may exist.

**Observations:**

- `network.events|str|evt-net-0301` 2026-08-08T12:15:00.000000Z (network, `unifi_list_events`, record `evt-net-0301`): fixture-phone connected. `CLIENT_CONNECTED_WIRELESS_2`; mapping `not_evaluated`.

**Hypotheses:**

- No correlation can be assessed without camera evidence and with an interrupted
  Network read (`network.events|str|evt-net-0301` is its only record). Both sources
  timing out is itself a signal worth checking: the controllers or the path to them
  may have been slow, which is a separate question from the AP incident.

**Identity:** Station `aa:bb:cc:00:20:01` identifies a device, not a person.

**Unanswered Questions and Next Reads:**

- Offer to repeat both calls once with `max_elapsed_ms=120000`. If Protect fails
  again, report Protect unavailable and use the Protect setup skill to check the
  connection.
- Network's truncation is unknown. Offer to split the window into two 30-minute
  reads with `unifi_get_incident_evidence`, `2026-08-08T08:00:00-04:00` to
  `2026-08-08T08:30:00-04:00` and `2026-08-08T08:30:00-04:00` to
  `2026-08-08T09:00:00-04:00`, so each part is read in less time.

## Ambiguous camera mapping

Golden view: `mapping_outcomes`, max_records_returned 25

**Incident and Inputs:** The front-door AP `aa:bb:cc:00:10:01` was dropping
clients. Window `2026-08-08T08:00:00-04:00` to `2026-08-08T09:00:00-04:00` (UTC
`2026-08-08T12:00:00Z` to `2026-08-08T13:00:00Z`). No `device_macs` filter.
Camera scope: every camera, at the user's request. Mappings asserted:

- `operator_input`: AP `aa:bb:cc:00:10:01` → camera `cam-fixture-000a`, and the
  same AP → camera `cam-fixture-000b` (the user said both cameras hang off it).
- `operator_input`: station `aa:bb:cc:00:10:fe` → location `loc-fixture-1`.
- `product_inventory`: camera `cam-fixture-000a` → itself, confirmed in the Protect
  inventory.

Budget limits: window 7200 s, events 500, calls 10, elapsed 60000 ms. Records per
view: `max_records_returned=25`.

**Coverage and Limitations:**

Golden evidence set: overall `complete`, coverage_complete `true`; budgets window 3600/7200 s, events 0/500, calls 2/10, elapsed 850/60000 ms; exhausted: none.
Golden evidence set records: returned 5 of 5 collected (in-window 5 of 5), max_records_returned 25; resumed after none (0 before it); omitted 0 (in-window 0, too large 0), limited by none, next cursor none; a presentation limit, not a coverage gap.
- `network.events` (network, `unifi_list_events`): outcome `complete`; reasons none; failure none; queried 2026-08-08T11:04:59.000000Z to 2026-08-08T13:04:59.000000Z (`covered`); filters none; returned 3, cap 100, has_more `false`, truncation `not_truncated`, retention `unknown`; received 3, accepted 3, in-window 3, out-of-window 0, untimed 0, malformed 0, duplicates 0, conflicting 0, boundary-uncertain 0.
- `protect.events` (protect, `protect_list_events`): outcome `complete`; reasons none; failure none; queried 2026-08-08T12:00:00.000000Z to 2026-08-08T13:00:00.000000Z (`covered`); filters none; returned 2, cap 100, has_more `false`, truncation `not_truncated`, retention `unknown`; received 2, accepted 2, in-window 2, out-of-window 0, untimed 0, malformed 0, duplicates 0, conflicting 0, boundary-uncertain 0.

Every source read the full window. Coverage is complete; the AP's camera mapping is
ambiguous, so no AP event is attributed to one camera.

**Observations:**

- `network.events|str|evt-net-1101` 2026-08-08T12:25:00.000000Z (network, `unifi_list_events`, record `evt-net-1101`): aa:bb:cc:00:20:01 has connected to aa:bb:cc:00:10:01. `CLIENT_CONNECTED_WIRELESS_2`; mapping `ambiguous` (targets `cam-fixture-000a` and `cam-fixture-000b`).
- `network.events|str|evt-net-1102` 2026-08-08T12:26:00.000000Z (network, `unifi_list_events`, record `evt-net-1102`): aa:bb:cc:00:10:02 disconnected. `DEVICE_DISCONNECTED_AP`; mapping `missing`. This device is not the AP under investigation.
- `protect.events|str|evt-protect-1101` 2026-08-08T12:26:00.000000Z (protect, `protect_list_events`, record `evt-protect-1101`): motion `motion`; mapping `verified` (camera `cam-fixture-000a`, from `product_inventory`).
- `protect.events|str|evt-protect-1102` 2026-08-08T12:26:00.000000Z (protect, `protect_list_events`, record `evt-protect-1102`): motion `motion`; mapping `missing` (camera `cam-fixture-unmapped`).
- `network.events|str|evt-net-1103` 2026-08-08T12:27:00.000000Z (network, `unifi_list_events`, record `evt-net-1103`): uppercase dashed MAC still matches exactly `K`; mapping `verified` (location `loc-fixture-1`).

**Hypotheses:**

- Correlation: motion on `cam-fixture-000a` (`protect.events|str|evt-protect-1101`)
  came one minute after a client joined the AP (`network.events|str|evt-net-1101`).
  Because the AP maps to two cameras, neither camera is linked to that AP event.
  Alternatives: routine foot traffic; motion unrelated to the AP.
- `protect.events|str|evt-protect-1102` happened in the same second as the
  `aa:bb:cc:00:10:02` disconnect (`network.events|str|evt-net-1102`), but its camera
  is unmapped and that device is not the AP. Same-second timing establishes neither
  a mapping nor a cause.

**Identity:** No person is identified. The client and station MACs identify
devices only.

**Unanswered Questions and Next Reads:**

- Which camera is actually attached to `aa:bb:cc:00:10:01`? Ask the user, or check
  each camera's uplink with `protect_get_camera` and `unifi_get_client_details`
  where those tools are directly listed, then repeat both calls with one mapping.
- Does `aa:bb:cc:00:10:02` matter here? Ask the user before widening the
  investigation to a second device.

## Malformed and untimed timestamps

Golden view: `malformed_timestamps`, max_records_returned 25

**Incident and Inputs:** Switch `aa:bb:cc:00:10:01` restarted during the morning.
Window `2026-08-08T08:00:00-04:00` to `2026-08-08T09:00:00-04:00` (UTC
`2026-08-08T12:00:00Z` to `2026-08-08T13:00:00Z`). No `device_macs` filter.
Camera scope: every camera as unmapped context. Mappings: none asserted. Budget
limits: window 7200 s, events 500, calls 10, elapsed 60000 ms. Records per view:
`max_records_returned=25`.

**Coverage and Limitations:**

Golden evidence set: overall `partial`, coverage_complete `false`; budgets window 3600/7200 s, events 0/500, calls 2/10, elapsed 850/60000 ms; exhausted: none.
Golden evidence set records: returned 10 of 10 collected (in-window 1 of 1), max_records_returned 25; resumed after none (0 before it); omitted 0 (in-window 0, too large 0), limited by none, next cursor none; a presentation limit, not a coverage gap.
- `network.events` (network, `unifi_list_events`): outcome `partial`; reasons malformed_records, untimed_records; failure none; queried 2026-08-08T11:04:59.000000Z to 2026-08-08T13:04:59.000000Z (`covered`); filters none; returned 10, cap 100, has_more `false`, truncation `not_truncated`, retention `unknown`; received 10, accepted 7, in-window 1, out-of-window 0, untimed 6, malformed 3, duplicates 0, conflicting 0, boundary-uncertain 0.
- `protect.events` (protect, `protect_list_events`): outcome `partial`; reasons untimed_records; failure none; queried 2026-08-08T12:00:00.000000Z to 2026-08-08T13:00:00.000000Z (`covered`); filters none; returned 3, cap 100, has_more `false`, truncation `not_truncated`, retention `unknown`; received 3, accepted 3, in-window 0, out-of-window 0, untimed 3, malformed 0, duplicates 0, conflicting 0, boundary-uncertain 0.

Coverage is partial. Both sources queried the whole window, but 9 records have no
usable time and 3 Network rows were unreadable and dropped. Any of them may belong
to the window; none is placed in it.

**Observations:**

- `network.events|str|evt-net-0707` 2026-08-08T12:20:00.000000Z (network, `unifi_list_events`, record `evt-net-0707`): (no summary) `CLIENT_CONNECTED_WIRELESS_2`; mapping `not_evaluated`.

Untimed records, reported with their original values and never placed in the window:

- `network.events|str|evt-net-0701` time `missing` (network, `unifi_list_events`, record `evt-net-0701`): no time field `CLIENT_CONNECTED_WIRELESS_2`; mapping `not_evaluated`; no original time field.
- `network.events|str|evt-net-0702` time `missing` (network, `unifi_list_events`, record `evt-net-0702`): (no summary) `CLIENT_CONNECTED_WIRELESS_2`; mapping `not_evaluated`; original `time` is null.
- `network.events|str|evt-net-0703` time `malformed` (network, `unifi_list_events`, record `evt-net-0703`): (no summary) `CLIENT_CONNECTED_WIRELESS_2`; mapping `not_evaluated`; original `time` is the string "not-a-time".
- `network.events|str|evt-net-0704` time `malformed` (network, `unifi_list_events`, record `evt-net-0704`): (no summary) `CLIENT_CONNECTED_WIRELESS_2`; mapping `not_evaluated`; original `time` is the integer 0.
- `network.events|str|evt-net-0705` time `malformed` (network, `unifi_list_events`, record `evt-net-0705`): (no summary) `CLIENT_CONNECTED_WIRELESS_2`; mapping `not_evaluated`; original `time` is a boolean.
- `network.events|str|evt-net-0706` time `malformed` (network, `unifi_list_events`, record `evt-net-0706`): (no summary) `CLIENT_CONNECTED_WIRELESS_2`; mapping `not_evaluated`; original `time` is an object.
- `protect.events|str|evt-protect-0701` time `ambiguous_timezone` (protect, `protect_list_events`, record `evt-protect-0701`): motion `motion`; mapping `not_evaluated`; original `start` "2026-08-08T12:20:00" has no offset.
- `protect.events|str|evt-protect-0702` time `malformed` (protect, `protect_list_events`, record `evt-protect-0702`): motion `motion`; mapping `not_evaluated`; original `start` "2026-13-45T12:20:00Z" is not a date.
- `protect.events|str|evt-protect-0703` time `malformed` (protect, `protect_list_events`, record `evt-protect-0703`): motion `motion`; mapping `not_evaluated`; original `start` is empty.

**Hypotheses:**

- No correlation is assessed. The one timed record
  (`network.events|str|evt-net-0707`) is a client connection at 12:20 UTC; the
  camera events that might sit near it have no usable time. An `ambiguous_timezone`
  value could be 12:20 in any timezone, so reading it as UTC would be a guess.

**Identity:** No person is identified; the records name no account.

**Unanswered Questions and Next Reads:**

- When did the untimed events happen? Another read of the same window returns the
  same values, so no follow-up read would change coverage. Ask the user whether
  the controller's clock or firmware recently changed.
