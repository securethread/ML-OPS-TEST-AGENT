"""
NovaBank web app: chat UI + REST API in front of the vulnerable agent.

Insecure by design at the web layer too:
  * The browser renders the assistant reply with innerHTML (no sanitization),
    so model output containing HTML/JS executes -> insecure output handling /
    (stored, via memory) XSS.
  * Identity comes from an HMAC token, but the tools never re-check it, so you
    can act on any customer (IDOR); the signing secret is leakable -> forgeable.
  * /api/kb/add ingests untrusted documents (live RAG poisoning).
  * /api/debug exposes internal state (system prompt, secrets, tools).
"""
from __future__ import annotations

import hashlib
import hmac
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import challenges
import config
from agent.core import NovaAgent
from agent.prompts import system_prompt

agent: NovaAgent | None = None


# -- session token: identity is server-anchored, but tools never re-check it,
#    and the signing secret is leakable (get_admin_config) -> forgeable.
def _sign(customer_id: str) -> str:
    sig = hmac.new(config.SESSION_SECRET.encode(), customer_id.encode(),
                   hashlib.sha256).hexdigest()[:16]
    return f"{customer_id}.{sig}"


def _identity(token: str | None) -> str | None:
    if not token or "." not in token:
        return None
    cid, _, sig = token.rpartition(".")
    return cid if hmac.compare_digest(_sign(cid), token) else None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent
    agent = NovaAgent()
    await agent.start()
    yield
    await agent.stop()


app = FastAPI(title="NovaBank Vulnerable Agent Lab", lifespan=lifespan)


@app.post("/api/login")
async def login(request: Request):
    """Real-ish auth: password check -> HMAC-signed token bound to a customer.
    (Password is shared/lab-public; the point is that the TOKEN anchors
    identity -- which the tools then ignore.)"""
    body = await request.json()
    if body.get("password") != config.LAB_PASSWORD:
        return JSONResponse({"error": "bad password"}, status_code=401)
    cid = body.get("customer_id") or config.DEFAULT_CUSTOMER_ID
    return {"token": _sign(cid), "customer_id": cid}


@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    message = body.get("message", "")
    session_id = body.get("session_id") or "default"
    # Identity comes from the signed token, not the request body.
    token = (request.headers.get("authorization", "").removeprefix("Bearer ").strip()
             or body.get("token"))
    customer_id = _identity(token)
    if not customer_id:
        return JSONResponse({"error": "unauthenticated"}, status_code=401)
    # ...but agent.chat / the tools never enforce that identity (IDOR).
    result = await agent.chat(session_id, message, customer_id)
    return JSONResponse(result)


@app.post("/api/kb/add")
async def kb_add(request: Request):
    """Untrusted knowledge-base ingestion (models a scraped page / uploaded
    doc). No validation -> live RAG poisoning."""
    body = await request.json()
    agent.retriever.add_document(body.get("source") or "user_upload",
                                 body.get("text") or "")
    return {"ok": True, "docs": len(agent.retriever.documents)}


@app.get("/api/challenges")
async def list_challenges():
    return challenges.as_list()


@app.post("/api/reset")
async def reset(request: Request):
    body = await request.json()
    agent.reset(body.get("session_id") or "default")
    agent.retriever.reload()   # drop any planted KB docs
    return {"ok": True}


@app.get("/api/debug")
async def debug():
    """Intentional information disclosure endpoint."""
    return {
        "model": agent.llm.model,
        "mock_mode": config.USE_MOCK_LLM,
        "shell_enabled": config.ENABLE_SHELL_TOOL,
        "system_prompt_example": system_prompt(config.DEFAULT_CUSTOMER_ID),
        "tools": [t["function"]["name"] for t in agent.mcp.openai_tools],
        "fake_secrets": config.FAKE_SECRETS,
    }


@app.get("/")
async def index():
    return FileResponse(config.BASE_DIR / "web" / "static" / "index.html")


app.mount("/static", StaticFiles(directory=str(config.BASE_DIR / "web" / "static")), name="static")
