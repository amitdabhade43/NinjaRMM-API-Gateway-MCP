"""One-call, schema-checked execution across configured MCP servers.

This first execution stage intentionally performs one selected tool call per
request. Multi-step reasoning and bounded follow-up calls are a later stage.
"""
from __future__ import annotations

import difflib
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
    "find_endpoint", "describe_endpoint", "call", "raw_call",
    "memory_save", "memory_list", "memory_delete",
}



_NINJAONE_COMPAT_TOOLS = {
    "find_endpoint", "describe_endpoint", "call", "raw_call",
    "memory_save", "memory_list", "memory_delete",
}

# Simple, unfiltered counts can be handled deterministically without asking
# OLMo to plan, inspect, execute, and then summarize the same request.
_COUNT_RESOURCES = {
    "organization": "organizations", "organizations": "organizations",
    "org": "organizations", "orgs": "organizations",
    "device": "devices", "devices": "devices",
    "user": "users", "users": "users",
    "technician": "technicians", "technicians": "technicians",
    "location": "locations", "locations": "locations",
    "group": "groups", "groups": "groups",
    "role": "roles", "roles": "roles",
    "alert": "alerts", "alerts": "alerts",
    "policy": "policies", "policies": "policies",
}
_COUNT_FILLER_WORDS = {
    "how", "many", "count", "number", "of", "total", "do", "we", "have",
    "in", "ninjaone", "ninja", "one", "the", "all", "what", "are", "is",
    "there", "currently",
}


def _simple_count_resource(question: str) -> str | None:
    """Return a resource only for a plain, unfiltered count request."""
    if not re.search(r"\b(how\s+many|count|number\s+of|total)\b", question, re.I):
        return None
    words = set(_WORDS.findall(question.casefold()))
    resources = words & set(_COUNT_RESOURCES)
    if len(resources) != 1 or words - _COUNT_FILLER_WORDS - resources:
        return None
    return _COUNT_RESOURCES[next(iter(resources))]


def _simple_name_resource(question: str) -> str | None:
    """Detect a plain request for resource names, including minor spelling errors."""
    if not re.search(r"\bname(?:s)?\b", question, re.I):
        return None

    words = set(_WORDS.findall(question.casefold()))
    matched_words: set[str] = set()
    resources: set[str] = set()
    for word in words:
        match = word if word in _COUNT_RESOURCES else None
        if match is None:
            candidates = difflib.get_close_matches(
                word, list(_COUNT_RESOURCES), n=1, cutoff=0.82
            )
            match = candidates[0] if candidates else None
        if match:
            matched_words.add(word)
            resources.add(_COUNT_RESOURCES[match])

    if len(resources) != 1:
        return None

    allowed = _COUNT_FILLER_WORDS | {
        "can", "could", "i", "get", "show", "list", "fetch", "retrieve",
        "display", "find", "give", "tell", "me", "what", "which", "please",
        "want", "need", "name", "names",
    }
    if words - allowed - matched_words:
        return None
    return next(iter(resources))


def _count_collection(payload: Any, resource: str) -> list[Any] | None:
    """Extract an unambiguous collection from the Gateway response envelope."""
    if not isinstance(payload, dict) or payload.get("error"):
        return None
    data = payload.get("data", payload)
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return None
    preferred = {
        resource, resource.rstrip("s"), "results", "items", "data",
    }
    for key in preferred:
        value = data.get(key)
        if isinstance(value, list):
            return value
    arrays = [value for value in data.values() if isinstance(value, list)]
    return arrays[0] if len(arrays) == 1 else None


