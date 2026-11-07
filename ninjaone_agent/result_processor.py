"""Deterministic result extraction, filtering, counting and completeness checks."""
from __future__ import annotations
from typing import Any

def _get_path(item: Any, path: str) -> Any:
    value = item
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value

def _matches(record: Any, condition: dict[str, Any]) -> bool:
    actual, expected = _get_path(record, str(condition["field"])), condition.get("value")
    operator = condition.get("operator", "eq")
    if operator == "contains":
        return str(expected).casefold() in str(actual).casefold()
    if operator == "startswith":
        return str(actual).casefold().startswith(str(expected).casefold())
    if operator == "in":
        values = expected if isinstance(expected, list) else [expected]
        return any(str(actual).casefold() == str(value).casefold() for value in values)
    if operator in {"gt", "gte", "lt", "lte"}:
        try:
            left, right = float(actual), float(expected)
        except (TypeError, ValueError):
            return False
        return {"gt": left > right, "gte": left >= right,
                "lt": left < right, "lte": left <= right}[operator]
    equal = str(actual).casefold() == str(expected).casefold()
    return not equal if operator == "ne" else equal

def extract_records(api_result: Any) -> list[Any] | None:
    if isinstance(api_result, list):
        return api_result
    if not isinstance(api_result, dict):
        return None
    data = api_result.get("data", api_result)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        arrays = [value for value in data.values() if isinstance(value, list)]
        if len(arrays) == 1:
            return arrays[0]
    return None

def process_result(task: dict[str, Any], api_result: Any) -> dict[str, Any]:
    if isinstance(api_result, dict) and api_result.get("error"):
        return {"task": task, "status": "error", "error": api_result["error"]}
    records = extract_records(api_result)
    if records is None:
        return {"task": task, "status": "success", "data": api_result,
                "complete": api_result.get("complete", True) if isinstance(api_result, dict) else True}
    filtered = [record for record in records
                if all(_matches(record, condition) for condition in task["filters"])]
    operation = task["operation"]
    result = {
        "task": task, "status": "success", "count": len(filtered),
        "total_records_received": len(records),
        "complete": api_result.get("complete", True) if isinstance(api_result, dict) else True,
        "truncated": api_result.get("truncated", False) if isinstance(api_result, dict) else False,
        "endpoint": api_result.get("endpoint") if isinstance(api_result, dict) else None,
    }
    if operation in {"list", "list_and_count", "details", "summary"}:
        result["data"] = filtered
    return result
