"""Schema-aware, read-only execution of planned tasks."""
from __future__ import annotations
import asyncio
import re
from typing import Any, Callable
from .config import AgentConfig
from .discovery import discover_for_task
from .mcp_gateway import GatewayConnection
from .result_processor import extract_records, is_truncated, process_result


def _schema_parameter_names(detail: dict[str, Any], location: str) -> set[str]:
    return {str(p.get("name")) for p in detail.get("parameters", [])
            if isinstance(p, dict) and p.get("in") == location}


def _validate_parameters(task: dict[str, Any], detail: dict[str, Any]) -> tuple[dict, dict]:
    path_params, query = {}, dict(task.get("query") or {})
    path_names, query_names = _schema_parameter_names(detail, "path"), _schema_parameter_names(detail, "query")
    template_names = set(re.findall(r"{([^}]+)}", str(detail.get("path", ""))))
    identifier = task.get("identifier")
    if identifier is not None and len(template_names) == 1:
        path_params[next(iter(template_names))] = identifier
    missing = template_names - path_params.keys()
    if missing:
        raise ValueError("This endpoint requires a record ID. No ID was supplied.")
    if set(path_params) - path_names:
        raise ValueError("The selected endpoint's path parameters do not match its OpenAPI schema.")
    if set(query) - query_names:
        raise ValueError("The planner suggested an unsupported API query parameter. The request was stopped safely.")
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


def _cursor_pagination(detail: dict[str, Any]) -> tuple[str, str] | None:
    """Recognize NinjaOne's documented device cursor parameters from the inspected schema.

    The old implementation depended on exact wording in the OpenAPI description.
    Description wording is not a reliable machine-readable contract; parameter
    names and their declared query location are the stable schema identifiers.
    """
    parameters = [p for p in detail.get("parameters", [])
                  if isinstance(p, dict) and p.get("in") == "query"]
    by_name = {str(p.get("name", "")).casefold(): str(p.get("name", ""))
               for p in parameters}
    after_name, size_name = by_name.get("after"), by_name.get("pagesize")
    if after_name and size_name:
        return after_name, size_name
    return None


async def _execute_cursor_pages(gateway: GatewayConnection, config: AgentConfig,
                                endpoint: str, path_params: dict,
                                base_query: dict, cursor_names: tuple[str, str]) -> dict[str, Any]:
    after_name, size_name = cursor_names
    # NinjaOne device inventory uses an ID cursor and a maximum page size of 50.
    page_size = min(config.page_size, 50)
    cursor = None
    seen_cursors: set[str] = set()
    collected: list[Any] = []
    pages = 0
    complete = False
    gateway_truncated = False
    for _ in range(config.max_pages):
        query = {k: v for k, v in base_query.items() if k not in {after_name, size_name}}
        query[size_name] = page_size
        if cursor is not None:
            query[after_name] = cursor
        raw = await gateway.call("execute_endpoint", {
            "endpoint": endpoint, "path_params": path_params or None, "query": query or None,
        })
        if isinstance(raw, dict) and raw.get("error"):
            return {"error": raw["error"], "complete": False,
                    "pages_fetched": pages, "items_fetched": len(collected)}
        records = extract_records(raw)
        if records is None:
            return {"error": "The MCP response did not contain a readable record array.",
                    "complete": False, "pages_fetched": pages,
                    "items_fetched": len(collected), "raw_response": raw}
        pages += 1
        collected.extend(records)
        page_truncated = is_truncated(raw)
        gateway_truncated = gateway_truncated or page_truncated

        # A short, non-truncated page (including an empty page after an exact
        # multiple of 50) is the API's completion signal.
        if len(records) < page_size:
            complete = not page_truncated
            break
        if not records or not isinstance(records[-1], dict) or records[-1].get("id") is None:
            break
        next_cursor = records[-1]["id"]
        cursor_key = str(next_cursor)
        if cursor_key in seen_cursors:
            break
        seen_cursors.add(cursor_key)
        cursor = next_cursor

    return {
        "endpoint": endpoint, "data": collected,
        "complete": complete, "truncated": gateway_truncated and not complete,
        "pages_fetched": pages, "items_fetched": len(collected),
        "max_pages_reached": not complete and pages >= config.max_pages,
    }


async def execute_task(gateway: GatewayConnection, config: AgentConfig,
                       task: dict[str, Any]) -> dict[str, Any]:
    try:
        candidate, detail = await discover_for_task(gateway, config, task)
        path_params, query = _validate_parameters(task, detail)
        endpoint, operation = candidate["endpoint"], task["operation"]
        if operation in {"count", "list", "list_and_count", "details", "summary"}:
            cursor_pagination = _cursor_pagination(detail)
            if cursor_pagination:
                raw = await _execute_cursor_pages(gateway, config, endpoint, path_params, query, cursor_pagination)
                return process_result(task, raw)
            pagination = _pagination_pair(detail)
            if pagination and operation in {"count", "list", "list_and_count"}:
                raw = await gateway.call("execute_paginated_endpoint", {
                    "endpoint": endpoint, "path_params": path_params or None,
                    "query": query or None, "page_parameter": pagination[0],
                    "page_size_parameter": pagination[1], "page_size": config.page_size,
                    "start_page": 1, "max_pages": min(config.max_pages, 20),
                })
            else:
                raw = await gateway.call("execute_endpoint", {
                    "endpoint": endpoint, "path_params": path_params or None, "query": query or None,
                })
        else:
            raw = await gateway.call("execute_endpoint", {
                "endpoint": endpoint, "path_params": path_params or None, "query": query or None,
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
