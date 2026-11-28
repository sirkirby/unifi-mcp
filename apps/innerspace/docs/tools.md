# Tools — InnerSpace Server

24 domain tools (without the six meta-tools) over a console's UniFi InnerSpace application: nine reads and 15 [writes](#writes). To install the server, see the [README](../README.md#install). Every read returns `{"success": true, "data": ...}` or `{"success": false, "error": "..."}`; the writes return a preview or a verified result, described [below](#writes).

The examples use made-up ids and values. Responses leave out any single value the console did not send, so a real response may have fewer fields than shown.

This server has no events, no event stream and no support-bundle tool. It has two MCP resources, the [plan image resources](#the-plan-image-resources), one per image type. It does not create or delete floor plans, replace or upload plan images, remove wall types or attenuation-object types, or place devices.

## IDs

Floor plan, site, device and wall ids returned by these tools belong to the InnerSpace tool family. They are not the ids the Network, Protect, Access or Site Manager servers use, and there is no translation between them. Take `plan_id` from `innerspace_list_floor_plans` or `innerspace_get_project`, and `site_id` from the `site_id` field of a plan.

## Units and lengths

Lengths come back in the project's display unit, `metric` (metres) or `imperial` (feet), and every result says which in its `unit` field. Pass `unit` to override it for one call. A project whose unit is missing or not recognised is an error, not a default.

## Limits and truncation

`innerspace_list_walls` and `innerspace_list_placed_devices` take `limit` (1-2000, default 500). The result reports `total` and `truncated`; when `truncated` is `true`, the list was cut at `limit`, so raise it to see more. The other lists return every entry and carry a `count`.

`scale_missing: true` means the plan has no usable scale, so positions and lengths on it are `null`.

## Status

### `innerspace_get_status`

Whether the InnerSpace application is installed and running on the console, with its installed version and any update available. It reads the console's system endpoint, not InnerSpace itself, so run it first when another tool reports that InnerSpace is not installed or not running.

No arguments.

```json
{"success": true, "data": {"installed": true, "running": true, "version": "1.2.3", "update_available": null}}
```

## Project

### `innerspace_get_project`

The project: title, unit, its floor plans with scale and image placement, wall types and attenuation object types.

| Argument | Type | Default |
|---|---|---|
| `include_shapes` | boolean | `false`; `true` adds every shape of the project (large) |
| `unit` | `metric` or `imperial` | the project's unit |

```json
{"success": true, "data": {
  "project": {"id": "project-0001", "title": "Example house", "unit": "metric"},
  "unit": "metric",
  "plans": [{"id": "plan-0001", "title": "Ground floor", "scale_per_unit": 50.0, "scale_missing": false,
             "image_scale": 1.0, "image_offset": [0.0, 0.0], "shape_counts": {"wall": 24}}],
  "wall_types": [{"id": "wt-0001", "name": "Drywall", "attenuation_db": 3.0}],
  "attenuation_object_types": []
}}
```

### `innerspace_list_walls`

The walls of one floor plan, with end points `x1`, `y1`, `x2`, `y2`, `length`, `variant` and `wall_type_id`, in the plan's own coordinate frame (see [Coordinates](#coordinates-and-the-plan-image)). `unreadable` counts walls without exactly two readable end points; their coordinates are `null`.

| Argument | Type | Default |
|---|---|---|
| `plan_id` | string, required | |
| `limit` | integer, 1-2000 | `500` |
| `unit` | `metric` or `imperial` | the project's unit |

```json
{"success": true, "data": {
  "unit": "metric", "plan_id": "plan-0001", "total": 24, "truncated": false, "scale_missing": false, "unreadable": 0,
  "walls": [{"id": "wall-0001", "plan_id": "plan-0001", "x1": 0.0, "y1": 0.0, "x2": 4.2, "y2": 0.0, "length": 4.2,
             "variant": "interior", "wall_type_id": "wt-0001"}]
}}
```

## Floor plans

### `innerspace_list_floor_plans`

The floor plans, with scale, image size, image file name and the image's scale and offset. Optionally filtered by InnerSpace site.

| Argument | Type | Default |
|---|---|---|
| `site_id` | string | every site |

```json
{"success": true, "data": {"floor_plans": [{
  "id": "plan-0001", "name": "Ground floor", "floor_number": 0, "site_id": "site-0001", "unit": "metric",
  "scale_per_unit": 50.0, "width_px": 2000.0, "height_px": 1400.0, "origin_x": 0.0, "origin_y": 0.0,
  "image_filename": "plan-image.png", "image_scale": 1.0, "image_offset": [0.0, 0.0]
}], "count": 1}}
```

### `innerspace_get_plan_asset`

The image metadata of one plan (file name, content type, pixel size, scale, image scale and offset, unit) and the `resource_uri` the image is read from: `innerspace://plans/{plan_id}/image` for a PNG, `innerspace://plans/{plan_id}/image.jpg` for a JPEG. No tool returns the image itself; read it through [the plan image resources](#the-plan-image-resources).

| Argument | Type | Default |
|---|---|---|
| `plan_id` | string, required | |

```json
{"success": true, "data": {
  "filename": "00000000-0000-0000-0000-000000000000.png", "content_type": "image/png",
  "width_px": 2000.0, "height_px": 1400.0, "scale_per_unit": 50.0, "image_scale": 1.0, "image_offset": [0.0, 0.0],
  "unit": "metric", "resource_uri": "innerspace://plans/plan-0001/image"
}}
```

[`unifi-api-server`](../../api/README.md#innerspace-console-product) returns the same metadata and never returns image bytes.

## Devices

### `innerspace_list_placed_devices`

Devices placed on one floor plan, with `x`, `y`, `height`, `mount` and `rotation`, in the project's unit. Reports `total` and `truncated` like walls.

| Argument | Type | Default |
|---|---|---|
| `plan_id` | string, required | |
| `limit` | integer, 1-2000 | `500` |
| `unit` | `metric` or `imperial` | the project's unit |

### `innerspace_list_access_points`

Access points in the whole project with `x`, `y`, `height`, `azimuth`, `mount`, `status` and `floor_plan_id`. `scale_missing` is `true` for an access point whose plan has no usable scale; its `x` and `y` are then `null`.

| Argument | Type | Default |
|---|---|---|
| `site_id` | string | every site |
| `unit` | `metric` or `imperial` | the project's unit |

### `innerspace_list_switches`

Switches in the whole project with `x`, `y`, `type`, `status` and `floor_plan_id`, in the same way.

| Argument | Type | Default |
|---|---|---|
| `site_id` | string | every site |
| `unit` | `metric` or `imperial` | the project's unit |

### `innerspace_list_inventory`

Devices the console has adopted that are not yet placed on a floor plan: `id`, `name`, `model`, `mac` and `serial`.

| Argument | Type | Default |
|---|---|---|
| `site_id` | string | every site |

MAC addresses and serial numbers in these results are not redacted.

## Writes

Fifteen tools change the layout. Each one previews first and changes the console only on `confirm=true`:

- `confirm=false` (the default) runs the same app check as a confirm, reads the console and returns `{"success": true, "requires_confirmation": true, "preview": {...}}`. Nothing is sent. The preview shows the current and proposed values, the fields a change clears, counts and a bounding box (first five items in full), and effects such as the walls that use a wall type or the devices a scale change shifts.
- `confirm=true` reads again, refuses an object that has gone, changed type or moved to another plan since, sends one request and reads the result back.

A write and its preview are refused while InnerSpace is not installed or not running. One write runs at a time per server process. The browser editor, other processes and `unifi-api-server` are not locked out, which is why a confirm reads again.

A confirmed write shows that the console stored the values. That is configuration only: it does not show that coverage or any traffic changed.

### The result of a confirm

| `success` | `mutation_applied` | Meaning |
|---|---|---|
| `true` | `true` | Sent, and the read-back shows every change. `created_ids` lists new objects. |
| `true` | `false` | Nothing was sent: the console already holds the values (`message` starts "No change"), an earlier identical create already made the objects (`noop: "already_applied"`, `message` starts "Already applied"), or none of the ids a remove names is in the project (`noop: "none_found"`, `message` starts "Nothing to remove"). |
| `false` | `false` | Nothing was applied: the console refused the write (an HTTP 4xx, or UniFi OS refusing it again on a fresh session) and the read-back shows no change; or the write's time budget ran out before it was sent; or the console's write turn was not free in time. |
| `false` | `null` | The outcome is unknown: the answer was lost or was not a refusal (a 5xx, 429 or an unreadable answer) and the read-back does not show every change yet, or the read-back failed or shows only part of the change. Read before retrying. |

`missing` lists the changes the read-back did not find, `effects` and `warnings` repeat the preview's, and `error` carries fixed text that says what the console answered.

```json
{"success": true, "mutation_applied": true, "operation": "create InnerSpace walls",
 "created_ids": ["wall-0101"], "missing": [], "effects": {}, "warnings": [],
 "message": "Walls created and read back."}
```

New ids follow from the tool and its arguments, so repeating a confirm whose answer was lost finds its objects and sends nothing. An identical second create is the same call and is also reported as already applied; to make an intentional copy, change an argument. If an object an identical earlier call created was changed since, or some of those objects were removed while others remain, the call is refused: change an argument or remove the existing object. If all of them were removed, the call creates them again under the same ids. A remove whose objects are all gone from the project already sends nothing; one that names some objects that are gone is refused. If a confirm's outcome is unknown, read before retrying.

### Units, coordinates and limits

Every write that takes a length or a position has a required `unit`, so a change of the project's unit between a preview and its confirm cannot rescale it. Positions use the same frame as the reads (`coordinates: "frame"`, the default): from the plan's top-left, `y` down, in `unit`. That frame is refused on a plan whose image is shifted or scaled, on a plan without a usable scale or image size, and outside the image; pass `coordinates: "plan_units"` to send the console's own values instead. An update that carries no position, such as a material change, is never refused for this.

At most 100 objects per create or update and 50 per remove. Write arguments use the names the reads return (`x1`, `y1`, `x2`, `y2`, `variant`, `wall_type_id`, `attenuation_db`), and an update names only the fields to change: the stored object is read and sent whole with those fields changed. A field you don't name keeps the value read at the confirm, so an edit made in the InnerSpace app at the same moment can be overwritten.

### Write tools

| Tool | Category | Action | Arguments |
|---|---|---|---|
| `innerspace_create_walls` | `walls` | create | `plan_id`, `walls` (`x1`, `y1`, `x2`, `y2`, `variant`, `wall_type_id`), `unit`, `coordinates` |
| `innerspace_update_walls` | `walls` | update | `plan_id`, `walls` (`id` and the fields to change; all four end points together), `unit`, `coordinates` |
| `innerspace_remove_walls` | `walls` | delete | `plan_id`, `wall_ids` |
| `innerspace_create_wall_type` | `wall_types` | create | `name`, `attenuation_db` (0-99), `color` (`#RRGGBB`), `transparent` |
| `innerspace_update_wall_type` | `wall_types` | update | `wall_type_id` and any of `name`, `attenuation_db`, `color`, `transparent` |
| `innerspace_create_attenuation_objects` | `attenuation` | create | `plan_id`, `objects` (`points`, `variant`, `attenuation_object_type_id`), `unit`, `coordinates` |
| `innerspace_update_attenuation_objects` | `attenuation` | update | `plan_id`, `objects` (`id` and the fields to change), `unit`, `coordinates` |
| `innerspace_remove_attenuation_objects` | `attenuation` | delete | `plan_id`, `object_ids` |
| `innerspace_create_attenuation_object_type` | `attenuation` | create | `name`, `attenuation_db` (0-99), `color` |
| `innerspace_update_attenuation_object_type` | `attenuation` | update | `attenuation_object_type_id` and any of `name`, `attenuation_db`, `color` |
| `innerspace_rename_floor_plan` | `floor_plans` | update | `plan_id`, `title` (1-32 characters) |
| `innerspace_set_floor_attenuation` | `floor_plans` | update | `plan_id`, `attenuation_db` (1-99, or `null` for the app default of 20 dB) |
| `innerspace_reorder_floor_plans` | `floor_plans` | update | `plan_ids`: every plan once, lowest floor first; the plans are renumbered 1, 2, 3 ..., so plans that share an order value lose the tie |
| `innerspace_set_plan_scale` | `floor_plans` | delete | `plan_id`, `x1`, `y1`, `x2`, `y2`, `length`, `unit`, `coordinates` |
| `innerspace_set_project_unit` | `project` | update | `unit` |

Every write also takes `confirm`. Notes:

- A wall `variant` is a built-in material (`concrete`, `drywall`, `drywall_heavy`, `glass`, `glass_thin`, `brick`, `metal`, `wood`, `door_wood`, `door_metal`, `door_glass`, `window_1_pane`, `window_2_pane`, `window_3_pane`) or `custom` with the `wall_type_id` of a project wall type. Changing a custom wall to a built-in material clears its wall type; the preview lists it under `cleared`.
- An attenuation object is a closed polygon: 4 to 100 `points` (`x`, `y`), the last repeating the first. Its `variant` is `car`, `cubicles`, `elevator`, `foliage_heavy`, `foliage_light`, `human_crowd`, `machinery`, `server_rack`, `shelf_small`, `shelf_medium`, `shelf_warehouse`, `truck`, or `custom` with an `attenuation_object_type_id`. Attenuation objects are listed by `innerspace_get_project` with `include_shapes`.
- A wall type or attenuation-object type is project-wide: an update changes every wall or object that uses it, on every plan, and the preview counts them.
- `innerspace_set_plan_scale` replaces the plan's scale line in one request. It is destructive and gated as a delete: every length on the plan is measured by it, and the preview counts the placed devices that shift on the image. `length` and the points take the call's own `unit`, whatever the project unit. Repeating a confirm that already replaced the line sends nothing.
- `innerspace_set_project_unit` changes how the app displays lengths. Stored positions do not change, but reads without a `unit` argument answer in the new unit.
- Removing walls and attenuation objects is gated as a delete. The console has no undo.

## Coordinates and the plan image

Positions use the plan frame of the documented InnerSpace API: distance from the plan's top-left corner, `x` to the right and `y` downward, in the project's unit (or the `unit` you passed). The frame lines up with the plan image only when the plan's `image_scale` is `1` and its `image_offset` is `(0, 0)`. Both come with each plan, from `innerspace_list_floor_plans`, `innerspace_get_project` and `innerspace_get_plan_asset`.

To place a returned position (`x`, `y`) on the plan image, take W = `width_px`, H = `height_px`, s = `image_scale`, (ox, oy) = `image_offset` and k = `scale_per_unit` (plan units per metre, or per foot when the unit is imperial):

1. Back to the console's plan units: `plan_x = x*k - W/2` and `plan_y = H/2 - y*k`.
2. Then to image pixels: `px = (plan_x - ox)/s + W/2` and `py = H/2 - (plan_y - oy)/s`.

With `s = 1` and `(ox, oy) = (0, 0)` this reduces to `px = x*k` and `py = y*k`. When the console sent no image scale or offset, or the map scales y differently from x, those fields are `null`: do not assume a value, and treat the position as not placeable on the image.

This is geometry only. It does not show that a device is where the plan says it is, and it says nothing about radio coverage.

## The plan image resources

Two resource templates return a plan's image, one per image type, since a template declares one MIME type: `innerspace://plans/{plan_id}/image` (`image/png`) and `innerspace://plans/{plan_id}/image.jpg` (`image/jpeg`). `innerspace_get_plan_asset` returns the right URI for each plan. They are fetched on demand and do not support subscriptions. The plan's metadata is read once, and a plan whose image is the other type is refused with fixed text naming the template that serves it, and its image is never downloaded.

The image is capped at 8,000,000 bytes. A larger image, or a response that is not an image of the type the plan's address promises (checked by content type and file header), is refused with fixed text rather than returned. Only the plan's own image address is ever requested, and only when it matches the console's asset address pattern and the plan's map in the project; no file name comes from the caller. Each read takes a read slot at the console's operation gate, like a tool call.

The resources are registered only beside `innerspace_get_plan_asset`: in eager mode, a category or tool filter that leaves that tool out leaves them out too. In setup mode no resource is registered.

## Meta-tools

Besides the 24 domain tools the server registers six meta-tools, `innerspace_tool_index`, `innerspace_execute`, `innerspace_batch`, `innerspace_batch_status`, `innerspace_batch_cancel` and `innerspace_load_tools`, as the other servers do. They are not counted among the 24 and are not all read-only; see [permissions.md](permissions.md#meta-tools-and-read-only-clients) and [MCP discovery and meta-tools](../../../docs/tool-index.md). In the default lazy mode the nine reads are listed directly and the writes are reached through `innerspace_execute`, or listed after `innerspace_load_tools`.

## Errors

Errors use fixed text built from the operation, the HTTP status and an error code: never a response body, the console address, a request path or an exception's text. An argument the server rejects is reported as `invalid arguments` and its value is never repeated; for a write, the error also names the field and the rule it broke (`walls.0.variant: Input should be ...`). An argument of the wrong type (text for `limit`) is rejected before the tool runs by the MCP framework, whose error to the caller quotes the value; the server's log names only the argument. The cases you will see are in [troubleshooting.md](troubleshooting.md).
