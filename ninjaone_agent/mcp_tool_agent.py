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
from .content_filters import filter_result_payload, normalize_operator

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


async def run_mcp_question(
    llm: LocalLLM,
    manager: MultiMCPManager,
    question: str,
    max_steps: int = 4,
) -> str:
    """Run a bounded discover/inspect/execute loop over safe MCP tools."""
    all_tools = manager.list_tools()
    shortlist = rank_tools(question, all_tools)
    # The NinjaOne Gateway exposes a small set of workflow tools. Keep those
    # available together so OLMo can discover, inspect, then execute an API.
    for item in all_tools:
        if item.server.casefold() == "ninjaone" and is_read_only_candidate(item):
            if item not in shortlist:
                shortlist.append(item)
    shortlist = shortlist[:max(16, len(shortlist))]

    if not shortlist:
        return "I couldn't find a suitable read-only MCP tool for that request."

    tool_catalog = [{
        "name": item.qualified_name,
        "description": item.description,
        "input_schema": item.input_schema,
    } for item in shortlist]
    system = (
        "You are a careful MCP tool-using agent. You may call one supplied tool "
        "per step, or return a final answer. Use only the exact tool names and "
        "argument schemas supplied. Never invent endpoint names, parameters, "
        "records, or results. First discover an API operation when needed, "
        "inspect its schema before execution when parameters are not clear, "
        "then execute only a GET operation. Never call write, create, update, "
        "delete, raw-request, or action tools. Return JSON only in one of these "
        "forms: {\"action\":\"call\",\"tool\":\"server.tool\","
        "\"arguments\":{}} or {\"action\":\"final\",\"answer\":\"...\"}. "
        "The action field must be exactly call or final; never put a tool name "
        "in the action field. Put the selected tool name in the tool field. "
        "Do not repeat a tool call with identical arguments. "
        "When the user asks to find, match, exclude, compare, or narrow records "
        "by their content, include an optional filters array in the decision. "
        "Translate equivalent wording into canonical operators: equals, "
        "not_equals, contains, not_contains, starts_with, ends_with, in, "
        "not_in, greater_than, greater_than_or_equal, less_than, "
        "less_than_or_equal, is_empty, is_not_empty. Phrases like begins with, "
        "starts with, prefix, and has prefix mean starts_with; includes, "
        "contains, has, and mentions mean contains; exactly and matches mean "
        "equals; ends in and suffix mean ends_with. Do not require an exact "
        "keyword. Filter objects use field, operator, and value (value is "
        "omitted only for empty checks). Filters are AND-combined. Only use "
        "filters supported by the request and returned record fields."
    )
    history: list[dict[str, Any]] = []
    seen_calls: set[str] = set()
    active_filters: list[dict[str, Any]] = []
    filters_applied = False

    for step in range(max(1, min(max_steps, 6))):
        prompt = (
            "USER REQUEST:\n" + question +
            "\n\nAVAILABLE TOOLS:\n" + json.dumps(tool_catalog, ensure_ascii=False) +
            "\n\nPREVIOUS TOOL RESULTS:\n" + json.dumps(history, ensure_ascii=False, default=str) +
            f"\n\nChoose the next action. This is step {step + 1} of {max_steps}."
        )
        decision = await llm.complete_json(system, prompt)
        # Preserve structured content filters across discover/inspect/execute
        # steps. Natural-language synonyms are normalized by the shared engine.
        proposed_filters = decision.get("filters")
        if isinstance(proposed_filters, list):
            normalized_filters = []
            for item in proposed_filters:
                if not isinstance(item, dict):
                    continue
                normalized = dict(item)
                if "operator" in normalized:
                    normalized["operator"] = normalize_operator(normalized["operator"])
                normalized_filters.append(normalized)
            if normalized_filters:
                active_filters = normalized_filters

        # Some OLMo responses use the selected tool name as the action
        # (for example, action="discover_endpoints") instead of action="call".
        # Normalize that shorthand only when it matches an approved tool.
        action = decision.get("action")
        if action == "choose_endpoint":
            # OLMo sometimes invents a planning action instead of selecting
            # the supplied Gateway discovery tool. Resolve this safely and
            # deterministically; do not execute an API endpoint at this stage.
            discovery_tool = next(
                (item for item in shortlist
                 if item.server.casefold() == "ninjaone"
                 and item.name == "discover_endpoints"),
                None,
            )
            if discovery_tool is not None:
                decision["tool"] = discovery_tool.qualified_name
                decision["arguments"] = {"intent": question}
                decision["action"] = "call"
        elif action not in {"call", "final"}:
            action_tool = next(
                (item for item in shortlist
                 if action in {item.name, item.qualified_name}),
                None,
            )
            if action_tool is not None:
                decision["tool"] = action_tool.qualified_name
                decision["action"] = "call"

        if decision.get("action") == "final":
            answer = decision.get("answer")
            if isinstance(answer, str) and answer.strip():
                return answer.strip()
            return "The agent did not provide a valid final answer."

        if decision.get("action") != "call":
            return ("OLMo returned an unsupported action: " + repr(decision.get("action")) + ". " + "Decision received: " + json.dumps(decision, ensure_ascii=False, default=str)[:1200] + ". No MCP tool was executed.")

        name = decision.get("tool")
        selected = next((item for item in shortlist if item.qualified_name == name), None)
        if selected is None:
            return "OLMo selected a tool that was not in the approved tool shortlist."

        arguments = validate_tool_arguments(selected, decision.get("arguments", {}))
        call_key = selected.qualified_name + ":" + json.dumps(arguments, sort_keys=True, default=str)
        if call_key in seen_calls:
            return "The agent attempted to repeat the same tool call. Stopping safely."
        seen_calls.add(call_key)

        if selected.server.casefold() == "ninjaone":
            if selected.name == "execute_raw_request":
                raise PermissionError("Raw NinjaOne requests are not permitted in generic mode.")
            if selected.name in {"execute_endpoint", "execute_paginated_endpoint"}:
                endpoint = arguments.get("endpoint")
                if not isinstance(endpoint, str) or not endpoint.lstrip().upper().startswith("GET "):
                    raise PermissionError("Only explicitly discovered GET endpoints may be executed.")

        result = await manager.call_tool(selected.qualified_name, arguments)
        entry: dict[str, Any] = {
            "tool": selected.qualified_name,
            "arguments": arguments,
            "result": result,
        }
        # Apply filters to actual returned records in Python, not by asking the
        # LLM to visually scan a potentially large page of JSON.
        if active_filters and not filters_applied:
            try:
                result, filter_summary = filter_result_payload(result, active_filters)
                entry["result"] = result
                entry["filter_summary"] = filter_summary
                filters_applied = True
            except ValueError:
                # Discovery/inspection responses are not record collections.
                # Keep the filters pending for the eventual data response.
                pass
        history.append(entry)
        # Keep the context bounded for local inference.
        history = history[-4:]

    final_system = (
        "Answer the user's request using only the MCP tool results below. "
        "Do not invent facts, counts, or records. If the available results do "
        "not fully answer the request, say what is missing."
    )
    return await llm.complete(
        final_system,
        "USER REQUEST:\n" + question + "\n\nAPPLIED FILTERS:\n" +
        json.dumps(active_filters, ensure_ascii=False, default=str) +
        "\n\nMCP TOOL RESULTS:\n" +
        json.dumps(history, ensure_ascii=False, default=str)[:18000],
        temperature=0.1,
    )
