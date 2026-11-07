"""Deterministic result extraction, filtering, counting and completeness checks."""
from __future__ import annotations
from typing import Any

DEVICE_NAME_FIELDS = ("displayName", "systemName", "dnsName", "netbiosName", "name", "hostname")

def _get_path(item: Any, path: str) -> Any:
    value = item
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value

def _matches(record: Any, condition: dict[str, Any]) -> bool:
    field = str(condition["field"])
    expected = condition.get("value")
    operator = condition.get("operator", "eq")
    if field.casefold() in {"name", "devicename", "displayname", "systemname", "hostname"} and isinstance(record, dict):
        actual_values = [record.get(key) for key in DEVICE_NAME_FIELDS if record.get(key) not in (None, "")]
    else:
        actual_values = [_get_path(record, field)]
    def matches_one(actual: Any) -> bool:
        if actual is None:
            return False
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
    return any(matches_one(actual) for actual in actual_values)

def extract_records(api_result: Any) -> list[Any] | None:
    if isinstance(api_result, list):
        return api_result
    if not isinstance(api_result, dict):
        return None
    data = api_result.get("data", api_result)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # Gateway truncation wrapper: {"items": [...], "_truncated": true, ...}
        if isinstance(data.get("items"), list):
            return data["items"]
        arrays = [value for value in data.values() if isinstance(value, list)]
        if len(arrays) == 1:
            return arrays[0]
    return None

def process_result(task: dict[str, Any], api_result: Any) -> dict[str, Any]:
    if isinstance(api_result, dict) and api_result.get("error"):
        return {"task": task, "status": "error", "error": api_result["error"],
                "complete": False}
    records = extract_records(api_result)
    if records is None:
        return {"task": task, "status": "success", "data": api_result,
                "complete": api_result.get("complete", True) if isinstance(api_result, dict) else True}
    filters = task.get("filters", [])
    filtered = [record for record in records
                if all(_matches(record, condition) for condition in filters)]
    complete = api_result.get("complete", True) if isinstance(api_result, dict) else True
    truncated = api_result.get("truncated", False) if isinstance(api_result, dict) else False
    operation = task["operation"]
    result = {
        "task": task, "status": "success", "count": len(filtered),
        "total_records_received": len(records),
        "complete": bool(complete) and not bool(truncated),
        "truncated": bool(truncated),
        "pages_fetched": api_result.get("pages_fetched") if isinstance(api_result, dict) else None,
        "max_pages_reached": api_result.get("max_pages_reached", False) if isinstance(api_result, dict) else False,
        "endpoint": api_result.get("endpoint") if isinstance(api_result, dict) else None,
    }
    if operation in {"list", "list_and_count", "details", "summary"}:
        result["data"] = filtered
    return result
