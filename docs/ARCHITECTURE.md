# NovaBank Lab — Architecture

```
                 ┌───────────────────────────────────────────────┐
                 │                 Browser (chat UI)              │
                 │  web/static/index.html  (renders reply via     │
                 │  innerHTML -> XSS; sends client-chosen customer)│
                 └───────────────┬───────────────────────────────┘
                                 │ HTTP /api/chat
                 ┌───────────────▼───────────────┐
                 │        FastAPI  (web/app.py)   │
                 │  trusts client identity, /api/debug leaks state │
                 └───────────────┬───────────────┘
                                 │
                 ┌───────────────▼───────────────────────────────┐
                 │            Agent loop (agent/core.py)          │
                 │  1. RAG retrieve  2. LLM  3. MCP tool calls    │
                 │  persistent per-session memory (poisonable)    │
                 └───────┬───────────────────┬───────────────────┘
                         │                   │
         ┌───────────────▼──────┐   ┌────────▼───────────────────────┐
         │  RAG (rag/store.py)  │   │  LLM (agent/llm.py)             │
         │  TF-IDF, no tenant   │   │  OpenRouter  OR  offline mock   │
         │  isolation; poisoned │   └────────┬───────────────────────┘
         │  + cross-tenant docs │            │ OpenAI-format tool schema
         └──────────────────────┘            │ (from the live MCP server)
                                             │
                         ┌───────────────────▼───────────────────────┐
                         │   MCP client (agent/mcp_client.py)         │
                         │   stdio ── launches ──▶ subprocess         │
                         └───────────────────┬───────────────────────┘
                                             │ Model Context Protocol (stdio)
                         ┌───────────────────▼───────────────────────┐
                         │   MCP server (mcp_server/server.py)        │
                         │   FastMCP; poisoned tool description       │
                         │   wraps mcp_server/tools_impl.py           │
                         └───────────────────┬───────────────────────┘
                                             │ real side effects (synthetic)
             ┌───────────────┬───────────────┼───────────────┬───────────────┐
             ▼               ▼               ▼               ▼               ▼
      lab/novabank.db  lab/sandbox/   lab/internal_notes  lab/outbox.log  httpx(SSRF)
      (SQLite +SQLi)   (traversal)    (traversal target)  (exfil sink)   (+fake metadata)
```

## Why the MCP server is a real subprocess

`agent/mcp_client.py` launches `python -m mcp_server.server` over stdio and
speaks the Model Context Protocol to it — the same transport Claude Desktop
and the MCP Inspector use. Tool schemas (including the **poisoned description**
of `get_exchange_rate`) are discovered at runtime via `list_tools` and handed
to the LLM verbatim. So the lab demonstrates MCP attacks as they actually
occur: the server's advertised metadata is part of the attack surface, not
something the agent hard-codes.

You can also point any MCP client at the server directly (no agent, no web
app) — see the config snippet at the top of `mcp_server/server.py`.

## Two LLM backends, one interface

`agent/llm.py` exposes `complete(messages, tools) -> {content, tool_calls}`.
- **OpenRouterLLM** — real tool-calling model (recommended). Set
  `OPENROUTER_API_KEY`.
- **MockLLM** — deterministic, deliberately gullible. Maps the user's own
  keywords to tools, and separately obeys imperative `call <tool>` directives
  found in retrieved documents / tool descriptions / prior memory. This makes
  the injection chains reproduce offline, but it is a rough stand-in: a real
  model weighs salience and phrasing, so always validate findings against
  OpenRouter before reporting them as model behavior.

## State that persists

- `lab/novabank.db` — rewritten by `seed_data.py`; mutated by `transfer_funds`
  and `search_internal_db`.
- `lab/outbox.log` — append-only exfil evidence.
- In-memory `sessions` dict — conversation memory per `session_id`; cleared by
  `/api/reset` or process restart.
