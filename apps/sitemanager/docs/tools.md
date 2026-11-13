# Tools — Site Manager Server

Nine read-only tools over Ubiquiti's [Site Manager API](https://developer.ui.com/site-manager-api/). Every tool returns `{"success": true, "data": ...}` or `{"success": false, "error": "..."}`.

The examples below use made-up ids and addresses. Responses leave out any single value the API did not send, so a real response may have fewer fields than shown; lists and maps the API did not send come back empty. Timestamps are passed through as the API sent them: an RFC 3339 string or epoch milliseconds.

This server has no events, no event stream, no MCP resources and no support-bundle tool.

## IDs

Host, site and device ids returned by these tools belong to the Site Manager tool family. They are not the ids the Network, Protect or Access servers use, and there is no translation between them.

## Paging

Paged tools (`sitemanager_list_hosts`, `sitemanager_list_sites`, `sitemanager_list_devices`) take `page_size` (1-500) and `cursor`, and return `next_cursor`. Pass `next_cursor` back as `cursor` for the next page. A page can hold fewer entries than `page_size`, even none, while `next_cursor` is still set: keep paging until `next_cursor` is `null`. The tools never fetch every page on their own.

First page:

```json
{"page_size": 2}
```

```json
{
  "success": true,
  "data": {
    "hosts": [{"id": "host-0001", "...": "..."}, {"id": "host-0002", "...": "..."}],
    "count": 2,
    "next_cursor": "cursor-aaaa"
  }
}
```

Next page, which here is empty but not the last:

```json
{"page_size": 2, "cursor": "cursor-aaaa"}
```

```json
{"success": true, "data": {"hosts": [], "count": 0, "next_cursor": "cursor-bbbb"}}
```

Last page:

```json
{"success": true, "data": {"hosts": [{"id": "host-0003", "...": "..."}], "count": 1, "next_cursor": null}}
```

## Hosts

### `sitemanager_list_hosts`

Consoles and self-hosted servers on the account: connection state, OS version, hardware model, installed applications. Paged.

| Argument | Type | Default |
|---|---|---|
| `page_size` | integer, 1-500 | API default |
| `cursor` | string | first page |

```json
{}
```

```json
{
  "success": true,
  "data": {
    "hosts": [
      {
        "id": "host-0001",
        "hardware_id": "hw-0001",
        "type": "console",
        "ip_address": "203.0.113.10",
        "owner": true,
        "is_blocked": false,
        "registration_time": "2026-01-15T09:00:00Z",
        "last_connection_state_change": "2026-11-01T08:30:00Z",
        "name": "example-console",
        "hostname": "example-console",
        "state": "connected",
        "os_version": "4.1.0",
        "model": "Example Gateway",
        "shortname": "EXGW",
        "mac": "00:00:5e:00:53:01",
        "timezone": "UTC",
        "release_channel": "release",
        "applications": [
          {"name": "network", "version": "9.0.0", "is_installed": true, "is_running": true, "update_available": "9.0.1"}
        ]
      }
    ],
    "count": 1,
    "next_cursor": null
  }
}
```

### `sitemanager_get_host`

One host by id. `include_reported_state` adds the host's full reported state, which can be large.

| Argument | Type | Default |
|---|---|---|
| `host_id` | string, required | |
| `include_reported_state` | boolean | `false` |

```json
{"host_id": "host-0001", "include_reported_state": true}
```

```json
{
  "success": true,
  "data": {
    "host": {
      "id": "host-0001",
      "name": "example-console",
      "state": "connected",
      "os_version": "4.1.0",
      "applications": [],
      "reported_state": {"name": "example-console", "state": "connected", "version": "4.1.0", "...": "..."}
    }
  }
}
```

The account holder's name, email and role are never returned. The full reported state leaves out account identifiers, device location and image metadata. An unknown id returns `{"success": false, "error": "Failed to get host: Host 'host-9999' not found"}`.

## Sites

### `sitemanager_list_sites`

Sites across every host, with device and client counts, ISP details and WAN health. Paged; same arguments as `sitemanager_list_hosts`.

```json
{"page_size": 50}
```

```json
{
  "success": true,
  "data": {
    "sites": [
      {
        "site_id": "site-0001",
        "host_id": "host-0001",
        "name": "default",
        "description": "Example Branch",
        "timezone": "UTC",
        "gateway_mac": "00:00:5e:00:53:01",
        "permission": "admin",
        "is_owner": true,
        "counts": {"totalDevice": 12, "offlineDevice": 1, "wifiClient": 40, "wiredClient": 15},
        "gateway": {"shortname": "EXGW"},
        "isp": {"name": "Example ISP", "organization": "Example ISP"},
        "wan_uptime_percent": 99.9,
        "internet_issues": [{"index": 1234, "highLatency": true}]
      }
    ],
    "count": 1,
    "next_cursor": null
  }
}
```

