# Python Examples - UniFi Network MCP

Practical examples demonstrating how to use the UniFi Network MCP server programmatically from Python.

## Prerequisites

```bash
pip install mcp
```

## Examples

### 1. Query Tool Index

**File:** `query_tool_index.py`

Demonstrates how to discover available tools and their schemas programmatically.

```bash
python examples/python/query_tool_index.py
```

**What it shows:**
- Connecting to the MCP server
- Querying the tool index
- Organizing tools by category
- Inspecting tool schemas

**Use cases:**
- Building dynamic UIs
- Auto-generating documentation
- Creating SDK wrappers
- IDE autocomplete integration

---

### 2. Async Jobs

**File:** `use_async_jobs.py`

Demonstrates how to start background jobs and monitor their progress.

```bash
python examples/python/use_async_jobs.py
```

**What it shows:**
- Single tool execution with `unifi_execute`
- Parallel batch operations with `unifi_batch`
- Polling batch status with `unifi_batch_status`
- Handling completion and errors

**Use cases:**
- Bulk operations across multiple devices
- Parallel data collection
- Long-running tasks (upgrades, exports)
- Network-wide configuration changes

---

### 3. Programmatic Client

**File:** `programmatic_client.py`

Demonstrates building a custom Python client class for UniFi operations.

```bash
python examples/python/programmatic_client.py
```

**What it shows:**
- Creating a reusable client class
- Wrapping common operations in methods
- Processing data in Python (filtering, sorting, aggregating)
- Building workflows that combine multiple operations

**Use cases:**
- Network monitoring scripts
- Automated network management
- Custom dashboards
- Integration with other systems

---

## Key Benefits of Programmatic Access

### Token Efficiency

Instead of sending full datasets through an LLM:

```python
# ❌ Inefficient: Send all clients to LLM
clients = await session.call_tool("unifi_list_clients", {})
# LLM processes 10,000 tokens of client data

# ✅ Efficient: Process in code, send summary
clients = await client.list_clients()
wireless = [c for c in clients if c.get("is_wireless")]
top_5 = sorted(wireless, key=lambda c: c["tx_bytes"])[:5]
# LLM processes 200 tokens of summary
```

### Complex Workflows

Chain operations without LLM involvement:

```python
# Get devices, filter offline, restart them
devices = await client.list_devices()
offline = [d for d in devices if not d.get("state") == 1]

for device in offline:
    job_id = await client.start_async_job("unifi_reboot_device", {"mac_address": device["mac"], "confirm": True})
    print(f"Rebooting {device['name']}: {job_id}")
```

### Data Processing

Transform data into custom formats:

```python
# Generate CSV export
clients = await client.list_clients()
with open("clients.csv", "w") as f:
    f.write("Name,IP,MAC,Traffic\\n")
    for c in clients:
        f.write(f"{c['name']},{c['ip']},{c['mac']},{c['tx_bytes']}\\n")
```

---

## Environment Variables

All examples require these environment variables:

```bash
export UNIFI_HOST="192.168.1.1"
export UNIFI_USERNAME="admin"
export UNIFI_PASSWORD="yourpassword"
export UNIFI_PORT="443"              # Optional
export UNIFI_SITE="default"          # Optional
export UNIFI_VERIFY_SSL="false"      # Optional
```

Or use a `.env` file in the project root.

---

## Next Steps

1. **Modify examples** - Adapt to your specific needs
2. **Build workflows** - Combine multiple operations
3. **Create dashboards** - Visualize network data
4. **Automate tasks** - Schedule regular operations

---

## Integration Examples

### With Grafana

```python
# Export metrics to Grafana/Prometheus
async with UniFiMCPClient() as client:
    stats = await client.get_network_stats()
    # Push to Prometheus pushgateway
```

### With Home Assistant

```python
# Create Home Assistant sensor
async with UniFiMCPClient() as client:
    devices = await client.list_devices()
    online_count = len([d for d in devices if d.get("state") == 1])
    # Update HA sensor
```

### With Jupyter Notebooks

```python
# Data analysis in Jupyter
import pandas as pd

async with UniFiMCPClient() as client:
    clients = await client.list_clients()
    df = pd.DataFrame(clients)
    df.plot(x="name", y="tx_bytes", kind="bar")
```

---

## See Also

- [Main README](../../README.md) - Server setup and configuration
- [Tool Catalog](../../README.md#-tool-catalog) - All available tools
- [Claude Desktop Guide](../CLAUDE_DESKTOP.md) - Using with Claude Desktop
