"""Ground task intent in actual Gateway/OpenAPI operations."""
from __future__ import annotations
import re
from typing import Any
from .config import AgentConfig
from .mcp_gateway import GatewayConnection


def _has_path_parameters(candidate: dict[str, Any]) -> bool:
    path = str(candidate.get("path", candidate.get("endpoint", "")))
    return bool(re.search(r"{[^}]+}", path))


def choose_candidate(candidates: list[dict[str, Any]], semantic: dict[str, Any],
                     task: dict[str, Any]) -> dict[str, Any]:
    selected_items = semantic.get("selected", []) if isinstance(semantic, dict) else []
    selected_keys = [item.get("endpoint") if isinstance(item, dict) else item
                     for item in selected_items]
    selected_pool = [item for key in selected_keys for item in candidates
                     if item.get("endpoint") == key]
    mode = semantic.get("mode") if isinstance(semantic, dict) else None
    wants_item = task.get("identifier") is not None

    # An item route is valid only when the user supplied an identifier.
    # For name/status searches, always choose a collection route, even when
    # semantic discovery ranks an /{id} route first.
    if wants_item:
        item_pool = [item for item in candidates if _has_path_parameters(item)]
        preferred = [item for item in selected_pool if _has_path_parameters(item)]
        pool = preferred or item_pool
        if pool:
            return pool[0]
        raise RuntimeError("No item GET endpoint was discovered for the supplied identifier.")

    collection_pool = [item for item in candidates if not _has_path_parameters(item)]
    preferred = [item for item in selected_pool if not _has_path_parameters(item)]
    pool = preferred or collection_pool
    if pool:
        return pool[0]
    raise RuntimeError(
        "No unscoped collection GET endpoint was discovered. "
        "Refusing to call an item endpoint because this request has no device ID."
    )


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
