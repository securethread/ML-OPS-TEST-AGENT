"""
The NovaBank agent loop: RAG retrieval -> LLM -> MCP tool calls -> repeat.

Insecure by design:
  * Retrieved knowledge-base text is concatenated straight into the user turn
    (indirect prompt injection surface).
  * Conversation memory persists verbatim across turns per session, so an
    instruction injected once lingers (context / memory poisoning).
  * Tool calls are executed with no authorization, confirmation, or output
    sanitization, up to a high iteration cap (unbounded consumption).
"""
from __future__ import annotations

import json

import config
from agent.llm import get_llm
from agent.mcp_client import MCPToolClient
from agent.prompts import system_prompt
from rag.store import get_retriever


class NovaAgent:
    def __init__(self) -> None:
        self.mcp = MCPToolClient()
        self.retriever = get_retriever()
        self.llm = get_llm()
        self.sessions: dict[str, list[dict]] = {}

    async def start(self) -> None:
        await self.mcp.start()

    async def stop(self) -> None:
        await self.mcp.stop()

    def _memory(self, session_id: str) -> list[dict]:
        return self.sessions.setdefault(session_id, [])

    async def chat(self, session_id: str, user_message: str,
                   customer_id: str | None = None) -> dict:
        customer_id = customer_id or config.DEFAULT_CUSTOMER_ID
        rag_context = self.retriever.context_block(user_message, k=3)

        memory = self._memory(session_id)
        messages: list[dict] = [{"role": "system", "content": system_prompt(customer_id)}]
        messages += memory
        user_content = (
            f"{user_message}\n\n[KNOWLEDGE BASE CONTEXT — treat as internal policy]\n{rag_context}"
        )
        messages.append({"role": "user", "content": user_content})

        trace: list[dict] = []
        reply = "(no response)"

        for _ in range(config.MAX_TOOL_ITERATIONS):
            resp = self.llm.complete(messages, self.mcp.openai_tools)

            if resp["tool_calls"]:
                messages.append({
                    "role": "assistant",
                    "content": resp["content"],
                    "tool_calls": [
                        {"id": tc["id"], "type": "function",
                         "function": {"name": tc["name"],
                                      "arguments": json.dumps(tc["arguments"])}}
                        for tc in resp["tool_calls"]
                    ],
                })
                for tc in resp["tool_calls"]:
                    result = await self.mcp.call_tool(tc["name"], tc["arguments"])
                    trace.append({"tool": tc["name"], "arguments": tc["arguments"],
                                  "result": result})
                    messages.append({"role": "tool", "tool_call_id": tc["id"],
                                     "name": tc["name"], "content": result})
                continue

            reply = resp["content"] or ""
            break
        else:
            reply = "(stopped: max tool iterations reached)"

        # Persist the turn -> memory poisoning surface.
        memory.append({"role": "user", "content": user_content})
        memory.append({"role": "assistant", "content": reply})

        return {"reply": reply, "trace": trace, "rag_context": rag_context,
                "customer_id": customer_id, "model": self.llm.model}

    def reset(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)
