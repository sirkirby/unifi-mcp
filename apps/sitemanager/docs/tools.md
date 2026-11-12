# Tools — Site Manager Server

Nine read-only tools over Ubiquiti's [Site Manager API](https://developer.ui.com/site-manager-api/). Every tool returns `{"success": true, "data": ...}` or `{"success": false, "error": "..."}`.

## IDs

Host, site and device ids returned by these tools belong to the Site Manager tool family. They are not the ids the Network, Protect or Access servers use, and there is no translation between them.

## Hosts

| Tool | Description |
|---|---|
| `sitemanager_list_hosts` | Consoles and self-hosted servers on the account: connection state, OS version, hardware model, installed applications. Paged. |
| `sitemanager_get_host` | One host by id. `include_reported_state` adds the host's full reported state (large). |

The account holder's name, email and role are never returned. The full reported state leaves out account identifiers, device location and image metadata.

## Sites

| Tool | Description |
|---|---|
| `sitemanager_list_sites` | Sites across every host, with device and client counts, ISP details and WAN health. Paged. |

## Devices

| Tool | Description |
|---|---|
| `sitemanager_list_devices` | Devices grouped by the host that manages them: model, status, firmware version, update availability. Paged by host. Filter with `host_ids` or `updated_since`. |

## ISP metrics

| Tool | Description |
|---|---|
| `sitemanager_get_isp_metrics` | WAN latency, speed, uptime and packet loss for every site. |
| `sitemanager_query_isp_metrics` | The same for named sites, each optionally with its own time range. |

- `metric_type` is `5m` (kept for 24 hours) or `1h` (kept for 30 days).
- For the every-site tool, give `duration` (`24h` for `5m`; `7d` or `30d` for `1h`) or `begin_timestamp` with `end_timestamp`, not both.
- Each site returns a summary over the whole window plus its most recent `period_limit` periods (default 12, up to 720). `period_limit: 0` returns the summary alone.
- The query tool sets `partial` when some requested sites were left out. A site with no metrics returns no series.

## SD-WAN

| Tool | Description |
|---|---|
| `sitemanager_list_sdwan_configs` | SD-WAN configurations on the account. An account with none returns an empty list. |
| `sitemanager_get_sdwan_config` | One configuration with its settings, hubs and spokes. |
| `sitemanager_get_sdwan_config_status` | Deployment status: generation status, errors, warnings, per-hub and per-spoke state. |

## Paging

Paged tools take `page_size` (1-500) and `cursor`, and return `next_cursor`. Pass `next_cursor` back as `cursor` for the next page. A page can hold fewer entries than `page_size`, even none, while `next_cursor` is still set: keep paging until it is absent. The tools never fetch every page on their own.

## Meta tools

`sitemanager_tool_index`, `sitemanager_execute`, `sitemanager_batch`, `sitemanager_batch_status` and, in lazy mode, `sitemanager_load_tools`. In the default lazy mode all nine tools are also listed directly, so a client that allows only read-only tools can call them without `sitemanager_execute`.
