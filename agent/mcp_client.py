"""
Real MCP client: launches the NovaBank MCP server as a stdio subprocess,
discovers its tools, and calls them over the Model Context Protocol.

The agent uses tool *descriptions exactly as advertised by the server* -- so
the poisoned get_exchange_rate description reaches the model unmodified, which
is the whole point of the MCP tool-poisoning demo.
"""
from __future__ import annotations

import os
import sys
from contextlib import AsyncExitStack
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

import config


def _extract_text(result: Any) -> str:
    """Flatten an MCP CallToolResult into plain text."""
    parts: list[str] = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        parts.append(text if text is not None else str(item))
    return "\n".join(parts) if parts else "(no content)"


class MCPToolClient:
    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self.session: ClientSession | None = None
        self.openai_tools: list[dict] = []
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        env = dict(os.environ)
        # Ensure `python -m mcp_server.server` resolves from the project root.
        env["PYTHONPATH"] = str(config.BASE_DIR) + os.pathsep + env.get("PYTHONPATH", "")
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mcp_server.server"],
            cwd=str(config.BASE_DIR),
            env=env,
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        listing = await self.session.list_tools()
        self.openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": t.inputSchema or {"type": "object", "properties": {}},
                },
            }
            for t in listing.tools
        ]
        self._started = True

    async def call_tool(self, name: str, arguments: dict) -> str:
        if self.session is None:
            raise RuntimeError("MCP client not started")
        result = await self.session.call_tool(name, arguments)
        return _extract_text(result)

    async def stop(self) -> None:
        await self._stack.aclose()
        self._started = False
        self.session = None
