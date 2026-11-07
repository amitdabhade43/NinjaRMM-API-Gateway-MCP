"""Fast deterministic answers; OLMo is reserved for complex explanations."""
from __future__ import annotations
import json
from typing import Any
from .llm import LocalLLM

def _compact_record(record: Any) -> str:
    if not isinstance(record, dict):
        return str(record)
    preferred = ("name", "firstName", "lastName", "email", "id", "hostname", "displayName")
    values = [str(record[key]) for key in preferred if record.get(key) not in (None, "")]
    return " — ".join(values[:4]) if values else json.dumps(record, ensure_ascii=False, default=str)

def format_fast(plan: dict[str, Any], results: list[dict[str, Any]]) -> str:
    lines = []
    for result in results:
        task = result["task"]
        if result["status"] != "success":
            lines.append(f"{task['description']}: Unable to complete — {result['error']}")
            continue
        if "count" in result:
            lines.append(f"{task['description']}: **{result['count']}**")
            if task["operation"] in {"list", "list_and_count", "details", "summary"}:
                lines.extend(f"- {_compact_record(row)}" for row in result.get("data", [])[:100])
        else:
            lines.append(task["description"] + ":")
            lines.append(json.dumps(result.get("data"), ensure_ascii=False, indent=2, default=str)[:12000])
        if result.get("complete") is False or result.get("truncated"):
            lines.append("Warning: Gateway marked this result incomplete; the count/list may not cover all records.")
    return "\n".join(lines) if lines else "No results were returned."

async def format_response(llm: LocalLLM, plan: dict[str, Any],
                          results: list[dict[str, Any]]) -> str:
    if all(r.get("status") == "success" for r in results) and plan["response_format"] != "detailed":
        return format_fast(plan, results)
    system = (
        "You are the response specialist for a read-only NinjaOne administration agent. "
        "Use only supplied tool results. Never invent records, counts, endpoint results or completeness. "
        "Clearly report errors and incomplete data. Be concise and answer the exact question."
    )
    user = ("USER QUESTION:\n" + plan["original_question"] +
            "\n\nVERIFIED RESULTS:\n" + json.dumps(results, ensure_ascii=False, default=str)[:24000])
    try:
        return await llm.complete(system, user, temperature=0.1)
    except Exception:
        return format_fast(plan, results)
