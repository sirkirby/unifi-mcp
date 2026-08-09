# Using UniFi Network MCP with Claude Desktop

Claude Desktop has built-in code execution capabilities that work seamlessly with the UniFi Network MCP server's tool index and async jobs features.

## How It Works

### 1. Tool Discovery

Claude Desktop automatically uses the tool index:

```
You: "What UniFi tools are available?"
```

Claude internally calls `unifi_tool_index` and presents a categorized list.

### 2. Code-Based Data Processing

Claude can write and execute code to process UniFi data:

```
You: "Show me the top 10 wireless clients by traffic"
```

Claude's workflow:
1. Calls `unifi_list_clients` to get all clients
2. Writes Python code to filter wireless clients
3. Sorts by traffic and takes top 10
4. Presents formatted results

**Token savings:** Only the top 10 results are in Claude's context, not all 500+ clients.

### 3. Async Operations

Claude can manage long-running operations:

```
You: "Upgrade the firmware on all my access points"
```

Claude's workflow:
1. Discovers tools with `unifi_tool_index`
2. Lists devices with `unifi_execute` → `unifi_list_devices`
3. Filters for access points
4. Starts batch upgrade with `unifi_batch`
5. Polls status with `unifi_batch_status`
6. Reports progress and results

---

## Example Conversations

### Network Analysis

```
You: "Analyze my network traffic and tell me which clients are using
      the most bandwidth. Focus on wireless clients only."
```

What Claude does:
```python
# Claude writes and executes this internally
clients = unifi_list_clients()
wireless = [c for c in clients if c.get("is_wireless")]
sorted_by_traffic = sorted(wireless, key=lambda c: c["tx_bytes"] + c["rx_bytes"], reverse=True)
top_10 = sorted_by_traffic[:10]
```

Result: Claude shows you a formatted table of the top 10 clients, with human-readable traffic amounts.

---

### Device Management

```
You: "Find all offline devices and tell me when they were last seen"
```

What Claude does:
```python
# Claude writes and executes this internally
devices = unifi_list_devices()
offline = [d for d in devices if d.get("state") != 1]

results = []
for device in offline:
    last_seen = device.get("last_seen")
    results.append({"name": device["name"], "model": device["model"], "last_seen": format_timestamp(last_seen)})
```

Result: Clean list of offline devices with formatted timestamps.

---

### Bulk Operations

```
You: "Block all clients that haven't been active in 30 days,
      but show me the list first for confirmation"
```

What Claude does:
1. Gets all clients
2. Filters by last activity date (in code)
3. Shows you the list
4. Waits for your confirmation
5. Runs async jobs to block each client
6. Monitors progress and reports results

**Note:** Claude will NEVER execute mutations without the `confirm: true` parameter, and will always ask you first.

---

## Best Practices

### 1. Be Specific About Data Processing

❌ Vague:
```
"Show me clients"
```

✅ Specific:
```
"Show me wireless clients sorted by download traffic,
 excluding guest networks, top 20 only"
```

Claude can filter, sort, and limit the data in code before showing you results.

### 2. Use Async Jobs for Long Operations

❌ Don't:
```
"Reboot all 50 access points" (synchronously)
```

✅ Do:
```
"Start async jobs to reboot all access points and monitor progress"
```

Claude will use `unifi_batch` and poll with `unifi_batch_status`.

### 3. Leverage Data Aggregation

❌ Inefficient:
```
"What's the total bandwidth usage?"
(gets all clients, sends to LLM to sum)
```

✅ Efficient:
```
"Calculate total bandwidth across all clients"
```

Claude sums in code, sends only the result.

---

## Tool Index Usage

### Discovering Tools

```
You: "List all firewall-related tools"
```

Claude queries the tool index and filters by name/description.

### Schema Inspection

```
You: "Show me what parameters the unifi_create_firewall_policy tool accepts"
```

Claude looks up the tool schema from the index.

### Dynamic Capabilities

```
You: "What can you help me do with my UniFi network?"
```

Claude uses the tool index to generate a capabilities summary.

---

## Tool Execution

### Single Operations

```
You: "List my network clients"
```

Claude:
```python
result = unifi_execute(tool="unifi_list_clients", arguments={})
# Returns: result directly
```

### Batch Operations

```
You: "Get details for multiple devices at once"
```

Claude:
```python
batch = unifi_batch(
    operations=[
        {"tool": "unifi_get_device_details", "arguments": {"mac": "AA:BB:CC:DD:EE:FF"}},
        {"tool": "unifi_get_device_details", "arguments": {"mac": "11:22:33:44:55:66"}},
    ]
)
# Returns: job IDs for each operation
```

### Monitoring Batch Progress

```
You: "Check the status of my batch jobs"
```

Claude:
```python
status = unifi_batch_status(jobIds=["abc123", "def456"])
# Shows: status of each job (running, done, error)
```

### Parallel Upgrades

```
You: "Upgrade all access points, show me progress every 30 seconds"
```

Claude:
1. Discovers tools with `unifi_tool_index`
2. Gets device list via `unifi_execute`
3. Starts batch upgrade with `unifi_batch`
4. Polls status with `unifi_batch_status`
5. Reports completion/failures

---

## Security Notes

### Mutations Require Confirmation

All state-changing operations require `confirm: true`:

```
You: "Block client AA:BB:CC:DD:EE:FF"
```

Claude will:
1. Show you what it's about to do
2. Ask for confirmation
3. Only then call with `confirm: true`

### Read-Only by Default

Safe operations work immediately:

```
You: "Show me network statistics"
```

No confirmation needed - read-only operation.

### Permission System

Your config controls what Claude can access:

```yaml
# config.yaml
permissions:
  firewall_policies:
    list: true      # ✓ Claude can list
    create: false   # ✗ Claude cannot create
```

---

## Advanced Patterns

### Multi-Step Workflows

```
You: "Find devices with old firmware, create a report,
      and upgrade them if I approve"
```

Claude:
1. Lists devices
2. Filters by firmware version (in code)
3. Generates markdown report
4. Shows you the report
5. Asks for approval
6. Starts async upgrade jobs
7. Monitors progress

### Data Transformation

```
You: "Export my network topology as a diagram"
```

Claude:
1. Gets devices, networks, clients
2. Processes relationships in code
3. Generates Mermaid diagram syntax
4. Renders the diagram

### Scheduled Operations

```
You: "Check network health every hour and alert me of issues"
```

Claude can't schedule natively, but will:
1. Write a Python script that uses the MCP client
2. Include cron/schedule instructions
3. You run it outside Claude Desktop

---

## Tips & Tricks

1. **Ask for summaries**: "Summarize" instead of "Show all"
2. **Use filters**: "Only show..." to process data in code
3. **Request formats**: "as CSV", "as JSON", "as table"
4. **Batch with async**: "Start jobs for..." with progress tracking
5. **Verify first**: Ask Claude to show the plan before executing

---

## Limitations

- Claude Desktop executes code in its own sandbox (not your machine)
- Async jobs run on the server, not in Claude's execution environment
- Very large datasets may still hit token limits (but much higher than without code execution)

---

## See Also

- [Python Examples](python/) - Programmatic usage from Python
- [Main README](../README.md) - Server setup and configuration
- [Tool Catalog](../README.md#-tool-catalog) - All available tools
