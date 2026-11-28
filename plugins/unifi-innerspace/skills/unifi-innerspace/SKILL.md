---
name: unifi-innerspace
description: Read UniFi InnerSpace floor plans, plan images, placed devices, walls and attenuation on a UniFi console, and edit a plan's layout with a preview before every change. Use unifi-innerspace-setup for a missing login or setup failure.
---

# UniFi InnerSpace

## Dependencies

Requires: innerspace
Optional: none

## Session boundary

This server talks to the InnerSpace application on one UniFi console, using
that console's login session: a username and password. It never uses an API
key, and a console API key must not be used for InnerSpace.

InnerSpace site, project, floor plan, device and wall IDs are scoped to the
InnerSpace tool family. Do not pass them to Network, Protect, Access or Site
Manager tools, and do not translate between them by matching names.

Whether InnerSpace is installed and running comes only from
`innerspace_get_status`. A 403 `errors.api.access` means the session is
missing, expired or lacks access to InnerSpace; it never means the application
is absent. Run `innerspace_get_status` first when a tool says InnerSpace is not
installed or not running.

## Discover and read

It provides 24 domain tools, plus 6 meta-tools.
In default lazy mode the read-only tools are listed directly. Start with
`innerspace_list_floor_plans` or `innerspace_get_project` for plan IDs, then
`innerspace_list_walls`, `innerspace_list_placed_devices`,
`innerspace_list_access_points`, `innerspace_list_switches` or
`innerspace_list_inventory`. `innerspace_get_plan_asset` returns a plan's
image metadata and the `resource_uri` to read the image from: an MCP resource,
`innerspace://plans/{plan_id}/image` for a PNG plan and
`innerspace://plans/{plan_id}/image.jpg` for a JPEG one. Read the URI the tool
returns rather than building one; the PNG resource refuses a JPEG plan.

The writes are not listed directly. Find one with `innerspace_tool_index`,
filtered by name or search, and request `include_schemas=True` for the
intended tool. Call it through `innerspace_execute` with its `tool` and
`arguments` fields, or load it with `innerspace_load_tools` in a client that
handles tool-list changes. `innerspace_batch` runs several calls as jobs, reads
side by side and writes one at a time; `innerspace_batch_status` and
`innerspace_batch_cancel` follow and withdraw its jobs.

Read [the tool reference](references/innerspace-tools.md) for every tool and
its type before constructing a call.

## Units and positions

Lengths come back in the project's unit, `metric` (metres) or `imperial`
(feet), and every result says which in its `unit` field; pass `unit` to
override it for one call. Positions are measured from the plan's top-left,
`y` down. They line up with the plan image only when the plan's `image_scale`
is 1 and its `image_offset` is (0, 0); both come back with each plan. A plan
with `scale_missing` has no usable scale, so its positions and lengths are
null. `innerspace_list_walls` and `innerspace_list_placed_devices` take
`limit`; when the result says `truncated`, raise it before drawing conclusions
from the list.

## Writes

Every write previews first unless the permission mode is `bypass`
(`UNIFI_INNERSPACE_TOOL_PERMISSION_MODE`, or a global
`UNIFI_TOOL_PERMISSION_MODE` when the InnerSpace one is unset). Call it
without `confirm` (or `confirm=False`), show the preview to the user, and call
again with `confirm=True` only after the user agrees. Every write that takes
a length or position needs `unit`. A confirm reads the console again and reports `mutation_applied`: `true` is
applied and read back, `false` is not applied or nothing to change, and
`null` is unknown. On `null`, read before retrying. When the server requires
preview tokens (`UNIFI_INNERSPACE_REQUIRE_PREVIEW_TOKEN`), send the preview's
`preview_token` back with `confirm=True`.

A write refused because the console is busy (another write holds its turn) or
because its time budget ran out before the send returns `success: false` and
`mutation_applied: false`: nothing was sent. Read the plan again, then retry
after a short wait, or send the change through `innerspace_batch`, which waits
its turn.

Writes are refused, before anything is sent, while InnerSpace is not
installed or not running. A confirmed write shows
the console stored the values, not that coverage changed. The server's
`UNIFI_POLICY_INNERSPACE_*` gates turn off kinds of writes; the plugin's setup
saves the create, update and delete gates off unless the user opts in.

## Coverage and Limitations

The tools read what the InnerSpace application holds for this console's
project. They do not create or delete floor plans, replace or upload plan
images, or place devices, and they do not measure coverage. A failed or
capped read is not an empty plan: report unavailable, truncated and
`scale_missing` results as such. With no host configured the server starts in
setup mode; use `unifi-innerspace-setup`.
