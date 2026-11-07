"""Ground task intent in actual Gateway/OpenAPI operations."""
from __future__ import annotations
import re
from typing import Any
from .config import AgentConfig
from .mcp_gateway import GatewayConnection


def _candidate_path(candidate: dict[str, Any]) -> str:
    path = candidate.get("path")
    if not path:
        endpoint = str(candidate.get("endpoint", ""))
        path = re.sub(r"^\\s*GET\\s+", "", endpoint, flags=re.I)
    return str(path).rstrip("/")


def _has_path_parameters(candidate: dict[str, Any]) -> bool:
    return bool(re.search(r"{[^}]+}", _candidate_path(candidate)))


def _is_device_collection(candidate: dict[str, Any], operation: str) -> bool:
    path = _candidate_path(candidate).casefold()
    allowed = ("/devices-detailed",) if operation == "details" else ("/devices",)
    return any(path.endswith(suffix) for suffix in allowed)


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
        raise RuntimeError("No collection GET endpoint was discovered; an item-detail endpoint cannot answer an unscoped request.")

    entity = str(task.get("entity", "")).casefold()
    if "device" in entity:
        # Never execute an unrelated semantic match (e.g. organization documents)
        # for a device inventory request.
        exact = [item for item in collection_pool if _is_device_collection(item, task.get("operation", "list"))]
        if exact:
            return exact[0]
        raise RuntimeError("Gateway discovery did not return the NinjaOne device collection endpoint. No unrelated endpoint was called.")

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
    semantic = result.get("semantic", {}) if isinstance(result, dict) else {}

    # Discovery is semantic and may rank an unrelated collection first. Retry
    # with a direct entity-oriented query before deciding no safe route exists.
    if "device" in str(task.get("entity", "")).casefold() and not any(
        _is_device_collection(item, task.get("operation", "list")) for item in candidates
    ):
        retry = await gateway.call("discover_endpoints", {
            "intent": "NinjaOne devices device inventory list all devices collection GET endpoint",
            "method": "GET", "candidate_limit": max(config.max_candidates, 50),
        })
        retry_candidates = retry.get("candidates", []) if isinstance(retry, dict) else []
        known = {item.get("endpoint") for item in candidates}
        candidates.extend(item for item in retry_candidates if item.get("endpoint") not in known)

    if not candidates:
        raise RuntimeError(f"No GET endpoint found for task: {task['description']}")
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