`counts`, `gateway`, `isp` and `internet_issues` pass through the flat values the API sent; their keys vary with the console's version. At most 50 internet issues are returned per site. Use `host_id` and `site_id` from here for `sitemanager_query_isp_metrics`.

## Devices

### `sitemanager_list_devices`

Devices grouped by the host that manages them: model, status, firmware version, update availability. Paged by host: `page_size` counts hosts, not devices.

| Argument | Type | Default |
|---|---|---|
| `host_ids` | list of 1-100 host ids | every host |
| `updated_since` | RFC 3339 timestamp with a time-zone offset, such as `2026-11-01T00:00:00Z` | no filter |
| `page_size` | integer, 1-500 | API default |
| `cursor` | string | first page |

`updated_since` returns only hosts whose device list changed after that time.

```json
{"host_ids": ["host-0001"], "updated_since": "2026-11-01T00:00:00Z"}
```

```json
{
  "success": true,
  "data": {
    "hosts": [
      {
        "host_id": "host-0001",
        "host_name": "example-console",
        "updated_at": "2026-11-02T10:00:00Z",
        "devices": [
          {
            "id": "device-0001",
            "mac": "00:00:5e:00:53:02",
            "name": "example-switch",
            "model": "Example Switch 8",
            "ip": "192.0.2.20",
            "product_line": "network",
            "status": "online",
            "version": "7.1.0",
            "firmware_status": "updateAvailable",
            "update_available": "7.1.1",
            "is_console": false,
            "is_managed": true
          }
        ]
      }
    ],
    "host_count": 1,
    "device_count": 1,
    "next_cursor": null
  }
}
```

## ISP metrics

WAN latency, throughput, uptime and packet loss per site. There is no paging: the API returns the whole window at once, so each site comes back as a summary over the whole window plus only its most recent periods.

- `metric_type` is `5m` (kept for 24 hours) or `1h` (kept for 30 days). Default `1h`.
- `period_limit` is how many of the most recent periods to return per site, 0-720 (default 12). The summary always covers every period in the window. `periods_truncated` is `true` when older periods were left out.

### `sitemanager_get_isp_metrics`

Metrics for every site the account can see.

| Argument | Type | Default |
|---|---|---|
| `metric_type` | `5m` or `1h` | `1h` |
| `duration` | `24h` for `5m`; `7d` or `30d` for `1h` | the shortest for the interval |
| `begin_timestamp`, `end_timestamp` | RFC 3339, given together | none |
| `period_limit` | integer, 0-720 | `12` |

Give `duration` or the two timestamps, not both.

```json
{"metric_type": "1h", "duration": "7d", "period_limit": 2}
```

```json
{
  "success": true,
  "data": {
    "sites": [
      {
        "host_id": "host-0001",
        "site_id": "site-0001",
        "metric_type": "1h",
        "summary": {
          "period_count": 168,
          "first_time": "2026-11-05T00:00:00Z",
          "last_time": "2026-11-11T23:00:00Z",
          "avg_latency_ms": 14.2,
          "max_latency_ms": 85,
          "avg_packet_loss": 0.1,
          "avg_download_kbps": 240000.0,
          "avg_upload_kbps": 38000.0,
          "total_downtime": 120,
          "periods_with_downtime": 1
        },
        "periods": [
          {"time": "2026-11-11T22:00:00Z", "avg_latency_ms": 12, "max_latency_ms": 20, "packet_loss": 0, "download_kbps": 245000, "upload_kbps": 39000, "uptime": 100, "downtime": 0, "isp_name": "Example ISP", "isp_asn": "64500"},
          {"time": "2026-11-11T23:00:00Z", "avg_latency_ms": 13, "max_latency_ms": 22, "packet_loss": 0, "download_kbps": 241000, "upload_kbps": 38500, "uptime": 100, "downtime": 0, "isp_name": "Example ISP", "isp_asn": "64500"}
        ],
        "periods_truncated": true
      }
    ],
    "count": 1
  }
}
```

With `period_limit: 0` each site carries the summary alone:

```json
{"metric_type": "5m", "duration": "24h", "period_limit": 0}
```

```json
{
  "success": true,
  "data": {
    "sites": [
      {"host_id": "host-0001", "site_id": "site-0001", "metric_type": "5m", "summary": {"period_count": 288, "...": "..."}, "periods": [], "periods_truncated": true}
    ],
    "count": 1
  }
}
```

### `sitemanager_query_isp_metrics`

The same metrics for named sites, each optionally with its own time range.

