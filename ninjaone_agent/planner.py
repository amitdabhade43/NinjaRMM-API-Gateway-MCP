"""Single-call request understanding and task decomposition."""
from __future__ import annotations
import re
from typing import Any
from .config import PROJECT_ROOT
from .llm import LocalLLM

INSTRUCTION = PROJECT_ROOT / "agents" / "planner.md"
VALID_OPERATIONS = {"count", "list", "list_and_count", "details", "summary"}
VALID_FORMATS = {"count_only", "list", "list_and_count", "summary", "detailed"}
_FILTER_INTENT = re.compile(
    r"\b(offline|online|active|inactive|enabled|disabled|open|closed|with|whose|"
    r"starting|starts|beginning|ending|ends|assigned|unassigned|managed|unmanaged|"
    r"failed|warning|critical|healthy|unhealthy|status|technician|end.?user|"
    r"belonging|greater than|less than|older than|newer than)\b", re.I
)


def validate_plan(plan: dict[str, Any], original_question: str) -> dict[str, Any]:
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("Planner returned no tasks.")
    normalized = []
    explicit_filter_intent = bool(_FILTER_INTENT.search(original_question))
    for index, task in enumerate(tasks[:8], start=1):
        if not isinstance(task, dict):
            continue
        operation = str(task.get("operation", "list")).lower()
        if operation not in VALID_OPERATIONS:
            operation = "list"
        entity = str(task.get("entity", "records")).strip()[:100]
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
            if operator not in {"eq", "ne", "contains", "startswith", "in", "gt", "gte", "lt", "lte"}:
                continue
            clean_filters.append({"field": str(item["field"])[:100],
                                  "operator": operator, "value": item.get("value")})
        # "How many X?" means the unfiltered total unless the user states
        # a condition. Do not allow a planner-generated default filter to
        # silently turn an inventory count into a filtered count.
        if operation == "count" and not explicit_filter_intent:
            clean_filters = []
        normalized.append({
            "task_id": str(task.get("task_id") or f"task_{index}")[:40],
            "description": description, "entity": entity, "operation": operation,
            "filters": clean_filters, "identifier": task.get("identifier"),
            "path_params": {}, "query": {},
            "depends_on": task.get("depends_on", []) if isinstance(task.get("depends_on", []), list) else [],
        })
    if not normalized:
        raise ValueError("Planner returned no valid tasks.")
    response_format = str(plan.get("response_format", "summary")).lower()
    if response_format not in VALID_FORMATS:
        response_format = "summary"
    return {"intent": str(plan.get("intent", "mcp_query"))[:100],
            "tasks": normalized, "response_format": response_format,
            "original_question": original_question}


async def create_plan(llm: LocalLLM, question: str) -> dict[str, Any]:
    system = INSTRUCTION.read_text(encoding="utf-8")
    raw = await llm.complete_json(system, "Create an execution plan for this request. JSON only:\n\n" + question)
    return validate_plan(raw, question)
