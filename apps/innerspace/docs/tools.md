# Tools — InnerSpace Server

Nine read-only domain tools (9, without the six meta-tools) over a console's UniFi InnerSpace application. The server is not yet released; see the [README](../README.md#run-from-source) to run it from a checkout. Every tool returns `{"success": true, "data": ...}` or `{"success": false, "error": "..."}`.

The examples use made-up ids and values. Responses leave out any single value the console did not send, so a real response may have fewer fields than shown.

This server has no write tools, no events, no event stream and no support-bundle tool. It has one MCP resource, the [plan image](#the-plan-image-resource).

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

The image metadata of one plan (file name, content type, pixel size, scale, image scale and offset, unit) and, when the image is a PNG, the `resource_uri` it is read from. With `include_image` set, it also returns the image as base64 in `image_base64`.

| Argument | Type | Default |
|---|---|---|
| `plan_id` | string, required | |
| `include_image` | boolean | `false` |

```json
{"success": true, "data": {
  "filename": "00000000-0000-0000-0000-000000000000.png", "content_type": "image/png",
  "width_px": 2000.0, "height_px": 1400.0, "scale_per_unit": 50.0, "image_scale": 1.0, "image_offset": [0.0, 0.0],
  "unit": "metric", "resource_uri": "innerspace://plans/plan-0001/image"
}}
```

The image is capped at 8,000,000 bytes. A larger image, or a response that is not an image of the type the plan's address promises (checked by content type and file header), is refused with fixed text rather than returned. Only the plan's own image address is ever requested, and only when it matches the console's asset address pattern and the plan's map in the project; no file name comes from the caller. `include_image` works on MCP only: [`unifi-api-server`](../../api/README.md#innerspace-console-product) rejects it and never returns image bytes.

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

## Coordinates and the plan image

Positions use the plan frame of the documented InnerSpace API: distance from the plan's top-left corner, `x` to the right and `y` downward, in the project's unit (or the `unit` you passed). The frame lines up with the plan image only when the plan's `image_scale` is `1` and its `image_offset` is `(0, 0)`. Both come with each plan, from `innerspace_list_floor_plans`, `innerspace_get_project` and `innerspace_get_plan_asset`.

To place a returned position (`x`, `y`) on the plan image, take W = `width_px`, H = `height_px`, s = `image_scale`, (ox, oy) = `image_offset` and k = `scale_per_unit` (plan units per metre, or per foot when the unit is imperial):

1. Back to the console's plan units: `plan_x = x*k - W/2` and `plan_y = H/2 - y*k`.
2. Then to image pixels: `px = (plan_x - ox)/s + W/2` and `py = H/2 - (plan_y - oy)/s`.

With `s = 1` and `(ox, oy) = (0, 0)` this reduces to `px = x*k` and `py = y*k`. When the console sent no image scale or offset, those fields are `null`: do not assume a value, and treat the position as not placeable on the image.

This is geometry only. It does not show that a device is where the plan says it is, and it says nothing about radio coverage.

## The plan image resource

`innerspace://plans/{plan_id}/image` is a resource template that returns a plan's image. It is fetched on demand, uses the same checks and size cap as `innerspace_get_plan_asset`, and does not support subscriptions. The template declares `image/png`: the plan's metadata is read first, and a plan whose image is another type is refused with fixed text before anything is downloaded; its image is available from `innerspace_get_plan_asset` with `include_image`. The resource is registered only beside `innerspace_get_plan_asset`: in eager mode, a category or tool filter that leaves that tool out leaves the resource out too. In setup mode no resource is registered.

## Meta-tools

Besides the nine domain tools the server registers six meta-tools, `innerspace_tool_index`, `innerspace_execute`, `innerspace_batch`, `innerspace_batch_status`, `innerspace_batch_cancel` and `innerspace_load_tools`, as the other servers do. They are not counted among the nine and are not all read-only; see [permissions.md](permissions.md#meta-tools-and-read-only-clients) and [MCP discovery and meta-tools](../../../docs/tool-index.md).

## Errors

Errors use fixed text built from the operation, the HTTP status and an error code: never a response body, the console address, a request path or an exception's text. An argument the server rejects is reported as `invalid arguments` and its value is never repeated. An argument of the wrong type (text for `limit`) is rejected before the tool runs by the MCP framework, whose error to the caller quotes the value; the server's log names only the argument. The cases you will see are in [troubleshooting.md](troubleshooting.md).
