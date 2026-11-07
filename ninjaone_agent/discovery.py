"""Ground task intent in actual Gateway/OpenAPI operations."""
from __future__ import annotations
import re
from typing import Any
from .config import AgentConfig
from .mcp_gateway import GatewayConnection

def choose_candidate(candidates: list[dict[str, Any]], semantic: dict[str, Any],
                     task: dict[str, Any]) -> dict[str, Any]:
    selected_items = semantic.get("selected", []) if isinstance(semantic, dict) else []
    selected_keys = [item.get("endpoint") if isinstance(item, dict) else item
                     for item in selected_items]
    selected_pool = [item for key in selected_keys for item in candidates
                     if item.get("endpoint") == key]
    mode = semantic.get("mode") if isinstance(semantic, dict) else None
    if mode == "local_semantic" and selected_pool:
        return selected_pool[0]

    # Fuzzy fallback: choose collection routes for list/count and item routes for details.
    pool = selected_pool or candidates
    wants_item = task.get("operation") == "details" or task.get("identifier") is not None
    if wants_item:
        shaped = [item for item in pool if re.search(r"{[^}]+}", str(item.get("path", item.get("endpoint", ""))))]
    else:
        shaped = [item for item in pool if not re.search(r"{[^}]+}", str(item.get("path", item.get("endpoint", ""))))]
    return (shaped or pool or candidates)[0]

async def discover_for_task(gateway: GatewayConnection, config: AgentConfig,
                            task: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    filter_text = " ".join(
        f"{item['field']} {item['operator']} {item.get('value')}" for item in task["filters"]
    )
    intent = f"{task['description']} {task['entity']} {task['operation']} {filter_text}".strip()
    result = await gateway.call("discover_endpoints", {
        "intent": intent, "method": "GET", "candidate_limit": config.max_candidates,
    })
    candidates = result.get("candidates", []) if isinstance(result, dict) else []
    if not candidates:
        raise RuntimeError(f"No GET endpoint found for task: {task['description']}")
    semantic = result.get("semantic", {}) if isinstance(result, dict) else {}
    selected = choose_candidate(candidates, semantic, task)
    endpoint = selected.get("endpoint")
    if not endpoint:
        raise RuntimeError("Discovery returned a candidate without an endpoint key.")
    detail = await gateway.call("inspect_endpoint", {"endpoint": endpoint})
    if not isinstance(detail, dict) or detail.get("error"):
        raise RuntimeError(str(detail.get("error", "Could not inspect selected endpoint.")))
    if str(detail.get("method", "")).upper() != "GET":
        raise PermissionError("Agent execution is GET-only.")
    return selected, detail
