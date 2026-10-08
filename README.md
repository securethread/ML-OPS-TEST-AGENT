# NovaBank — Vulnerable AI Agent Lab (Agent + MCP + RAG)

A deliberately **insecure** finance customer-support assistant, built as a
training target for AI-security testing. One bundle wires together:

- an **LLM agent** (via **OpenRouter**, with an offline mock fallback),
- a **real MCP server** (Model Context Protocol, stdio) exposing banking tools
  with genuine side effects,
- a **real RAG** pipeline over a banking knowledge base,
- a chat **web UI** + REST API,

and plants a broad set of **OWASP LLM Top 10**, **MCP (community) Top 10**, and
**RAG** vulnerabilities so testers can find and exploit them hands-on.

> ⚠️ **READ THIS FIRST.** This app is vulnerable *on purpose*. Everything it
> touches is **synthetic** — a seeded SQLite DB, a jailed `sandbox/` folder, a
> mock email outbox, a simulated cloud-metadata endpoint. There are **no real
> credentials, customers, money, or external systems**. All "secrets" are fake
> strings. Even so:
> - Run it **locally / in a disposable container**, bound to `127.0.0.1`.
> - **Never** expose it to an untrusted network or point its tools at anything
>   real.
> - The shell/RCE tool ships **disabled**; only enable it in a throwaway VM.
>
> For **authorized security education and testing only.**

---

## What's inside

| Layer | Path | Notes |
|---|---|---|
| Web UI + API | `web/` | chat UI (insecure `innerHTML` render), `/api/chat`, `/api/debug` |
| Agent loop | `agent/core.py` | RAG → LLM → MCP tools; persistent (poisonable) memory |
| LLM backends | `agent/llm.py` | OpenRouter real client + deterministic offline mock |
| MCP client | `agent/mcp_client.py` | launches the server over stdio, discovers tools |
| MCP server | `mcp_server/` | FastMCP; 11 vulnerable tools, one poisoned description |
| RAG | `rag/` | TF-IDF retriever (no tenant isolation) + poisoned corpus |
| Data seeder | `seed_data.py` | synthetic customers/accounts/txns + sandbox docs |
| Docs | `docs/` | **VULNERABILITIES.md**, **CHALLENGES.md**, **ARCHITECTURE.md** |

Full mapping of every vulnerability → code → exploit is in
**[docs/VULNERABILITIES.md](docs/VULNERABILITIES.md)**. Start attacking with
**[docs/CHALLENGES.md](docs/CHALLENGES.md)**.

---

## Requirements

- **Python 3.11–3.13** (tested on 3.13), or **Docker**.
- ~150 MB disk, no GPU. Runs fully **offline** (mock LLM, pure-Python RAG).
- Optional but recommended: an **OpenRouter API key**
  (<https://openrouter.ai/keys>) for a real LLM.

Python deps (`requirements.txt`): `openai`, `python-dotenv`, `mcp` (v1),
`fastapi`, `uvicorn`, `httpx`.

---

## Quick start (local)

```bash
# 1. install
pip install -r requirements.txt

# 2. (optional) configure the LLM
cp .env.example .env
#   edit .env -> set OPENROUTER_API_KEY=...  (leave blank to use the mock)

# 3. seed synthetic data
python seed_data.py

# 4a. run the web app
python run.py
#   open http://127.0.0.1:8000

# 4b. ...or the terminal client
python cli.py
```

## Quick start (Docker)

```bash
OPENROUTER_API_KEY=sk-or-... docker compose up --build
# open http://127.0.0.1:8000   (omit the key to run the offline mock)
```

---

## Choosing an OpenRouter model

Set `LLM_MODEL` in `.env`. The default is **`openai/gpt-4o-mini`**: cheap,
reliable tool-calling, and — importantly for a lab — compliant enough that the
planted injections actually fire.

- Good middle ground: `openai/gpt-4o-mini`, `anthropic/claude-3.5-haiku`,
  `google/gemini-flash-1.5`.
- Free tier: `meta-llama/llama-3.3-70b-instruct:free`.
- **Caveat:** frontier/safety-tuned models often **refuse** some attacks
  (prompt-leak, obvious transfers), which makes the lab look "broken" when it
  is actually the model defending. That refusal is itself worth studying. Use
  a mid-tier model to see the full chains, or the offline mock for a
  deterministic baseline.

No key? The lab auto-selects the **offline mock LLM** so every tool/RAG chain
still demonstrates. See `agent/llm.py` for exactly how faithful it is.

---

## Try it in 60 seconds

In the web UI (as the default `CUST-1001`):

1. `Can I get a refund on my overdraft fee?`  → watch the trace panel:
   the poisoned KB doc makes the agent leak secrets, **email them to an
   attacker**, and **move money to ACC-9999** — from a totally benign question.
2. `cat lab/outbox.log` and
   `sqlite3 lab/novabank.db "select account_id,balance from accounts;"` to
   confirm the exfiltration and transfer really happened.
3. Then work through `docs/CHALLENGES.md`.

---

## Plugging the MCP server into a real MCP client

The server is a standalone MCP server (stdio). Example Claude Desktop entry:

```json
{
  "mcpServers": {
    "novabank": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/absolute/path/to/ML-OPS-TEST-AGENT"
    }
  }
}
```

or inspect it with the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector python -m mcp_server.server
```

---

## Resetting state

- Clear poisoned conversation memory: **Reset** button, or
  `curl -X POST localhost:8000/api/reset -d '{"session_id":"default"}' -H 'content-type: application/json'`.
- Restore balances / re-create the sandbox: `python seed_data.py`.

---

## Tests

```bash
python -m pytest -q        # smoke tests: tools fire, injection chain works
```

## License / intent

Provided for **authorized, educational security testing**. You are responsible
for how you run it. Don't point it at real systems, and don't expose it.