async def _fast_count_with_compat_tools(
    manager: MultiMCPManager, resource: str
) -> str:
    """Discover and count a plain collection using Python, with no extra LLM call."""
    available = {tool.qualified_name for tool in manager.list_tools()}
    required_tools = {
        "ninjaone.find_endpoint",
        "ninjaone.describe_endpoint",
        "ninjaone.call",
    }
    if not required_tools.issubset(available):
        return "The fast count path is unavailable because the NinjaOne compatibility tools are incomplete."

    discovery = await manager.call_tool(
        "ninjaone.find_endpoint",
        {"query": f"list {resource}", "limit": 20},
    )
    candidates = discovery.get("results", []) if isinstance(discovery, dict) else []
    singular = resource[:-1] if resource.endswith("s") else resource
    selected_endpoint = None
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        endpoint = candidate.get("endpoint")
        method = str(candidate.get("method", "")).upper()
        searchable = " ".join(str(candidate.get(key, "")) for key in (
            "path", "summary", "operation_id", "category", "endpoint"
        )).casefold()
        if (
            isinstance(endpoint, str)
            and (method == "GET" or endpoint.upper().startswith("GET "))
            and (resource in searchable or singular in searchable)
        ):
            selected_endpoint = endpoint
            break

    if not selected_endpoint:
        return f"I couldn't safely identify a GET endpoint for counting {resource}."

    detail = await manager.call_tool(
        "ninjaone.describe_endpoint", {"endpoint": selected_endpoint}
    )
    if not isinstance(detail, dict) or str(detail.get("method", "")).upper() != "GET":
        return f"The discovered endpoint {selected_endpoint} could not be verified as a GET operation."
    if "{" in str(detail.get("path", "")) or "}" in str(detail.get("path", "")):
        return f"The endpoint {selected_endpoint} requires path parameters, so I did not execute it."
    required_parameters = [
        item for item in detail.get("parameters", [])
        if isinstance(item, dict) and item.get("required")
    ]
    if required_parameters:
        names = ", ".join(str(item.get("name", "unknown")) for item in required_parameters)
        return f"The endpoint {selected_endpoint} requires parameters ({names}); I did not guess their values."

    result = await manager.call_tool(
        "ninjaone.call", {"endpoint": selected_endpoint}
    )
    if isinstance(result, dict) and result.get("error"):
        return f"NinjaOne returned an error while counting {resource}: {result['error']}"
    records = _count_collection(result, resource)
    if records is None:
        return (
            f"I retrieved {selected_endpoint}, but its response did not contain "
            "an unambiguous record collection to count."
        )

    count = len(records)
    if isinstance(result, dict) and (result.get("truncated") or result.get("complete") is False):
        return f"At least {count} {resource} were returned; the response was incomplete, so this may not be the total."
    label = resource[:-1] if count == 1 and resource.endswith("s") else resource
    return f"There are {count} {label} in NinjaOne."




def _record_name(record: Any) -> str | None:
    """Find a useful display-name field without sending full records to OLMo."""
    if isinstance(record, dict):
        preferred = {
            "name", "displayname", "organizationname", "orgname",
            "devicename", "username", "fullname", "companyname",
        }
        for key, value in record.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if normalized in preferred and isinstance(value, (str, int)):
                return str(value)
        for value in record.values():
            found = _record_name(value)
            if found:
                return found
    elif isinstance(record, list):
        for value in record:
            found = _record_name(value)
            if found:
                return found
    return None


async def _fast_names_with_compat_tools(
    manager: MultiMCPManager, resource: str
) -> str | None:
    """Discover and return resource names with Python; no OLMo planning/summarization."""
    available = {tool.qualified_name for tool in manager.list_tools()}
    required_tools = {
        "ninjaone.find_endpoint",
        "ninjaone.describe_endpoint",
        "ninjaone.call",
    }
    if not required_tools.issubset(available):
        return None

    # Keep fuzzy discovery broad across all supported methods; choose a safe
    # collection GET only after seeing the ranked OpenAPI candidates.
    discovery = await manager.call_tool(
        "ninjaone.find_endpoint", {"query": f"list {resource}", "limit": 20}
    )
    candidates = discovery.get("results", []) if isinstance(discovery, dict) else []
    singular = resource[:-1] if resource.endswith("s") else resource
    selected_endpoint = None
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        endpoint = candidate.get("endpoint")
        method = str(candidate.get("method", "")).upper()
        if not method and isinstance(endpoint, str):
            method = endpoint.split(None, 1)[0].upper() if " " in endpoint else ""
        path = str(candidate.get("path", ""))
        searchable = " ".join(str(candidate.get(key, "")) for key in (
            "path", "summary", "operation_id", "category", "endpoint"
        )).casefold()
        if (
            isinstance(endpoint, str)
            and method == "GET"
            and "{" not in path
            and (resource in searchable or singular in searchable)
        ):
            selected_endpoint = endpoint
            break

    if not selected_endpoint:
        return None

    detail = await manager.call_tool(
        "ninjaone.describe_endpoint", {"endpoint": selected_endpoint}
    )
    if not isinstance(detail, dict) or str(detail.get("method", "")).upper() != "GET":
        return None
    if "{" in str(detail.get("path", "")) or "}" in str(detail.get("path", "")):
        return None
    required_parameters = [
        item for item in detail.get("parameters", [])
        if isinstance(item, dict) and item.get("required")
    ]
    if required_parameters:
        return None

    result = await manager.call_tool("ninjaone.call", {"endpoint": selected_endpoint})
    if isinstance(result, dict) and result.get("error"):
        return f"NinjaOne returned an error while retrieving {resource}: {result['error']}"
    records = _count_collection(result, resource)
    if records is None:
        return None

    names = []
    for record in records:
        name = _record_name(record)
        if name and name not in names:
            names.append(name)
    if not names:
        return (
            f"NinjaOne returned {len(records)} {resource}, but the response did not "
            "contain a recognized name field."
        )

    output = [f"{resource.capitalize()}"]
    output.extend(f"{index}. {name}" for index, name in enumerate(names, 1))
    output.append(f"Total: {len(records)} {resource}")
    if isinstance(result, dict) and (result.get("truncated") or result.get("complete") is False):
        output.append("Note: the API response was incomplete; additional records may exist.")
    return "\n".join(output)
