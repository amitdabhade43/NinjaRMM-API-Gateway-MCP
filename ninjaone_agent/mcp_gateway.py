"""Minimal stdio MCP client. Only read-only gateway tools are exposed."""
from __future__ import annotations
import json
from typing import Any
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from .config import AgentConfig

READ_ONLY_TOOLS = {"discover_endpoints", "inspect_endpoint",
                   "execute_endpoint", "execute_paginated_endpoint"}

def _decode_result(result: Any) -> Any:
    if getattr(result, "isError", False):
        messages = [getattr(item, "text", "") for item in getattr(result, "content", [])]
        raise RuntimeError("MCP tool error: " + " ".join(messages))
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
    return {}

class GatewayConnection:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.session = None
        self._stdio_context = None

    async def __aenter__(self):
        server = StdioServerParameters(command=self.config.mcp_command,
                                       args=list(self.config.mcp_args), env=None)
        self._stdio_context = stdio_client(server)
        read, write = await self._stdio_context.__aenter__()
        self.session = ClientSession(read, write)
        await self.session.__aenter__()
        await self.session.initialize()
        tools = await self.session.list_tools()
        names = {tool.name for tool in tools.tools}
        missing = READ_ONLY_TOOLS - names
        if missing:
            raise RuntimeError("Gateway missing tools: " + ", ".join(sorted(missing)))
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.session:
            await self.session.__aexit__(exc_type, exc, tb)
        if self._stdio_context:
            await self._stdio_context.__aexit__(exc_type, exc, tb)

    async def call(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in READ_ONLY_TOOLS:
            raise PermissionError(f"Agent is not allowed to call MCP tool {name!r}.")
        if not self.session:
            raise RuntimeError("MCP session is not connected.")
        return _decode_result(await self.session.call_tool(name, arguments))
