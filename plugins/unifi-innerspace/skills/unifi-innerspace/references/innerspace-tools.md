# InnerSpace Server Tool Reference (24 domain tools, plus 6 meta-tools)

InnerSpace console tools, from the release the plugin pins. Reads return data;
every Mutate tool previews first and changes the console only with
`confirm=True`. These IDs are scoped to the InnerSpace tool family — do not
pass them to Network, Protect, Access or Site Manager tools.

## Meta-Tools

| Tool | Purpose |
|---|---|
| `innerspace_tool_index` | Discover names and schemas |
| `innerspace_execute` | Dispatch one domain tool |
| `innerspace_load_tools` | Load selected lazy tools |
| `innerspace_batch` | Dispatch a bounded group of calls |
| `innerspace_batch_status` | Check dispatched jobs |
| `innerspace_batch_cancel` | Cancel dispatched jobs that are still queued |

## Status

<!-- AUTO:tools:status -->
1 tools.

| Tool | Type | Description |
|------|------|-------------|
| `innerspace_get_status` | Read | Reports whether the InnerSpace application is installed and running on the UniFi OS console, with its installed version and any update av... |
<!-- /AUTO:tools:status -->

## Project

<!-- AUTO:tools:project -->
3 tools.

| Tool | Type | Description |
|------|------|-------------|
| `innerspace_get_project` | Read | Returns the InnerSpace project: its title, floor plans, wall types and attenuation-object (RF obstacle) types. |
| `innerspace_list_walls` | Read | Lists the walls of one floor plan in the plan's own coordinate frame, in the project's unit unless unit is given. |
| `innerspace_set_project_unit` | Mutate | Sets the unit the InnerSpace app displays lengths in: metric or imperial. |
<!-- /AUTO:tools:project -->

## Floor Plans

<!-- AUTO:tools:floor_plans -->
6 tools.

| Tool | Type | Description |
|------|------|-------------|
| `innerspace_get_plan_asset` | Read | Returns one floor plan's image metadata and the resource URI to read the image from. |
| `innerspace_list_floor_plans` | Read | Lists the floor plans of the InnerSpace project with their scale and image placement. |
| `innerspace_rename_floor_plan` | Mutate | Changes a floor plan's title. |
| `innerspace_reorder_floor_plans` | Mutate | Sets the order of the floor plans, which is how InnerSpace stacks the floors. |
| `innerspace_set_floor_attenuation` | Mutate | Sets the signal loss through one floor, which InnerSpace uses between stacked plans; null restores the app default. |
| `innerspace_set_plan_scale` | Mutate | Replaces a floor plan's scale line: a line between two points and its real length. |
<!-- /AUTO:tools:floor_plans -->

## Devices

<!-- AUTO:tools:devices -->
4 tools.

| Tool | Type | Description |
|------|------|-------------|
| `innerspace_list_access_points` | Read | Lists the access points in the InnerSpace project and where they are placed, in the project's unit unless unit is given. |
| `innerspace_list_inventory` | Read | Lists the devices the console has adopted that are not yet placed on a floor plan. |
| `innerspace_list_placed_devices` | Read | Lists the devices placed on one floor plan, in the project's unit unless unit is given. |
| `innerspace_list_switches` | Read | Lists the switches in the InnerSpace project and where they are placed, in the project's unit unless unit is given. |
<!-- /AUTO:tools:devices -->

## Walls

<!-- AUTO:tools:walls -->
3 tools.

| Tool | Type | Description |
|------|------|-------------|
| `innerspace_create_walls` | Mutate | Creates walls on one floor plan. |
| `innerspace_remove_walls` | Mutate | Removes walls from one floor plan, at most 50 per call. |
| `innerspace_update_walls` | Mutate | Moves walls or changes their material on one floor plan. |
<!-- /AUTO:tools:walls -->

## Wall Types

<!-- AUTO:tools:wall_types -->
2 tools.

| Tool | Type | Description |
|------|------|-------------|
| `innerspace_create_wall_type` | Mutate | Creates a project wall type (a custom material). |
| `innerspace_update_wall_type` | Mutate | Changes a project wall type. |
<!-- /AUTO:tools:wall_types -->

## Attenuation

<!-- AUTO:tools:attenuation -->
5 tools.

| Tool | Type | Description |
|------|------|-------------|
| `innerspace_create_attenuation_object_type` | Mutate | Creates a project attenuation-object type. |
| `innerspace_create_attenuation_objects` | Mutate | Creates attenuation objects (areas that weaken the signal, such as shelving or a car) on one floor plan. |
| `innerspace_remove_attenuation_objects` | Mutate | Removes attenuation objects from one floor plan, at most 50 per call; their ids are in innerspace_get_project with include_shapes. |
| `innerspace_update_attenuation_object_type` | Mutate | Changes a project attenuation-object type. |
| `innerspace_update_attenuation_objects` | Mutate | Moves attenuation objects or changes their kind on one floor plan. |
<!-- /AUTO:tools:attenuation -->
