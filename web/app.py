"""
NovaBank web app: chat UI + REST API in front of the vulnerable agent.

Insecure by design at the web layer too:
  * The browser renders the assistant reply with innerHTML (no sanitization),
    so model output containing HTML/JS executes -> insecure output handling /
    (stored, via memory) XSS.
  * The client supplies its own `customer_id`, which the server trusts -> the
    "authenticated" identity is attacker-controlled (broken authZ).
  * /api/debug exposes internal state (system prompt, secrets, corpus).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import config
from agent.core import NovaAgent
from agent.prompts import system_prompt

agent: NovaAgent | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent
    agent = NovaAgent()
    await agent.start()
    yield
    await agent.stop()


app = FastAPI(title="NovaBank Vulnerable Agent Lab", lifespan=lifespan)


@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    message = body.get("message", "")
    # Client-controlled identity -- trusted blindly (broken authZ).
    customer_id = body.get("customer_id") or config.DEFAULT_CUSTOMER_ID
    session_id = body.get("session_id") or "default"
    result = await agent.chat(session_id, message, customer_id)
    return JSONResponse(result)


@app.post("/api/reset")
async def reset(request: Request):
    body = await request.json()
    agent.reset(body.get("session_id") or "default")
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