\n\ndef is_read_only_candidate(tool: MCPToolInfo) -> bool:
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



def _compact_tool_schema(tool: MCPToolInfo) -> dict[str, Any]:
    """Keep the model's tool catalog readable and cheap to process."""
    schema = tool.input_schema if isinstance(tool.input_schema, dict) else {}
    properties = schema.get("properties", {})
    compact_properties = {}
    if isinstance(properties, dict):
        for name, details in properties.items():
            if not isinstance(details, dict):
                compact_properties[name] = {}
                continue
            item = {"type": details.get("type")}
            if details.get("description"):
                item["description"] = str(details["description"])[:180]
            if details.get("enum"):
                item["enum"] = details["enum"]
            compact_properties[name] = item
    return {
        "name": tool.qualified_name,
        "description": tool.description[:500],
        "required": schema.get("required", []),
        "properties": compact_properties,
    }


def _find_tool(shortlist: list[MCPToolInfo], name: Any) -> MCPToolInfo | None:
    if not isinstance(name, str) or not name.strip():
        return None
    candidate = name.strip().casefold()
    for tool in shortlist:
        if candidate in {tool.qualified_name.casefold(), tool.name.casefold()}:
            return tool
    # Small naming variation frequently produced by local models:
    # discover_endpoint vs discover_endpoints. Only resolve when unique.
    normalized = candidate.rstrip("s")
    matches = [
        tool for tool in shortlist
        if tool.name.casefold().rstrip("s") == normalized
        or tool.qualified_name.casefold().rstrip("s") == normalized
    ]
    return matches[0] if len(matches) == 1 else None


