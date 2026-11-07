"""One-call, schema-checked execution across configured MCP servers.

This first execution stage intentionally performs one selected tool call per
request. Multi-step reasoning and bounded follow-up calls are a later stage.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .llm import LocalLLM
from .mcp_registry import MCPToolInfo, MultiMCPManager

_WORDS = re.compile(r"[a-z0-9_]+")

# Conservative default policy. A server can expose write tools, but the agent
# will not invoke them merely because the model selected them.
_READ_PREFIXES = ("get_", "list_", "search_", "find_", "read_", "inspect_",
                  "discover_", "describe_", "query_", "fetch_", "lookup_")
_NINJAONE_SAFE_TOOLS = {
    "discover_endpoints", "inspect_endpoint", "execute_endpoint",
    "execute_paginated_endpoint",
}


def is_read_only_candidate(tool: MCPToolInfo) -> bool:
    if tool.server.casefold() == "ninjaone":
        return tool.name in _NINJAONE_SAFE_TOOLS
    return tool.name.casefold().startswith(_READ_PREFIXES)


def rank_tools(question: str, tools: list[MCPToolInfo], limit: int = 10) -> list[MCPToolInfo]:
    """Cheap lexical shortlist; OLMo sees only the most relevant safe tools."""
    query = set(_WORDS.findall(question.casefold()))
    ranked: list[tuple[int, str, MCPToolInfo]] = []
    for tool in tools:
        if not is_read_only_candidate(tool):
            continue
        text = f"{tool.qualified_name} {tool.description} {json.dumps(tool.input_schema)}".casefold()
        words = set(_WORDS.findall(text))
        score = len(query & words)
        # Keep generic tools with zero overlap out of the prompt.
        if score:
            ranked.append((score, tool.qualified_name, tool))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return [row[2] for row in ranked[:max(1, limit)]]


def validate_tool_arguments(tool: MCPToolInfo, arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be a JSON object.")
    schema = tool.input_schema if isinstance(tool.input_schema, dict) else {}
    properties = schema.get("properties", {})
    if isinstance(properties, dict):
        unknown = set(arguments) - set(properties)
        if unknown:
            raise ValueError("Unsupported tool argument(s): " + ", ".join(sorted(unknown)))
    required = schema.get("required", [])
    missing = [name for name in required if name not in arguments]
    if missing:
        raise ValueError("Missing required tool argument(s): " + ", ".join(missing))
    return arguments


async def run_mcp_question(llm: LocalLLM, manager: MultiMCPManager, question: str) -> str:
    shortlist = rank_tools(question, manager.list_tools())
    if not shortlist:
        return "I couldn't find a suitable read-only MCP tool for that request."

    tool_catalog = [{
        "name": item.qualified_name,
        "description": item.description,
        "input_schema": item.input_schema,
    } for item in shortlist]
    system = (
        "You select one read-only MCP tool for the user's request. "
        "Use only the supplied tool catalog. Never invent tool names or arguments. "
        "Return one JSON object only: "
        '{"tool":"server.tool_name","arguments":{}}. '
        "If no tool is suitable, return {\"tool\":null,\"arguments\":{}}. "
        "Do not select write, update, create, delete, or action tools."
    )
    selection = await llm.complete_json(
        system,
        "USER REQUEST:\n" + question + "\n\nAVAILABLE TOOLS:\n" +
        json.dumps(tool_catalog, ensure_ascii=False),
    )
    selected_name = selection.get("tool")
    selected = next((item for item in shortlist
                     if item.qualified_name == selected_name), None)
    if selected is None:
        return "I couldn't select a valid read-only MCP tool for that request."

    arguments = validate_tool_arguments(selected, selection.get("arguments", {}))
    # The NinjaOne Gateway's generic endpoint executor can reach write
    # operations too. Require a concrete GET endpoint before invoking it.
    if selected.server.casefold() == "ninjaone" and selected.name in {
        "execute_endpoint", "execute_paginated_endpoint"
    }:
        endpoint = arguments.get("endpoint")
        if not isinstance(endpoint, str) or not endpoint.lstrip().upper().startswith("GET "):
            raise PermissionError("Only explicitly discovered GET endpoints may be executed.")
    result = await manager.call_tool(selected.qualified_name, arguments)
    result_text = json.dumps(result, ensure_ascii=False, default=str)[:18000]
    response_system = (
        "Answer the user's request using only the MCP result below. "
        "Do not invent records, counts, or facts. If the result is incomplete or "
        "does not contain the requested information, say so clearly. Be concise."
    )
    return await llm.complete(
        response_system,
        "USER REQUEST:\n" + question + "\n\nTOOL:\n" +
        selected.qualified_name + "\n\nVERIFIED TOOL RESULT:\n" + result_text,
        temperature=0.1,
    )
