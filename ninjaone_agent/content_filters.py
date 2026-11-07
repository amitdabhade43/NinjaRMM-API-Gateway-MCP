"""Generic, deterministic filtering for structured MCP results.

The LLM translates natural language into canonical filter objects. This module
applies those filters to returned records so matching does not depend on the
model scanning or remembering every item in a large response.
"""
from __future__ import annotations

import copy
import re
from typing import Any

_KEY_NORMALIZER = re.compile(r"[^a-z0-9]+")

_OPERATOR_ALIASES = {
    "eq": "equals", "equal": "equals", "is": "equals", "exact": "equals",
    "exactly": "equals", "matches": "equals", "match": "equals",
    "ne": "not_equals", "neq": "not_equals", "is_not": "not_equals",
    "does_not_equal": "not_equals", "not_equal": "not_equals", "not_equal_to": "not_equals",
    "includes": "contains", "include": "contains", "has": "contains",
    "having": "contains", "containing": "contains", "matches_text": "contains",
    "not_contains": "not_contains", "does_not_contain": "not_contains", "not_contain": "not_contains",
    "excludes": "not_contains", "without": "not_contains",
    "prefix": "starts_with", "begins": "starts_with",
    "begin_with": "starts_with", "begins_with": "starts_with",
    "start_with": "starts_with", "starts": "starts_with",
    "suffix": "ends_with", "end_with": "ends_with", "ends": "ends_with",
    "greater": "greater_than", "gt": "greater_than", "above": "greater_than",
    "less": "less_than", "lt": "less_than", "below": "less_than",
    "gte": "greater_than_or_equal", "at_least": "greater_than_or_equal",
    "lte": "less_than_or_equal", "at_most": "less_than_or_equal",
    "empty": "is_empty", "blank": "is_empty",
    "not_empty": "is_not_empty", "not_blank": "is_not_empty",
}

_SUPPORTED_OPERATORS = {
    "equals", "not_equals", "contains", "not_contains", "starts_with",
    "ends_with", "in", "not_in", "greater_than", "greater_than_or_equal",
    "less_than", "less_than_or_equal", "is_empty", "is_not_empty",
}


def normalize_operator(operator: Any) -> str:
    """Normalize common wording variants to a supported filter operator."""
    value = str(operator or "").strip().casefold().replace("-", "_").replace(" ", "_")
    value = _OPERATOR_ALIASES.get(value, value)
    if value not in _SUPPORTED_OPERATORS:
        raise ValueError(f"Unsupported filter operator: {operator!r}")
    return value


def _normal_key(value: str) -> str:
    return _KEY_NORMALIZER.sub("", value.casefold())


def _get_field(record: Any, field: str) -> Any:
    """Resolve dotted paths and case/underscore-insensitive object keys."""
    current = record
    for part in field.split("."):
        if not isinstance(current, dict):
            return None
        if part in current:
            current = current[part]
            continue
        wanted = _normal_key(part)
        match = next((key for key in current if isinstance(key, str)
                      and _normal_key(key) == wanted), None)
        if match is None:
            return None
        current = current[match]
    return current


def _text(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return str(value).casefold()
    return str(value).casefold()


def _compare(actual: Any, operator: str, expected: Any) -> bool:
    if operator == "is_empty":
        return actual is None or actual == "" or actual == [] or actual == {}
    if operator == "is_not_empty":
        return not _compare(actual, "is_empty", None)
    if actual is None:
        return operator in {"not_equals", "not_contains", "not_in"} and expected is not None

    if operator in {"equals", "not_equals"}:
        if isinstance(actual, str) or isinstance(expected, str):
            equal = _text(actual) == _text(expected)
        else:
            equal = actual == expected
        return equal if operator == "equals" else not equal

    if operator in {"contains", "not_contains", "starts_with", "ends_with"}:
        left, right = _text(actual), _text(expected)
        matched = {
            "contains": lambda: right in left,
            "not_contains": lambda: right not in left,
            "starts_with": lambda: left.startswith(right),
            "ends_with": lambda: left.endswith(right),
        }[operator]()
        return matched

    if operator in {"in", "not_in"}:
        values = expected if isinstance(expected, list) else [expected]
        matched = any(_compare(actual, "equals", value) for value in values)
        return matched if operator == "in" else not matched

    try:
        left = float(actual)
        right = float(expected)
    except (TypeError, ValueError):
        left, right = _text(actual), _text(expected)

    if operator == "greater_than":
        return left > right
    if operator == "greater_than_or_equal":
        return left >= right
    if operator == "less_than":
        return left < right
    if operator == "less_than_or_equal":
        return left <= right
    return False


def record_matches(record: dict[str, Any], filters: list[dict[str, Any]]) -> bool:
    """All supplied filters are combined with AND semantics."""
    for item in filters:
        if not isinstance(item, dict):
            raise ValueError("Each filter must be an object.")
        field = item.get("field")
        if not isinstance(field, str) or not field.strip():
            raise ValueError("Each filter requires a non-empty field.")
        operator = normalize_operator(item.get("operator"))
        if operator not in {"is_empty", "is_not_empty"} and "value" not in item:
            raise ValueError(f"Filter {field!r} requires a value.")
        if not _compare(_get_field(record, field), operator, item.get("value")):
            return False
    return True


def _record_arrays(value: Any, path: tuple[str, ...] = ()):
    """Yield arrays of objects, preferring common record-container names."""
    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            yield path, value
        for index, item in enumerate(value):
            yield from _record_arrays(item, path + (str(index),))
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _record_arrays(item, path + (str(key),))


def _path_priority(path: tuple[str, ...]) -> int:
    preferred = {"data", "items", "results", "records", "devices", "organizations", "users"}
    return sum(2 for part in path if part.casefold() in preferred)


def _replace_path(value: Any, path: tuple[str, ...], replacement: list[dict[str, Any]]) -> Any:
    if not path:
        return replacement
    result = copy.deepcopy(value)
    current = result
    for part in path[:-1]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    last = path[-1]
    if isinstance(current, list):
        current[int(last)] = replacement
    else:
        current[last] = replacement
    return result


def filter_result_payload(payload: Any, filters: list[dict[str, Any]]) -> tuple[Any, dict[str, int]]:
    """Filter the most likely record collection and return match/completeness counts."""
    if not filters:
        return payload, {"examined": 0, "matched": 0}
    candidates = list(_record_arrays(payload))
    if isinstance(payload, list) and payload and all(isinstance(x, dict) for x in payload):
        candidates.append(((), payload))
    if not candidates:
        raise ValueError("The MCP result did not contain a record collection to filter.")
    path, records = max(candidates, key=lambda item: (len(item[1]), _path_priority(item[0])))
    matches = [record for record in records if record_matches(record, filters)]
    return _replace_path(payload, path, matches), {
        "examined": len(records),
        "matched": len(matches),
    }
