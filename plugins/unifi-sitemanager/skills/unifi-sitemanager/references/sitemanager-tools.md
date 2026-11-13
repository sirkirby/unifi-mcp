# Site Manager Server Tool Reference (9 read-only domain tools, plus 5 meta-tools)

Read-only cloud account tools, pinned to `unifi-sitemanager-mcp==0.1.0`.
These IDs are scoped to the Site Manager tool family — do not pass them to
Network, Protect, or Access tools.

## Meta-Tools

| Tool | Purpose |
|---|---|
| `sitemanager_tool_index` | Discover names and schemas |
| `sitemanager_execute` | Dispatch one domain read |
| `sitemanager_load_tools` | Load selected lazy tools |
| `sitemanager_batch` | Dispatch a bounded group of reads |
| `sitemanager_batch_status` | Check dispatched jobs |

## Hosts

<!-- AUTO:tools:hosts -->
2 tools.

| Tool | Type | Description |
|------|------|-------------|
| `sitemanager_get_host` | Read | Returns one host by its Site Manager host id. |
| `sitemanager_list_hosts` | Read | Lists the UniFi consoles and self-hosted servers linked to the account behind the Site Manager API key, with connection state, OS version, hardware model and installed applications. |
<!-- /AUTO:tools:hosts -->

## Sites

<!-- AUTO:tools:sites -->
1 tools.

| Tool | Type | Description |
|------|------|-------------|
| `sitemanager_list_sites` | Read | Lists the sites on every host the account behind the Site Manager API key can see, with device and client counts, ISP details and WAN health. |
<!-- /AUTO:tools:sites -->

## Devices

<!-- AUTO:tools:devices -->
1 tools.

| Tool | Type | Description |
|------|------|-------------|
| `sitemanager_list_devices` | Read | Lists UniFi devices grouped by the host that manages them, with model, status, firmware version and whether an update is available. |
<!-- /AUTO:tools:devices -->

## ISP Metrics

<!-- AUTO:tools:isp_metrics -->
2 tools.

| Tool | Type | Description |
|------|------|-------------|
| `sitemanager_get_isp_metrics` | Read | Returns WAN performance for every site the account can see: latency, download and upload speed, uptime, downtime and packet loss. |
| `sitemanager_query_isp_metrics` | Read | Returns WAN performance for named sites, each optionally with its own time range. |
<!-- /AUTO:tools:isp_metrics -->

## SD-WAN

<!-- AUTO:tools:sdwan -->
3 tools.

| Tool | Type | Description |
|------|------|-------------|
| `sitemanager_get_sdwan_config` | Read | Returns one SD-WAN configuration with its settings, hubs and spokes. |
| `sitemanager_get_sdwan_config_status` | Read | Returns the deployment status of one SD-WAN configuration: generation status, errors and warnings, and per-hub and per-spoke state. |
| `sitemanager_list_sdwan_configs` | Read | Lists the SD-WAN configurations on the account behind the Site Manager API key. |
<!-- /AUTO:tools:sdwan -->

