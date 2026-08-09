# UniFi Network MCP Examples

This directory contains practical examples demonstrating how to use the UniFi Network MCP server's code-execution features.

## What's Here

### Python Examples (`python/`)

Practical, working examples showing how to:

- **Query the tool index** - Discover available tools programmatically
- **Use async jobs** - Start and monitor long-running operations
- **Build custom clients** - Create reusable Python clients for UniFi operations

**Why Python?**
- Works today with no compatibility issues
- Integrates with existing Python tooling
- Easy to adapt for your specific needs
- Perfect for automation scripts

See: [Python Examples README](python/README.md)

### Claude Desktop Guide (`CLAUDE_DESKTOP.md`)

Complete guide showing how Claude Desktop uses the tool index and async jobs features automatically:

- How Claude discovers and uses tools
- Code-based data processing for token efficiency
- Async job management in conversations
- Best practices and example prompts

See: [Claude Desktop Guide](CLAUDE_DESKTOP.md)

---

## Quick Start

### Python Examples

```bash
# Install dependencies
pip install mcp

# Set environment variables
export UNIFI_HOST="192.168.1.1"
export UNIFI_USERNAME="admin"
export UNIFI_PASSWORD="yourpassword"

# Run examples
python examples/python/query_tool_index.py
python examples/python/use_async_jobs.py
python examples/python/programmatic_client.py
```

### Claude Desktop

Just use the server with Claude Desktop - it automatically uses the tool index and async jobs features.

Example prompt:
```
Show me the top 10 wireless clients by traffic,
excluding guest networks
```

Claude will query the tool index, fetch clients, filter in code, and show results.

---

## Key Features

### 1. Tool Index API

Programmatically discover available tools:

```python
from mcp import ClientSession, stdio_client

result = await session.call_tool("unifi_tool_index", {})
# Returns: {"tools": [{"name": "...", "description": "..."}, ...], "categories": [...]}
# Pass {"include_schemas": True} for full parameter schemas
# Pass {"category": "clients"} or {"search": "firewall"} to filter
```

**Use cases:**
- Dynamic UI generation
- SDK/wrapper generation
- IDE autocomplete
- Documentation generation

### 2. Tool Execution

Execute discovered tools synchronously or in parallel batches:

```python
# Single execution (returns result directly)
result = await session.call_tool("unifi_execute", {"tool": "unifi_list_clients", "arguments": {"limit": 10}})

# Batch execution (parallel, returns job IDs)
batch = await session.call_tool(
    "unifi_batch",
    {
        "operations": [
            {"tool": "unifi_get_client_details", "arguments": {"mac": "..."}},
            {"tool": "unifi_get_device_details", "arguments": {"mac": "..."}},
        ]
    },
)

# Check batch status
status = await session.call_tool("unifi_batch_status", {"jobIds": [job["jobId"] for job in batch["jobs"]]})
```

**Use cases:**
- Bulk operations across multiple devices
- Parallel data collection
- Long-running tasks (upgrades, exports)
- Network-wide changes

### 3. Code-Based Processing

Process data in code instead of sending through LLM:

```python
# Fetch all clients
clients = await get_clients()

# Filter, sort, aggregate in code
wireless = [c for c in clients if c["is_wireless"]]
top_10 = sorted(wireless, key=lambda c: c["tx_bytes"])[:10]

# Send only the summary to LLM
```

**Benefits:**
- 98% token reduction
- Faster processing
- More complex transformations
- Lower costs

---

## Architecture

```
┌─────────────────────────────────────────┐
│     UniFi Network MCP Server            │
│  ┌──────────────┐  ┌──────────────┐    │
│  │ Tool Index   │  │  Async Jobs  │    │
│  │     API      │  │     API      │    │
│  └──────────────┘  └──────────────┘    │
└────────────┬────────────────────────────┘
             │
    ┌────────┴────────┐
    │                 │
┌───▼────────┐  ┌────▼──────────┐
│   Claude   │  │    Python     │
│  Desktop   │  │   Scripts     │
└────────────┘  └───────────────┘
(uses features    (direct API
 automatically)    access)
```

---

## What Happened to TypeScript?

**Short version:** Removed due to Node.js compatibility issues and limited practical value.

**Long version:**

The original plan included TypeScript examples with `isolated-vm` for sandboxed code execution. However:

1. **Compatibility issues**: Node.js v25.x broke `isolated-vm` compilation
2. **Unnecessary complexity**: Claude Desktop already has code execution built-in
3. **Limited audience**: Who's building their own code execution environment?
4. **Better alternatives**: Python examples are simpler, work today, and more useful

The **server features** (tool index, async jobs) work with ANY MCP client - you don't need our TypeScript examples to use them.

---

## See Also

- [Main README](../README.md) - Server setup and configuration
- [Tool Catalog](../README.md#-tool-catalog) - All available tools
- [Python Examples](python/README.md) - Detailed Python usage
- [Claude Desktop Guide](CLAUDE_DESKTOP.md) - Using with Claude Desktop
