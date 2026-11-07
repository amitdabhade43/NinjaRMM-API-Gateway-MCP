"""Deterministic result extraction, filtering, counting and completeness checks."""
from __future__ import annotations
from typing import Any
from difflib import SequenceMatcher

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
    if field.casefold() in {"name", "username", "fullname", "devicename", "displayname", "systemname", "hostname"} and isinstance(record, dict):
        actual_values = [record.get(key) for key in DEVICE_NAME_FIELDS if record.get(key) not in (None, "")]
        person_name = " ".join(str(record.get(key, "")).strip() for key in ("firstName", "lastName")).strip()
        if person_name:
            actual_values.append(person_name)
        if record.get("email"):
            actual_values.append(record["email"])
    else:
        actual_values = [_get_path(record, field)]

    def matches_one(actual: Any) -> bool:
        if actual is None:
            return False
        if operator == "contains":
            wanted = str(expected).casefold().strip()
            candidate = str(actual).casefold().strip()
            if wanted in candidate:
                return True
            # Tolerate small spelling mistakes in a person's name, but only
            # for short name tokens; do not fuzzy-match IDs or arbitrary fields.
            if field.casefold() in {"name", "username", "fullname"} and len(wanted) >= 4:
                return any(SequenceMatcher(None, wanted, token).ratio() >= 0.80
                           for token in candidate.split())
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


def _payload_data(api_result: dict[str, Any]) -> Any:
    return api_result.get("data", api_result.get("result", api_result))


def is_truncated(api_result: Any) -> bool:
    if not isinstance(api_result, dict):
        return False
    data = _payload_data(api_result)
    return bool(api_result.get("truncated") or api_result.get("_truncated") or
                (isinstance(data, dict) and data.get("_truncated")))


def extract_records(api_result: Any) -> list[Any] | None:
    if isinstance(api_result, list):
        return api_result
    if not isinstance(api_result, dict):
        return None
    data = _payload_data(api_result)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "results", "records", "devices", "users", "organizations"):
            if isinstance(data.get(key), list):
                return data[key]
        arrays = [value for value in data.values() if isinstance(value, list)]
        if len(arrays) == 1:
            return arrays[0]
        if any(key in data for key in ("id", "uid", "displayName", "systemName", "name", "firstName")):
            return [data]
    return None


def process_result(task: dict[str, Any], api_result: Any) -> dict[str, Any]:
    if isinstance(api_result, dict) and api_result.get("error"):
        return {"task": task, "status": "error", "error": api_result["error"], "complete": False}
    records = extract_records(api_result)
    if records is None:
        return {"task": task, "status": "error",
                "error": "The MCP response did not contain a recognizable record collection. No count was reported.",
                "complete": False, "raw_response": api_result}
    filters = task.get("filters", [])
    filtered = [record for record in records if all(_matches(record, condition) for condition in filters)]
    count_field = task.get("count_field")
    source_complete = (bool(api_result.get("complete", True)) and not is_truncated(api_result)
                       if isinstance(api_result, dict) else True)
    # Collapse duplicate rows for the same person, but never merge two
    # distinct people who happen to share a first/last name.
    unique_people: dict[str, Any] = {}
    if count_field:
        for record in filtered:
            if not isinstance(record, dict):
                continue
            email = str(record.get("email") or record.get("emailAddress") or "").casefold().strip()
            user_id = record.get("id", record.get("userId", record.get("uid")))
            full_name = " ".join(str(record.get(key, "")).strip()
                                 for key in ("firstName", "lastName")).casefold().strip()
            identity = f"email:{email}" if email else (
                f"id:{user_id}" if user_id is not None else f"name:{full_name}"
            )
            if identity.strip() not in {"name:", "email:"}:
                if identity not in unique_people:
                    unique_people[identity] = dict(record)
                else:
                    # The API can return repeated rows for one identity.
                    # Merge related-device arrays so no accessible IDs are lost.
                    existing_ids = unique_people[identity].get(count_field)
                    new_ids = record.get(count_field)
                    if isinstance(existing_ids, list) or isinstance(new_ids, list):
                        merged = list(existing_ids) if isinstance(existing_ids, list) else []
                        merged.extend(new_ids if isinstance(new_ids, list) else [])
                        unique_people[identity][count_field] = list(dict.fromkeys(merged))

    # A unique identity is safe to count; two identities with the same search
    # name require clarification. Incomplete source results are never trusted.
    if count_field and (len(unique_people) != 1 or not source_complete):
        return {
            "task": task, "status": "success", "count": None,
            "clarification_required": True, "complete": source_complete,
            "matched_subjects": len(unique_people), "total_records_received": len(records),
            "data": list(unique_people.values())[:20], "endpoint": api_result.get("endpoint"),
        }
    if count_field:
        related_ids = set()
        for record in unique_people.values():
            values = _get_path(record, count_field)
            if isinstance(values, list):
                related_ids.update(str(value) for value in values if value is not None)
        count = len(related_ids)
        filtered = list(unique_people.values())
    else:
        count = len(filtered)
    truncated = is_truncated(api_result)
    complete = api_result.get("complete", True) if isinstance(api_result, dict) else True
    operation = task["operation"]
    result = {
        "task": task, "status": "success", "count": count,
        "matched_subjects": len(filtered) if count_field else None,
        "total_records_received": len(records),
        "complete": bool(complete) and not truncated,
        "truncated": truncated,
        "pages_fetched": api_result.get("pages_fetched") if isinstance(api_result, dict) else None,
        "max_pages_reached": api_result.get("max_pages_reached", False) if isinstance(api_result, dict) else False,
        "endpoint": api_result.get("endpoint") if isinstance(api_result, dict) else None,
    }
    if count_field or operation in {"list", "list_and_count", "details", "summary"}:
        result["data"] = filtered
    return result
