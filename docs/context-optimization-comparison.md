# Context Optimization Comparison

## Visual Comparison: Eager vs Meta-Only Mode

### Scenario: User asks "Show me my wireless clients"

---

## EAGER MODE (Default - All Tools Loaded)

```
┌─────────────────────────────────────────────────────────────┐
│ Claude Desktop Connects to MCP Server                       │
└─────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ MCP Server: list_tools()                                    │
│                                                              │
│ Returns 67 tools:                                            │
│ ├─ unifi_tool_index                                          │
│ ├─ unifi_execute                                             │
│ ├─ unifi_batch / unifi_batch_status                          │
│ ├─ unifi_list_clients                                        │
│ ├─ unifi_get_client_details                                  │
│ ├─ unifi_list_devices                                        │
│ ├─ unifi_get_device_details                                  │
│ ├─ unifi_reboot_device                                       │
│ ├─ unifi_list_networks                                       │
│ └─ ... 58 more tools                                         │
│                                                              │
│ 📊 Context: ~5,000 tokens                                    │
└─────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ Claude's Context Window                                      │
│                                                              │
│ ┌───────────────────────────────────────────┐               │
│ │ System Prompt              │ ~1,000 tokens │               │
│ ├───────────────────────────────────────────┤               │
│ │ Tool Schemas (67 tools)    │ ~5,000 tokens │ ◄── HEAVY!   │
│ ├───────────────────────────────────────────┤               │
│ │ Conversation History       │ ~2,000 tokens │               │
│ ├───────────────────────────────────────────┤               │
│ │ Available for Response     │ ~92,000 tokens│               │
│ └───────────────────────────────────────────┘               │
│                                                              │
│ Total Context Used: ~8,000 tokens                            │
└─────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ User: "Show me my wireless clients"                         │
└─────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ Claude: Calls unifi_list_clients                            │
│ (Already has schema in context)                             │
└─────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ Result: List of clients                                      │
│ ✅ Total Tokens Used: ~8,000                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## META_ONLY MODE (Optimized - Lazy Tool Loading)

```
┌─────────────────────────────────────────────────────────────┐
│ Claude Desktop Connects to MCP Server                       │
│ (with UNIFI_TOOL_REGISTRATION_MODE=meta_only)               │
└─────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ MCP Server: list_tools()                                    │
│                                                              │
│ Returns 4 meta-tools ONLY:                                   │
│ ├─ 🔍 unifi_tool_index                                       │
│ ├─ ⚡ unifi_execute                                          │
│ ├─ 📦 unifi_batch                                            │
│ └─ 📊 unifi_batch_status                                     │
│                                                              │
│ 📊 Context: ~200 tokens (96% less!)                          │
└─────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ Claude's Context Window                                      │
│                                                              │
│ ┌───────────────────────────────────────────┐               │
│ │ System Prompt              │ ~1,000 tokens │               │
│ ├───────────────────────────────────────────┤               │
│ │ Tool Schemas (3 tools)     │   ~200 tokens │ ◄── LIGHT!   │
│ ├───────────────────────────────────────────┤               │
│ │ Conversation History       │ ~2,000 tokens │               │
│ ├───────────────────────────────────────────┤               │
│ │ Available for Response     │ ~96,800 tokens│               │
│ └───────────────────────────────────────────┘               │
│                                                              │
│ Total Context Used: ~3,200 tokens (60% less!)                │
└─────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ User: "Show me my wireless clients"                         │
└─────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ Claude: Hmm, I need to find client-related tools...         │
│ Calls unifi_tool_index to discover available tools          │
└─────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ Tool Index Response:                                         │
│ {                                                            │
│   "tools": [                                                 │
│     {"name": "unifi_list_clients", "description": "...", ... },│
│     {"name": "unifi_get_client_details", ...},              │
│     ... 64 more tools                                        │
│   ]                                                          │
│ }                                                            │
│                                                              │
│ 📊 ~300 tokens (only loaded when needed)                     │
└─────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ Claude: Perfect! I found unifi_list_clients                 │
│ Calls unifi_list_clients                                    │
└─────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ Result: List of clients                                      │
│ ✅ Total Tokens Used: ~3,500 (56% less!)                     │
└─────────────────────────────────────────────────────────────┘
```

---

## Token Usage Breakdown

| Component | Eager Mode | Meta-Only Mode | Savings |
|-----------|------------|----------------|---------|
| System Prompt | 1,000 | 1,000 | 0% |
| Tool Schemas | **5,000** | **200** | **96%** ⭐ |
| Conversation | 2,000 | 2,000 | 0% |
| Tool Index Call | 0 | 300 | -300 |
| **Initial Total** | **8,000** | **3,200** | **60%** |
| **After User Query** | **8,000** | **3,500** | **56%** |

---

## Multi-Turn Conversation Example

### Scenario: User has a 10-message conversation

```
┌──────────────────────────────────────────────────────────────┐
│ EAGER MODE                                                   │
├──────────────────────────────────────────────────────────────┤
│ Turn 1: "Show clients"                                       │
│   Context: 5,000 (tools) + 1,000 (system) = 6,000           │
│                                                              │
│ Turn 2: "Which devices are offline?"                        │
│   Context: 5,000 (tools) + 2,000 (history) = 7,000          │
│                                                              │
│ Turn 3: "Reboot the offline ones"                           │
│   Context: 5,000 (tools) + 3,000 (history) = 8,000          │
│                                                              │
│ Turn 10: "Show network stats"                               │
│   Context: 5,000 (tools) + 10,000 (history) = 15,000        │
│                                                              │
│ ⚠️  Tool schemas consume 33-50% of every message's context! │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ META_ONLY MODE                                               │
├──────────────────────────────────────────────────────────────┤
│ Turn 1: "Show clients"                                       │
│   Context: 200 (tools) + 300 (index) + 1,000 (system) = 1,500│
│                                                              │
│ Turn 2: "Which devices are offline?"                        │
│   Context: 200 (tools) + 2,000 (history) = 2,200            │
│   (tool_index already in history, reused)                   │
│                                                              │
│ Turn 3: "Reboot the offline ones"                           │
│   Context: 200 (tools) + 3,000 (history) = 3,200            │
│                                                              │
│ Turn 10: "Show network stats"                               │
│   Context: 200 (tools) + 10,000 (history) = 10,200          │
│                                                              │
│ ✅ Tool schemas consume only 2% of each message's context!   │
│ ✅ 32% total savings over 10 turns!                          │
└──────────────────────────────────────────────────────────────┘
```

---

## When Each Mode Makes Sense

### Use EAGER Mode When:
- 🔧 **Interactive testing** (dev console)
- 📝 **Writing documentation** (need to see all tools)
- 🤖 **Building automation** (know exactly which tools to use)
- 🐛 **Debugging** (want full visibility)

### Use META_ONLY Mode When:
- 💬 **Conversational AI** (Claude Desktop, chatbots)
- 🌐 **Web interfaces** (token costs matter)
- 📱 **Mobile apps** (limited context windows)
- 🎯 **Targeted workflows** (users typically need 1-3 tools)
- 💰 **Cost optimization** (paying per token)

---

## Real-World Impact

### Example: Customer Support Bot

**Scenario:** 1,000 conversations per day, average 5 messages each

**Eager Mode:**
- 5,000 tokens/conversation × 1,000 = 5,000,000 tokens/day
- At $0.003/1K tokens = **$15/day** = **$450/month**

**Meta-Only Mode:**
- 2,000 tokens/conversation × 1,000 = 2,000,000 tokens/day
- At $0.003/1K tokens = **$6/day** = **$180/month**

**Savings: $270/month (60%)**

---

## The Magic of On-Demand Discovery

The key insight is that **most conversations only use a small subset of tools**, but traditional MCP servers load ALL tools into context "just in case."

With `meta_only` mode:
1. Start lean (3 tools)
2. Discover on-demand (call tool_index when needed)
3. Use once (tool schema stays in conversation history)
4. Reuse naturally (if same tool needed again)

It's like having a library catalog instead of carrying all the books!

---

## Future: True Lazy Loading

In the future, we could implement:

```python
# Hypothetical on-demand loading
if UNIFI_TOOL_REGISTRATION_MODE == "lazy":

    @server.tool_resolver
    async def load_tool_on_demand(tool_name: str):
        """Load tool only when first called."""
        if tool_name.startswith("unifi_"):
            module = import_tool_module(tool_name)
            return module.get_tool()
        return None
```

This would enable:
- ✨ Zero upfront tool loading
- ✨ Load only what's actually called
- ✨ Ultimate token efficiency

**Requires:** MCP SDK support for dynamic tool registration
**Status:** Future enhancement, tracked in roadmap

---

## Conclusion

**Meta-only mode** provides the best of both worlds:
- ✅ All tools remain accessible (via tool_index)
- ✅ Massive token savings (96% reduction)
- ✅ Faster responses (smaller context)
- ✅ Better user experience (more room for conversation)
- ✅ Lower costs (fewer tokens = less money)

It's a **win-win-win** for users, developers, and the planet (less compute = less energy)! 🌍
