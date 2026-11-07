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
    wants_item = task.get("identifier") is not None

    if wants_item:
        item_pool = [item for item in candidates if _has_path_parameters(item)]
        preferred = [item for item in selected_pool if _has_path_parameters(item)]
        pool = preferred or item_pool
        if pool:
            return pool[0]
        raise RuntimeError("No item GET endpoint was discovered for the supplied identifier.")

    collection_pool = [item for item in candidates if not _has_path_parameters(item)]
    if not collection_pool:
        raise RuntimeError(
            "No collection GET endpoint was discovered. No device ID was supplied, so an item-detail endpoint cannot be used."
        )

    entity = str(task.get("entity", "")).casefold()
    has_name_prefix = any(
        f.get("field", "").casefold() in {"name", "displayname", "systemname", "hostname"}
        and f.get("operator") == "startswith"
        for f in task.get("filters", [])
    )
    if "device" in entity:
        # Prefix matching is performed locally against the documented device-name
        # fields. Do not choose /devices/search and treat its broad q search as
        # an exact starts-with filter.
        preferred_path = "/devices-detailed" if task.get("operation") == "details" else "/devices"
        exact = [item for item in collection_pool
                 if str(item.get("path", item.get("endpoint", ""))).rstrip("/").endswith(preferred_path)]
        if exact:
            return exact[0]

    preferred = [item for item in selected_pool if not _has_path_parameters(item)]
    if preferred:
        return preferred[0]
    return collection_pool[0]


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
