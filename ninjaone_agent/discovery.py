"""Ground task intent in actual Gateway/OpenAPI operations."""
from __future__ import annotations
from typing import Any
from .config import AgentConfig
from .mcp_gateway import GatewayConnection

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
    selected_items = semantic.get("selected", []) if isinstance(semantic, dict) else []
    selected_keys = [
        item.get("endpoint") if isinstance(item, dict) else item
        for item in selected_items
    ]
    selected = next((item for key in selected_keys for item in candidates
                     if item.get("endpoint") == key), candidates[0])
    endpoint = selected.get("endpoint")
    if not endpoint:
        raise RuntimeError("Discovery returned a candidate without an endpoint key.")
    detail = await gateway.call("inspect_endpoint", {"endpoint": endpoint})
    if not isinstance(detail, dict) or detail.get("error"):
        raise RuntimeError(str(detail.get("error", "Could not inspect selected endpoint.")))
    if str(detail.get("method", "")).upper() != "GET":
        raise PermissionError("Agent execution is GET-only.")
    return selected, detail
