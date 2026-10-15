---
s0ma_kind: "doc-guide"
name: "selfhost_walkthrough"
module: "tools"
format: "markdown"
intent: "How the s0ma authoring MCP server hosts itself: its tools, resources, and prompts are authored as s0ma modules, registered at bootstrap, served from the self-model registry — and the running server will tell you so."
schema_version: "3.0.0"
content_hash: "1:b3067b3502e5afa8c88271f3e1a72e075caad3cf01aec83d920786bbbded7d94"
---

# The server that describes itself

Every tool, resource, and prompt this MCP server exposes is authored as a declaration in a s0ma module, transpiled to Python, and registered as a component when the package imports. The FastMCP surface is then derived from that registry: a component carrying MCP metadata is served because it is registered, so the served surface and the self-model cannot drift apart.

Two surfaces let you watch it happen. The `nerve::describe_server_tool` (Answers 'what is this server and what can it do' from the live self-model: the registered component graph plus an LLM-ready text rendering) tool answers with the live component graph plus a text rendering an agent can read directly, and the `nerve::self_model_resource` (Serves this server's own live component graph as JSON — every tool, resource, prompt, and factory with kind, layer, intent, and dependencies, the same registry the served surface is derived from (FR-MCP-7)) resource serves the same graph as a JSON document.

```python
from s0ma_mcp import tools

described = tools.describe_server_tool()
assert described["ok"] is True
assert described["server"]["name"] == "s0ma-authoring"
print(f"self-model components: {described['component_count']}")
```

The assertion in the example is the whole point: the server you are talking to is the one describing itself, from the same registry its own build registered.