| Argument | Type | Default |
|---|---|---|
| `sites` | list of 1-50 entries, required | |
| `metric_type` | `5m` or `1h` | `1h` |
| `period_limit` | integer, 0-720 | `12` |

Each entry of `sites` takes `host_id` and `site_id` (required) and may give `begin_timestamp` and `end_timestamp` as RFC 3339 strings. Any other key in an entry is refused, so a misspelled range field cannot fall back to the default window unnoticed.

```json
{
  "metric_type": "5m",
  "period_limit": 0,
  "sites": [
    {"host_id": "host-0001", "site_id": "site-0001"},
    {"host_id": "host-0002", "site_id": "site-0002", "begin_timestamp": "2026-11-11T00:00:00Z", "end_timestamp": "2026-11-11T12:00:00Z"}
  ]
}
```

```json
{
  "success": true,
  "data": {
    "sites": [
      {"host_id": "host-0001", "site_id": "site-0001", "metric_type": "5m", "summary": {"period_count": 288, "...": "..."}, "periods": [], "periods_truncated": true}
    ],
    "count": 1,
    "partial": true,
    "message": "..."
  }
}
```

`partial` is `true` when the API left out some requested sites, usually because the account cannot read them or the ids are wrong. `message` appears only when the API sent one. A site with no metrics returns no series and does not set `partial`.

## SD-WAN

Hub, spoke and status entries are passed through as the API sent them.

### `sitemanager_list_sdwan_configs`

SD-WAN configurations on the account. Takes no arguments.

```json
{}
```

```json
{
  "success": true,
  "data": {
    "configs": [{"id": "sdwan-0001", "name": "Example Mesh", "type": "hub-spoke"}],
    "count": 1
  }
}
```

An account with no SD-WAN configurations is not an error:

```json
{"success": true, "data": {"configs": [], "count": 0}}
```

### `sitemanager_get_sdwan_config`

One configuration with its settings, hubs and spokes.

| Argument | Type | Default |
|---|---|---|
| `config_id` | string, required | |

```json
{"config_id": "sdwan-0001"}
```

```json
{
  "success": true,
  "data": {
    "config": {
      "id": "sdwan-0001",
      "name": "Example Mesh",
      "type": "hub-spoke",
      "variant": "...",
      "settings": {"...": "..."},
      "hubs": [{"hostId": "host-0001", "siteId": "site-0001", "...": "..."}],
      "spokes": [{"hostId": "host-0002", "siteId": "site-0002", "...": "..."}]
    }
  }
}
```

### `sitemanager_get_sdwan_config_status`

Deployment status: generation status, errors, warnings, per-hub and per-spoke state.

| Argument | Type | Default |
|---|---|---|
| `config_id` | string, required | |

```json
{"config_id": "sdwan-0001"}
```

```json
{
  "success": true,
  "data": {
    "status": {
      "id": "sdwan-0001",
      "fingerprint": "fp-0001",
      "generate_status": "ok",
      "updated_at": "2026-11-11T12:00:00Z",
      "last_generated_at": "2026-11-11T11:59:00Z",
      "errors": [],
      "warnings": [],
      "hubs": [{"...": "..."}],
      "spokes": [{"...": "..."}]
    }
  }
}
```

An unknown id returns `{"success": false, "error": "Failed to get SD-WAN configuration status: SD-WAN configuration 'sdwan-9999' not found"}`.

## Meta tools

| Tool | Registered in | Purpose |
|---|---|---|
| `sitemanager_tool_index` | every mode | List tools; filter by `category`, `search` or `name`; `include_schemas` adds input schemas |
| `sitemanager_execute` | every mode | Run one tool by name |
| `sitemanager_batch` | every mode | Run several tools in the background |
| `sitemanager_batch_status` | every mode | Check background jobs by `jobId` or `jobIds` |
| `sitemanager_load_tools` | lazy mode | Register tools for direct calling |

In the default lazy mode all nine tools are also listed directly, so most clients never need the meta-tools. Call a tool by name when you can: `sitemanager_execute` and `sitemanager_batch` are not marked read-only, so a client may ask for approval before them or refuse them. See [permissions.md](permissions.md#meta-tools-and-read-only-clients).

Find the tools for one area, with their input schemas:

```json
{"category": "isp_metrics", "include_schemas": true}
```

Categories are `hosts`, `sites`, `devices`, `isp_metrics` and `sdwan`; every index response lists them in `categories`.

Run a tool through the dispatcher:

```json
{"tool": "sitemanager_list_sites", "arguments": {"page_size": 50}}
```

Run several at once with `sitemanager_batch`, then read the results with `sitemanager_batch_status`:

```json
{"operations": [
  {"tool": "sitemanager_list_hosts", "arguments": {}},
  {"tool": "sitemanager_list_sdwan_configs", "arguments": {}}
]}
```
