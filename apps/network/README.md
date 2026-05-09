<!-- mcp-name: io.github.sirkirby/unifi-network-mcp -->
# UniFi Network MCP Server

<p align="center">
  <img src="../../assets/hero-network.svg" alt="UniFi Network MCP Server" width="720">
</p>

MCP server exposing 161 UniFi Network Controller tools for LLMs, agents, and automation platforms. Query clients, devices, firewall rules, VLANs, VPNs, stats, and more — with safe-by-default permissions and preview-before-confirm for all mutations.

## Install

### Claude Code (recommended)

The plugin installs the MCP server, an agent skill for tool discovery, and a guided setup command:

```
/plugin marketplace add sirkirby/unifi-mcp
/plugin install unifi-network@unifi-plugins
```

Then run the interactive setup to configure your controller connection:

```
/unifi-network:setup
```

This walks you through entering your controller host, credentials, and permission preferences — then writes everything to `.claude/settings.json` so it persists across sessions. Restart Claude Code after setup to connect.

### PyPI / Docker

```bash
# PyPI
uvx unifi-network-mcp@latest
# or: pip install unifi-network-mcp

# Docker
docker pull ghcr.io/sirkirby/unifi-network-mcp:latest

# From source
git clone https://github.com/sirkirby/unifi-mcp.git
cd unifi-mcp && uv sync
```

## Usage Examples

Once connected, just ask your AI agent in natural language:

> "Show me all clients on the Guest VLAN with their signal strength and data usage"

> "Create a firewall rule that blocks IoT devices from reaching the internet between midnight and 6 AM"

> "Which access points have the most client disconnections this week?"

> "Audit my firewall policies — are there any redundant or conflicting rules?"

> "Rename the device at 192.168.1.45 to 'Living Room TV' and show me its traffic stats"

> "What changed on my network in the last 24 hours? Show me new clients and config changes."

All mutations (firewall rules, device changes, client blocking) use a **preview-then-confirm** flow — you see exactly what will change before anything is applied.

## Configure

Set these environment variables (or create a `.env` file). If you used `/unifi-network:setup`, this is already done.

```bash
# Server-specific variables (recommended)
UNIFI_NETWORK_HOST=192.168.1.1      # Controller IP or hostname
UNIFI_NETWORK_USERNAME=admin         # Local admin username
UNIFI_NETWORK_PASSWORD=your-password # Admin password
# Optional:
# UNIFI_NETWORK_API_KEY=             # UniFi API key (experimental — read-only, subset of tools)
# UNIFI_NETWORK_PORT=443             # Controller HTTPS port
# UNIFI_NETWORK_SITE=default         # UniFi site name
# UNIFI_NETWORK_VERIFY_SSL=false     # SSL certificate verification
```

**Fallback:** Existing `UNIFI_*` variables (e.g., `UNIFI_HOST`) continue to work. The server checks for `UNIFI_NETWORK_*` first and falls back to `UNIFI_*` if the server-specific variable is not set. For single-controller setups, the shared variables are all you need.

## Run

```bash
# stdio transport (default — for Claude Desktop, LM Studio, etc.)
unifi-network-mcp

# Docker
docker run -i --rm \
  -e UNIFI_NETWORK_HOST=192.168.1.1 \
  -e UNIFI_NETWORK_USERNAME=admin \
  -e UNIFI_NETWORK_PASSWORD=secret \
  ghcr.io/sirkirby/unifi-network-mcp:latest
```

### Claude Desktop

Add to `claude_desktop_config.json`:

```jsonc
{
  "mcpServers": {
    "unifi": {
      "command": "uvx",
      "args": ["unifi-network-mcp"],
      "env": {
        "UNIFI_NETWORK_HOST": "192.168.1.1",
        "UNIFI_NETWORK_USERNAME": "admin",
        "UNIFI_NETWORK_PASSWORD": "your-password"
      }
    }
  }
}
```

## Agent Skills

When installed via Claude Code, the network plugin ships three agent skills that extend Claude with specialized workflows for network management.

### Network Health Check

**Trigger:** "check network health", "what's down", "run a health check", "network status"

Gathers a full diagnostic snapshot in a single `unifi_batch` call — system info, network health, device list, and active alarms — then produces a structured health report. Includes reference documents for device state codes, alarm types and severity levels, and health subsystem diagnostics (WAN → LAN → WLAN → VPN priority order).

### Firewall Manager

**Trigger:** "block traffic", "create firewall rule", "set up IoT isolation", "manage content filtering"

Natural-language firewall management with a safe preview-then-confirm workflow. Ships with:

- **Policy templates** for common scenarios (`references/policy-templates.yaml`):

  | Template | Description |
  |----------|-------------|
  | `iot-isolation` | Block IoT VLAN from reaching the main LAN |
  | `guest-lockdown` | Restrict guest network to internet-only |
  | `kids-content-filter` | Time-based social media and gaming block via DPI |
  | `block-bittorrent` | Block P2P/BitTorrent traffic via DPI |
  | `work-vpn-split-tunnel` | Allow corporate VPN while keeping local LAN accessible |
  | `camera-isolation` | Lock IP cameras to NVR-only communication |

- **Snapshot/diff workflow** — Claude saves a timestamped JSON snapshot of all policies, zones, and groups before every mutation, then diffs the after-state against it so unintended changes are caught immediately
- **Reference docs** for firewall schema, DPI categories, and full template parameter lists

### Firewall Auditor

**Trigger:** "audit firewall", "review firewall rules", "check for security issues", "score my firewall"

Comprehensive automated audit across 16 security benchmarks in 4 categories, producing a 0–100 score with per-finding remediation guidance. Claude dispatches the MCP tool calls and evaluates each benchmark against `references/security-benchmarks.md`; a small CLI (`scripts/unifi-firewall-score`) turns the findings into the canonical, version-stable score so audit history stays comparable.

**Score thresholds:**

| Score | Rating | Meaning |
|-------|--------|---------|
| 80–100 | Healthy | Follows best practices with minor gaps |
| 60–79 | Needs Attention | Notable gaps; address on a planned schedule |
| 0–59 | Critical | Significant exposure requiring immediate remediation |

**Benchmark categories (4 × 25 points):**

- **Segmentation** (SEG-01–04) — IoT/Guest/Management VLAN isolation, explicit inter-VLAN policies
- **Egress Control** (EGR-01–03) — Outbound filtering for high-risk VLANs, DNS enforcement, threat intelligence blocks
- **Rule Hygiene** (HYG-01–05) — Conflicts, redundant/disabled rules, stale references, naming, shadowing
- **Topology** (TOP-01–04) — Offline devices, firmware currency, VLAN consistency across switch uplinks, orphaned port profiles

Each finding includes the benchmark ID, severity (critical/warning/informational), a plain-language explanation, and — when automatable — the exact MCP tool call to fix it. Audit history is tracked in `audit-history.json` so score trends are visible over time.

---

## Tool Improvements

### Device Classification (`unifi_list_devices`)

`unifi_list_devices` now returns a `device_category` field that correctly classifies every adopted device:

| Category | Devices |
|----------|---------|
| `ap` | Real access points (excludes USP Smart Power strips that connect via wireless mesh) |
| `switch` | Managed switches |
| `gateway` | Security gateways and Dream Machines |
| `pdu` | Power distribution units |
| `wan` | UCI cable internet devices |
| `unknown` | Unrecognized device types |

The `ap` category uses the controller's `is_access_point` boolean flag as the authoritative signal, not just the device type prefix. This means USP Smart Power strips — which appear as `uap`-typed devices — are correctly excluded from the AP category.

### Enriched Device Fields

Each device record now includes additional fields alongside the existing MAC, name, model, IP, firmware, uptime, and status:

| Field | Type | Description |
|-------|------|-------------|
| `device_category` | string | Semantic category: `ap`, `switch`, `gateway`, `pdu`, `wan`, `unknown` |
| `upgradable` | bool | Whether a firmware upgrade is available |
| `connection_network` | string | Name of the VLAN the device's management interface is on |
| `uplink` | object | Topology info: uplink type, speed, parent device name, and port |
| `load_avg_1` | float | 1-minute load average (from device system stats) |
| `mem_pct` | float | Memory utilization percentage (0–100) |
| `model_eol` | bool | Whether the device model has reached end-of-life |

---

## Documentation

- [Configuration](docs/configuration.md) — Full env var reference, YAML config, controller type detection
- [Permissions](docs/permissions.md) — Permission system, category defaults, how to enable high-risk tools
- [Tool Catalog](docs/tools.md) — All 166 tools organized by category
- [Transports](docs/transports.md) — stdio, Streamable HTTP, and SSE setup
- [Troubleshooting](docs/troubleshooting.md) — Connection issues, SSL, missing tools

## Development

```bash
cd apps/network
make test         # Run tests
make lint         # Lint
make format       # Format
make manifest     # Regenerate tools_manifest.json
make pre-commit   # All of the above
```

See the root [CONTRIBUTING.md](../../CONTRIBUTING.md) for the full monorepo workflow.

## License

[MIT](../../LICENSE)