def _normalize_decision(
    decision: dict[str, Any],
    shortlist: list[MCPToolInfo],
    question: str,
) -> tuple[str, MCPToolInfo | None, dict[str, Any]]:
    """Recover common local-model action variations without relaxing tool policy."""
    action = str(decision.get("action", "")).strip().casefold()
    arguments = decision.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}

    # Prefer an explicit, approved tool field. Some models emit action=get,
    # action=discover_endpoint, etc. even when the tool field is correct.
    selected = _find_tool(shortlist, decision.get("tool"))
    if selected is not None and action != "final":
        action = "call"

    if action == "final":
        return action, None, arguments

    if selected is None:
        selected = _find_tool(shortlist, decision.get("tool") or action)
        if selected is not None:
            action = "call"

    # If the model describes a planning operation (get/list/discover/choose)
    # but omits a concrete tool, route to the server's discovery tool. This
    # discovers the correct API operation instead of executing an invented path.
    if selected is None and action in {
        "get", "list", "search", "find", "find_endpoint", "discover_endpoint",
        "choose_endpoint", "select_endpoint", "lookup",
    }:
        selected = next(
            (tool for tool in shortlist
             if tool.server.casefold() == "ninjaone"
             and tool.name in {"find_endpoint", "discover_endpoints"}),
            None,
        )
        if selected is not None:
            arguments = {}
            action = "call"

    if selected is None or action != "call":
        return action, None, arguments

    # Fill only well-understood search-intent parameters from the original
    # request. All other required arguments must come from the model/schema.
    schema = selected.input_schema if isinstance(selected.input_schema, dict) else {}
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    for key in required:
        if key in arguments:
            continue
        if key.casefold() in {"intent", "query", "question", "search", "search_query"}:
            arguments[key] = question
        elif isinstance(properties, dict):
            details = properties.get(key, {})
            description = str(details.get("description", "")).casefold() if isinstance(details, dict) else ""
            if any(word in description for word in ("user request", "natural language", "search intent")):
                arguments[key] = question

    return "call", selected, arguments

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
    conversation_context: str = "",
    approval_callback=None,
) -> str:
    """Run a bounded discover/inspect/execute loop over safe MCP tools."""
    all_tools = manager.list_tools()

    # Fast path: plain collection counts need no planning or answer-generation
    # inference. Python discovers, verifies, executes and counts through the
    # seven-tool compatibility surface.
    count_resource = _simple_count_resource(question)
    if count_resource:
        available_names = {tool.qualified_name for tool in all_tools}
        if {
            "ninjaone.find_endpoint",
            "ninjaone.describe_endpoint",
            "ninjaone.call",
        }.issubset(available_names):
            try:
                return await _fast_count_with_compat_tools(manager, count_resource)
            except Exception as exc:
                return f"Unable to complete the NinjaOne count: {type(exc).__name__}: {exc}"

    # Simple name lookups are deterministic: avoid OLMo tool planning and
    # final summarization, which are the main latency/failure points for 7B models.
    name_resource = _simple_name_resource(question)
    if name_resource:
        available_names = {tool.qualified_name for tool in all_tools}
        if {
            "ninjaone.find_endpoint",
            "ninjaone.describe_endpoint",
            "ninjaone.call",
        }.issubset(available_names):
            try:
                answer = await _fast_names_with_compat_tools(manager, name_resource)
                if answer is not None:
                    return answer
            except Exception as exc:
                return f"Unable to retrieve NinjaOne {name_resource}: {type(exc).__name__}: {exc}"

    # The MCP server exposes only the seven compatibility tools.
    has_compat_surface = any(
        item.server.casefold() == "ninjaone"
        and item.name in _NINJAONE_COMPAT_TOOLS
        for item in all_tools
    )
    agent_tools = [
        item for item in all_tools
        if (
            item.server.casefold() != "ninjaone"
            or not has_compat_surface
            or item.name in _NINJAONE_COMPAT_TOOLS
        )
    ]
    shortlist = rank_tools(question, agent_tools)
    for item in agent_tools:
        if item.server.casefold() != "ninjaone":
            continue
        if has_compat_surface:
            include_tool = item.name in _NINJAONE_COMPAT_TOOLS
        else:
            # Older MCP servers may not expose the compatibility aliases.
            include_tool = is_read_only_candidate(item)
        if include_tool and item not in shortlist:
            shortlist.append(item)

    if not shortlist:
        return "I couldn't find a suitable read-only MCP tool for that request."

    # Like Clawd-Code's central tool registry, keep tool metadata separate
    # from execution validation. The model sees a compact schema; Python
    # validates calls against the full MCP schema before dispatch.
    tool_catalog = [_compact_tool_schema(item) for item in shortlist]
    system = (
        "You are a careful MCP tool-using agent. You may call one supplied tool "
        "per step, or return a final answer. Use only the exact tool names and "
        "argument schemas supplied. Never invent endpoint names, parameters, "
        "records, or results. For endpoint discovery, call find_endpoint with "
        "the user's full natural-language intent and leave category and method "
        "unset unless the user explicitly requests a category or HTTP method. "
        "The default fuzzy search must consider all supported methods, not GET "
        "only. Use the returned ranked matches to choose the closest operation; "
        "do not ask the user to provide an API path or exact keyword. Inspect "
        "only the selected endpoint when its schema is needed, then retrieve "
        "only the records and fields needed to answer. "
        "GET calls may execute automatically. POST, PUT and PATCH may execute "
        "only after the Python CLI obtains explicit user confirmation. DELETE "
        "is permanently blocked. The call and raw_call aliases follow these "
        "same rules. Local "
        "memory_save, memory_list and memory_delete tools manage saved query "
        "templates only; use them only when the user explicitly asks to save, "
        "list, or delete a saved query. Never use these memory tools to infer "
        "permission for a tenant API write. Return JSON only in one of these "
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
            "CONVERSATION CONTEXT (may be empty):\n" + (conversation_context or "None") +
            "\n\nCURRENT USER REQUEST:\n" + question +
            "\n\nAVAILABLE TOOLS:\n" + json.dumps(tool_catalog, ensure_ascii=False) +
            "\n\nPREVIOUS TOOL RESULTS (use only relevant fields; do not repeat large results):\n" + json.dumps(history, ensure_ascii=False, default=str) +
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
                    try:
                        normalized["operator"] = normalize_operator(normalized["operator"])
                    except ValueError as exc:
                        history.append({
                            "filter_error": str(exc),
                            "hint": "Use one of the supported canonical filter operators.",
                        })
                        history = history[-4:]
                        normalized_filters = []
                        break
                normalized_filters.append(normalized)
            if normalized_filters:
                active_filters = normalized_filters
            elif proposed_filters:
                # Ask the model to repair an unsupported filter before making
                # a data request that could otherwise return misleading results.
                continue

        action, selected, normalized_arguments = _normalize_decision(
            decision, shortlist, question
        )
        if action == "final":
            answer = decision.get("answer")
            if isinstance(answer, str) and answer.strip():
                return answer.strip()
            return "The agent did not provide a valid final answer."

        if action != "call":
            return (
                "OLMo returned an unsupported action: " + repr(decision.get("action"))
                + ". Decision received: "
                + json.dumps(decision, ensure_ascii=False, default=str)[:1200]
                + ". No MCP tool was executed."
            )
        if selected is None:
            return "OLMo selected a tool that was not in the approved tool shortlist."

        try:
            arguments = validate_tool_arguments(selected, normalized_arguments)
        except ValueError as exc:
            # Similar to Clawd-Code's tool loop, return validation feedback to
            # the model so it can repair the call instead of crashing the CLI.
            history.append({
                "tool": selected.qualified_name,
                "tool_error": str(exc),
                "hint": "Correct the arguments using the supplied tool schema.",
            })
            history = history[-4:]
            continue

        call_key = selected.qualified_name + ":" + json.dumps(arguments, sort_keys=True, default=str)
        if call_key in seen_calls:
            return "The agent attempted to repeat the same tool call. Stopping safely."
        seen_calls.add(call_key)

        if selected.server.casefold() == "ninjaone":
            method = ""
            operation = ""
            if selected.name == "raw_call":
                operation = str(arguments.get("request", "")).strip()
                method = operation.split(None, 1)[0].upper() if operation else ""
            elif selected.name == "call":
                operation = str(arguments.get("endpoint", "")).strip()
                method = operation.split(None, 1)[0].upper() if operation else ""
            if selected.name in {"call", "raw_call"}:
                if method == "DELETE":
                    raise PermissionError("DELETE is permanently blocked, even after confirmation.")
                if method not in {"GET", "POST", "PUT", "PATCH"}:
                    raise PermissionError("The operation must use GET, POST, PUT or PATCH.")
                if method in {"POST", "PUT", "PATCH"}:
                    if approval_callback is None:
                        return (f"This request proposes {operation}. Run it in interactive mode "
                                "to review the operation and confirm before execution.")
                    approved = approval_callback(operation, arguments.get("body"))
                    if not approved:
                        return f"Cancelled. No {method} request was sent to NinjaOne."
                    arguments["approval_token"] = "LOCAL_USER_CONFIRMED"
            if selected.name == "memory_save" and not re.search(r"\b(save|remember|store)\b", question, re.I):
                raise PermissionError("Save a query template only when the user explicitly asks to save or remember it.")
            if selected.name == "memory_list" and not re.search(
                r"\b(saved queries|saved searches|saved query templates|memories)\b", question, re.I
            ):
                raise PermissionError("List saved-query memory only when the user asks to view saved queries.")
            if selected.name == "memory_delete" and not (
                re.search(r"\b(delete|remove|forget)\b", question, re.I)
                and re.search(r"\b(saved|memory|query|search)\b", question, re.I)
            ):
                raise PermissionError("Delete only a saved query when the user explicitly asks to remove it.")

        try:
            result = await manager.call_tool(selected.qualified_name, arguments)
        except Exception as exc:
            # Keep transient MCP/tool failures inside the bounded reasoning loop.
            history.append({
                "tool": selected.qualified_name,
                "arguments": arguments,
                "tool_error": f"{type(exc).__name__}: {exc}",
                "hint": "Use this error to correct the next tool call; do not repeat identical arguments.",
            })
            history = history[-4:]
            continue

        entry: dict[str, Any] = {
            "tool": selected.qualified_name,
            "arguments": arguments,
            "result": result,
        }
        # Apply filters to actual returned records in Python, not by asking the
        # LLM to visually scan a potentially large page of JSON.
        is_ninjaone_metadata_step = (
            selected.server.casefold() == "ninjaone"
            and selected.name in {"discover_endpoints", "inspect_endpoint", "find_endpoint", "describe_endpoint"}
        )
        if active_filters and not filters_applied and not is_ninjaone_metadata_step:
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
        "CONVERSATION CONTEXT:\n" + (conversation_context or "None") +
        "\n\nCURRENT USER REQUEST:\n" + question + "\n\nAPPLIED FILTERS:\n" +
        json.dumps(active_filters, ensure_ascii=False, default=str) +
        "\n\nMCP TOOL RESULTS:\n" +
        json.dumps(history, ensure_ascii=False, default=str)[:18000],
        temperature=0.1,
    )
