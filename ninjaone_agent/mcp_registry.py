"""Multi-server MCP connection and tool discovery registry.

This stage deliberately discovers tools without executing them. Tool execution
and per-tool permission decisions are added in the next stage.
"""
from __future__ import annotations

import json
import os
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", self.name):
            raise ValueError(f"Invalid MCP server name: {self.name!r}")
        if not self.command.strip():
            raise ValueError(f"MCP server {self.name!r} has no command.")
        if not all(isinstance(item, str) for item in self.args):
            raise ValueError(f"MCP server {self.name!r} args must be strings.")
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in self.env.items()):
            raise ValueError(f"MCP server {self.name!r} environment values must be strings.")

    @classmethod
    def load_all(cls, default_command: str, default_args: tuple[str, ...]) -> list["MCPServerConfig"]:
        """Load JSON server definitions, or fall back to the existing NinjaOne server."""
        raw = os.getenv("NINJA_AGENT_MCP_SERVERS_JSON", "").strip()
        if not raw:
            return [cls(name="ninjaone", command=default_command, args=default_args)]

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("NINJA_AGENT_MCP_SERVERS_JSON must contain valid JSON.") from exc

        if isinstance(payload, dict):
            payload = payload.get("servers")
        if not isinstance(payload, list) or not payload:
            raise ValueError("MCP server configuration must be a non-empty JSON array (or an object with a 'servers' array).")

        servers: list[MCPServerConfig] = []
        seen: set[str] = set()
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError("Each MCP server configuration must be a JSON object.")
            name = str(item.get("name", "")).strip()
            if name.casefold() in seen:
                raise ValueError(f"Duplicate MCP server name: {name!r}")
            seen.add(name.casefold())
            args = item.get("args", [])
            env = item.get("env", {})
            if not isinstance(args, list) or not isinstance(env, dict):
                raise ValueError(f"Server {name!r}: args must be an array and env must be an object.")
            servers.append(cls(name=name, command=str(item.get("command", "")),
                               args=tuple(args), env=env))
        return servers


@dataclass(frozen=True)
class MCPToolInfo:
    server: str
    name: str
    qualified_name: str
    description: str
    input_schema: dict[str, Any]


class MultiMCPManager:
    """Connect configured stdio MCP servers and build a collision-safe tool registry."""

    def __init__(self, servers: list[MCPServerConfig]):
        self.servers = servers
        self._stack = AsyncExitStack()
        self.sessions: dict[str, ClientSession] = {}
        self.tools: dict[str, MCPToolInfo] = {}
        self.connection_errors: dict[str, str] = {}

    async def __aenter__(self) -> "MultiMCPManager":
        for server in self.servers:
            try:
                child_env = dict(os.environ)
                child_env.update(server.env)
                params = StdioServerParameters(
                    command=server.command, args=list(server.args), env=child_env
                )
                read_stream, write_stream = await self._stack.enter_async_context(stdio_client(params))
                session = ClientSession(read_stream, write_stream)
                await self._stack.enter_async_context(session)
                await session.initialize()
                self.sessions[server.name] = session

                response = await session.list_tools()
                for tool in response.tools:
                    qualified = f"{server.name}.{tool.name}"
                    self.tools[qualified] = MCPToolInfo(
                        server=server.name,
                        name=tool.name,
                        qualified_name=qualified,
                        description=getattr(tool, "description", "") or "",
                        input_schema=getattr(tool, "inputSchema", {}) or {},
                    )
            except Exception as exc:
                self.connection_errors[server.name] = f"{type(exc).__name__}: {exc}"

        if not self.sessions:
            await self._stack.aclose()
            details = "; ".join(f"{name}: {error}" for name, error in self.connection_errors.items())
            raise RuntimeError("Could not connect to any configured MCP server. " + details)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._stack.__aexit__(exc_type, exc, tb)

    def list_tools(self) -> list[MCPToolInfo]:
        """Return tools with server-qualified names; duplicate tool names remain distinct."""
        return sorted(self.tools.values(), key=lambda item: item.qualified_name)

    async def call_tool(self, qualified_name: str, arguments: dict[str, Any]) -> Any:
        """Execute a previously discovered, server-qualified tool."""
        tool = self.tools.get(qualified_name)
        if tool is None:
            raise KeyError(f"Unknown MCP tool: {qualified_name}")
        session = self.sessions.get(tool.server)
        if session is None:
            raise RuntimeError(f"MCP server {tool.server!r} is not connected.")
        result = await session.call_tool(tool.name, arguments)
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

    def server_status(self) -> dict[str, Any]:
        return {
            "connected": sorted(self.sessions),
            "failed": dict(self.connection_errors),
            "tool_count": len(self.tools),
        }
