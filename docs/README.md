# Documentation

Complete documentation for the UniFi MCP ecosystem.

---

## 📚 Quick Links

- **[Main README](../README.md)** - Project overview and installation
- **[Quick Start](../QUICKSTART.md)** - Get started in 5 minutes
- **[Architecture](ARCHITECTURE.md)** - Monorepo layout and package responsibilities
- **[Worker Gateway](../apps/worker/)** - Cloudflare Worker gateway and npm CLI
- **[Relay Sidecar](../packages/unifi-mcp-relay/)** - Local sidecar for cloud relay mode
- **[Sponsor UniFi MCP](sponsor/)** - Support maintenance, AI costs, compatibility testing, and releases

---

## Lazy Tool Loading

Lazy mode is the default for MCP servers and keeps initial tool context small.

The server now supports three tool registration modes:

| Mode | Description | Tokens | Use Case |
|------|-------------|--------|----------|
| **lazy** (default) | Auto-loads tools on-demand | ~225 | Production LLMs |
| **meta_only** | Manual tool discovery | ~225 | Maximum control |
| **eager** | All tools immediately | ~5,000 | Dev console |

**Quick config:**
```bash
export UNIFI_TOOL_REGISTRATION_MODE=lazy  # default, recommended
```

---

## 📖 Documentation Overview

### Core Guides

#### [Context Optimization Comparison](context-optimization-comparison.md)
Visual guide comparing eager vs lazy vs meta-only modes:
- Side-by-side token usage diagrams
- Real-world cost calculations
- When to use each mode

**TLDR:** Lazy mode = 96% token savings + seamless UX = best of both worlds!

#### [Tool Index](tool-index.md)
Documentation for the `unifi_tool_index` meta-tool:
- How to query available tools
- Schema format
- Use cases (SDK generation, automation)

**TLDR:** Call `unifi_tool_index` to get a machine-readable list of all available tools.

#### [Permissions](permissions.md) 🔐 **SECURITY**
Complete guide to the permission system:
- How permissions work
- Default security settings
- Enabling/disabling tool categories
- Impact on tool availability

**TLDR:** High-risk tools (networks, devices, clients) are disabled by default. Enable in config.yaml as needed.

---

## 🎯 Common Tasks

### I want to...

**...get started quickly**
→ See [Quick Start Guide](../QUICKSTART.md)

**...configure the server**
→ See [Main README - Configuration](../README.md#configuration)

**...build automation scripts**
→ See [examples/python/](../examples/python/)

**...use with Claude Desktop**
→ See [examples/CLAUDE_DESKTOP.md](../examples/CLAUDE_DESKTOP.md)

---

## 🔧 Configuration Reference

### Environment Variables

```bash
# Tool registration mode
UNIFI_TOOL_REGISTRATION_MODE=lazy  # lazy (default), eager, meta_only

# UniFi controller connection
UNIFI_HOST=192.168.1.1
UNIFI_USERNAME=admin
UNIFI_PASSWORD=your-password
UNIFI_PORT=443
UNIFI_SITE=default

# Controller type detection
UNIFI_CONTROLLER_TYPE=auto  # auto (default), proxy, direct

# Server options
UNIFI_MCP_HTTP_ENABLED=false
UNIFI_MCP_DIAGNOSTICS=false
```

Full Network server defaults are in [config.yaml](../apps/network/src/unifi_network_mcp/config/config.yaml). Protect and Access keep their own defaults under `apps/protect/` and `apps/access/`.

### Worker and Relay

The cloud relay path has two packages:

- `apps/worker/`: the TypeScript Cloudflare Worker gateway and published `unifi-mcp-worker` npm CLI
- `packages/unifi-mcp-relay/`: the Python sidecar that connects local MCP servers to the Worker over WebSocket

Use `make sync` in a source checkout to install both the Python workspace and worker npm dependencies.

---

## 📊 Performance & Metrics

### Token Savings

| Mode | Initial Context | After Query | Savings |
|------|----------------|-------------|---------|
| eager | 5,000 tokens | 5,000 | 0% |
| meta_only | 225 tokens | 525 | 89% |
| **lazy** | **225 tokens** | **225** | **96%** ⭐ |

### Cost Savings (1,000 conversations/day)

- **Eager mode:** $450/month
- **Lazy mode:** $180/month
- **Savings:** $270/month (60%)

See [Context Optimization Comparison](context-optimization-comparison.md) for detailed analysis.

---

## 🤝 Contributing

See [CLAUDE.md](../CLAUDE.md) for project development guidelines.

---

## 📝 Document Index

### Root Documentation
- [README.md](../README.md) - Main project documentation
- [QUICKSTART.md](../QUICKSTART.md) - Quick start guide
- [CLAUDE.md](../CLAUDE.md) - Development guidelines

### Core Documentation (docs/)
- [context-optimization-comparison.md](context-optimization-comparison.md) - Mode comparison
- [tool-index.md](tool-index.md) - Tool index documentation
- [sponsor/](sponsor/) - Sponsorship landing page

---

## 🔗 External Resources

- **MCP Specification:** https://spec.modelcontextprotocol.io/
- **FastMCP Documentation:** https://gofastmcp.com/
- **UniFi Controller API:** https://ubntwiki.com/products/software/unifi-controller/api
- **GitHub Repository:** https://github.com/sirkirby/unifi-mcp
