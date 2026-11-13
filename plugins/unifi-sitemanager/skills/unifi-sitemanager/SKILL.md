---
name: unifi-sitemanager
description: Read UniFi Site Manager account-wide cloud inventory, WAN metrics, and SD-WAN status. Use for cloud hosts, sites or devices; use unifi-sitemanager-setup for a missing key or setup failure.
---

# UniFi Site Manager

## Dependencies

Requires: sitemanager
Optional: none

## Account boundary

This server reads `https://api.ui.com` using one Site Manager account API key.
The key can see the whole account, across every accessible host and site.
Before an account-wide read, explain this scope and agree on the requested data.
It requires internet access and Ubiquiti's cloud service, even for nearby consoles.
All nine domain tools are read-only. There are no writes, policy gates, or
support-bundle tool. Console management uses separate product servers.

These IDs are scoped to the Site Manager tool family — do not pass them to
Network, Protect, or Access tools. Console IDs are not interchangeable with
Site Manager IDs; never translate them by matching names.

## Discover and read

It provides 9 read-only domain tools, plus 5 meta-tools.
Domain reads cover hosts, sites, devices, ISP metrics and SD-WAN. In default lazy mode, start
with `sitemanager_tool_index`, filtered by name or search, and request
`include_schemas=True` for the intended tool. Use `sitemanager_execute` with
its `tool` and `arguments` fields when the domain tool is not directly listed.
`sitemanager_load_tools` loads selected tools for clients that handle tool-list
changes; `sitemanager_batch` and `sitemanager_batch_status` handle bounded groups
of reads. The loader and dispatchers' non-read-only annotations describe local
registration and dispatch, not cloud mutations.

Read [the tool reference](references/sitemanager-tools.md) for all nine tools
and their parameter names before constructing a call.

## Bounds and reporting

Inventory pages accept `page_size` from 1 to 500. Choose a page and call budget
before reading. Pass `next_cursor` back as `cursor` while budget remains;
an empty page can still have a next cursor. Stop when it is absent, and state
partial coverage when a budget stops paging. Device reads can filter up to
100 `host_ids` and an `updated_since` timestamp.

For metrics choose either `duration` or a pair of RFC 3339 timestamps.
`metric_type="5m"` covers up to 24 hours; `metric_type="1h"` covers up to
30 days, with durations `7d` or `30d`. Bound `period_limit` to 0–720 per site;
0 returns summaries alone, and summaries cover the whole selected window.
Targeted queries accept 1–50 sites with Site Manager host and site IDs.
Report the window, returned counts, paging limits, and any `partial` result.
Cloud-reported state can lag a console; do not call it real-time evidence.

## Coverage and Limitations

Inventory and health cover only what the account and cloud API expose. A missing
site, stale value or failed read does not prove a healthy network. Keep unavailable,
partial and capped reads visible in the answer. This server cannot configure a
console, change access, retrieve recordings or generate a support bundle.
With no key it starts in keyless setup mode; use `unifi-sitemanager-setup`.
