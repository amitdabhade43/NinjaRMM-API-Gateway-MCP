"""Schema-aware, read-only execution of planned tasks."""
from __future__ import annotations
import asyncio
import re
from typing import Any, Callable
from .config import AgentConfig
from .discovery import discover_for_task
from .mcp_gateway import GatewayConnection
from .result_processor import process_result

def _schema_parameter_names(detail: dict[str, Any], location: str) -> set[str]:
    return {str(p.get("name")) for p in detail.get("parameters", [])
            if isinstance(p, dict) and p.get("in") == location}

def _validate_parameters(task: dict[str, Any], detail: dict[str, Any]) -> tuple[dict, dict]:
    path_params, query = dict(task.get("path_params") or {}), dict(task.get("query") or {})
    path_names, query_names = _schema_parameter_names(detail, "path"), _schema_parameter_names(detail, "query")
    template_names = set(re.findall(r"{([^}]+)}", str(detail.get("path", ""))))
    missing = template_names - path_params.keys()
    identifier = task.get("identifier")
    if missing and identifier is not None and len(missing) == 1:
        path_params[next(iter(missing))] = identifier
    missing = template_names - path_params.keys()
    if missing:
        raise ValueError("Missing required path value(s): " + ", ".join(sorted(missing)))
    if set(path_params) - path_names:
        raise ValueError("Planner supplied path parameters not declared by the OpenAPI schema.")
    if set(query) - query_names:
        raise ValueError("Planner supplied query parameters not declared by the OpenAPI schema.")
    for parameter in detail.get("parameters", []):
        if not isinstance(parameter, dict) or not parameter.get("required"):
            continue
        if parameter.get("in") == "query" and parameter.get("name") not in query:
            raise ValueError(f"Missing required query parameter: {parameter.get('name')}")
    return path_params, query

def _pagination_pair(detail: dict[str, Any]) -> tuple[str, str] | None:
    names = _schema_parameter_names(detail, "query")
    page = next((name for name in ("page", "pageNumber", "page_number") if name in names), None)
    size = next((name for name in ("pageSize", "page_size", "limit") if name in names), None)
    return (page, size) if page and size and page != size else None

async def execute_task(gateway: GatewayConnection, config: AgentConfig,
                       task: dict[str, Any]) -> dict[str, Any]:
    try:
        candidate, detail = await discover_for_task(gateway, config, task)
        path_params, query = _validate_parameters(task, detail)
        endpoint, operation = candidate["endpoint"], task["operation"]
        pagination = _pagination_pair(detail)
        if pagination and operation in {"count", "list", "list_and_count"}:
            raw = await gateway.call("execute_paginated_endpoint", {
                "endpoint": endpoint, "path_params": path_params or None,
                "query": query or None, "page_parameter": pagination[0],
                "page_size_parameter": pagination[1], "page_size": config.page_size,
                "start_page": 1, "max_pages": config.max_pages,
            })
        else:
            raw = await gateway.call("execute_endpoint", {
                "endpoint": endpoint, "path_params": path_params or None,
                "query": query or None,
            })
        return process_result(task, raw)
    except Exception as exc:
        return {"task": task, "status": "error", "error": str(exc)}

async def execute_plan(gateway: GatewayConnection, config: AgentConfig,
                       plan: dict[str, Any],
                       on_task_complete: Callable[[dict[str, Any]], None] | None = None
                       ) -> list[dict[str, Any]]:
    tasks = plan["tasks"]

    async def run_one(task: dict[str, Any]):
        result = await execute_task(gateway, config, task)
        if on_task_complete:
            on_task_complete(result)
        return task["task_id"], result

    if any(task.get("depends_on") for task in tasks):
        completed: dict[str, dict[str, Any]] = {}
        pending = list(tasks)
        while pending:
            ready = [task for task in pending if all(dep in completed for dep in task["depends_on"])]
            if not ready:
                raise RuntimeError("Task plan contains an unresolved dependency or cycle.")
            pairs = await asyncio.gather(*(run_one(task) for task in ready))
            for task_id, result in pairs:
                completed[task_id] = result
            pending = [task for task in pending if task["task_id"] not in completed]
        return [completed[task["task_id"]] for task in tasks]

    running = [asyncio.create_task(run_one(task)) for task in tasks]
    completed_results = {}
    for future in asyncio.as_completed(running):
        task_id, result = await future
        completed_results[task_id] = result
    return [completed_results[task["task_id"]] for task in tasks]
