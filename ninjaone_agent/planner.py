"""Single-call request understanding and task decomposition."""
from __future__ import annotations
from typing import Any
from .config import PROJECT_ROOT
from .llm import LocalLLM

INSTRUCTION = PROJECT_ROOT / "agents" / "planner.md"
VALID_OPERATIONS = {"count", "list", "list_and_count", "details", "summary"}
VALID_FORMATS = {"count_only", "list", "list_and_count", "summary", "detailed"}

def validate_plan(plan: dict[str, Any], original_question: str) -> dict[str, Any]:
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("Planner returned no tasks.")
    normalized = []
    for index, task in enumerate(tasks[:8], start=1):
        if not isinstance(task, dict):
            continue
        operation = str(task.get("operation", "list")).lower()
        if operation not in VALID_OPERATIONS:
            operation = "list"
        entity = str(task.get("entity", "NinjaOne records")).strip()[:100]
        description = str(task.get("description") or f"{operation} {entity}").strip()[:300]
        filters = task.get("filters", [])
        if isinstance(filters, dict):
            filters = [filters]
        if not isinstance(filters, list):
            filters = []
        clean_filters = []
        for item in filters[:10]:
            if not isinstance(item, dict) or not item.get("field"):
                continue
            operator = str(item.get("operator", "eq")).lower()
            if operator not in {"eq", "ne", "contains", "in", "gt", "gte", "lt", "lte"}:
                continue
            clean_filters.append({"field": str(item["field"])[:100],
                                  "operator": operator, "value": item.get("value")})
        path_params, query = task.get("path_params", {}), task.get("query", {})
        normalized.append({
            "task_id": str(task.get("task_id") or f"task_{index}")[:40],
            "description": description, "entity": entity, "operation": operation,
            "filters": clean_filters, "identifier": task.get("identifier"),
            "path_params": path_params if isinstance(path_params, dict) else {},
            "query": query if isinstance(query, dict) else {},
            "depends_on": task.get("depends_on", []) if isinstance(task.get("depends_on", []), list) else [],
        })
    if not normalized:
        raise ValueError("Planner returned no valid tasks.")
    response_format = str(plan.get("response_format", "summary")).lower()
    if response_format not in VALID_FORMATS:
        response_format = "summary"
    return {"intent": str(plan.get("intent", "ninjaone_query"))[:100],
            "tasks": normalized, "response_format": response_format,
            "original_question": original_question}

async def create_plan(llm: LocalLLM, question: str) -> dict[str, Any]:
    system = INSTRUCTION.read_text(encoding="utf-8")
    raw = await llm.complete_json(system, "Create an execution plan for this request. JSON only:\n\n" + question)
    return validate_plan(raw, question)
