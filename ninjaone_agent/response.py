"""Fast deterministic answers; OLMo is reserved for complex explanations."""
from __future__ import annotations
import json
from typing import Any
from .llm import LocalLLM

def _compact_record(record: Any) -> str:
    if not isinstance(record, dict):
        return str(record)
    preferred = ("displayName", "systemName", "dnsName", "netbiosName",
                 "name", "firstName", "lastName", "email", "id", "hostname")
    values = [str(record[key]) for key in preferred if record.get(key) not in (None, "")]
    return " — ".join(values[:5]) if values else json.dumps(record, ensure_ascii=False, default=str)

def format_fast(plan: dict[str, Any], results: list[dict[str, Any]]) -> str:
    lines = []
    for result in results:
        task = result["task"]
        if result["status"] != "success":
            lines.append(f"{task['description']}: Could not complete. {result.get('error', 'Unknown error')}")
            continue
        count = result.get("count")
        complete = result.get("complete", True)
        pages = result.get("pages_fetched")
        checked = result.get("total_records_received", 0)
        if count is not None:
            if complete:
                lines.append(f"Found **{count}** matching record(s).")
            else:
                lines.append(
                    f"**Partial result:** Found {count} matching record(s) in {checked} record(s) checked"
                    + (f" across {pages} page(s)." if pages else ".")
                )
                lines.append("The inventory search is incomplete, so this is not a confirmed total.")
            if task["operation"] in {"list", "list_and_count", "details", "summary"}:
                rows = result.get("data", [])
                if rows:
                    lines.append("Matching devices/records:")
                    if task["operation"] == "details":
                        for index, row in enumerate(rows[:25], start=1):
                            lines.append(f"{index}. " + json.dumps(row, ensure_ascii=False, indent=2, default=str))
                    else:
                        lines.extend(f"- {_compact_record(row)}" for row in rows[:100])
                elif complete:
                    lines.append("No matching records were found.")
                else:
                    lines.append("No matches were found in the records checked; other records may still match.")
        else:
            lines.append(task["description"] + ":")
            lines.append(json.dumps(result.get("data"), ensure_ascii=False, indent=2, default=str)[:12000])
            if not complete:
                lines.append("Warning: this response is incomplete; do not treat it as a complete inventory result.")
        if result.get("truncated"):
            lines.append("The Gateway truncated this response before all records could be retrieved.")
        if result.get("max_pages_reached"):
            lines.append("The configured page limit was reached. Increase NINJA_AGENT_MAX_PAGES or narrow the search.")
    return "\n".join(lines) if lines else "No results were returned."

async def format_response(llm: LocalLLM, plan: dict[str, Any],
                          results: list[dict[str, Any]]) -> str:
    if all(r.get("status") == "success" for r in results):
        return format_fast(plan, results)
    system = (
        "You are the response specialist for a read-only NinjaOne administration agent. "
        "Use only supplied tool results. Never invent records, counts, endpoint results or completeness. "
        "Clearly distinguish complete results from partial results. Explain errors in plain language. "
        "Be concise and answer the exact question."
    )
    user = ("USER QUESTION:\n" + plan["original_question"] +
            "\n\nVERIFIED RESULTS:\n" + json.dumps(results, ensure_ascii=False, default=str)[:24000])
    try:
        return await llm.complete(system, user, temperature=0.1)
    except Exception:
        return format_fast(plan, results)
