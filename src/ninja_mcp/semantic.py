"""Optional local-LLM semantic endpoint ranking with strict candidate grounding."""
from __future__ import annotations
import json
import os
from typing import Any
import httpx
from .spec import Endpoint

async def semantic_rank(intent: str, candidates: list[Endpoint]) -> dict[str, Any]:
    base_url = os.getenv("NINJA_MCP_LLM_BASE_URL", "").rstrip("/")
    model = os.getenv("NINJA_MCP_LLM_MODEL", "")
    if not base_url or not model:
        return {"mode": "fuzzy_fallback", "warning": "Set NINJA_MCP_LLM_BASE_URL and NINJA_MCP_LLM_MODEL to enable local semantic ranking.",
                "selected": [e.key for e in candidates[:5]]}
    allowed = {e.key: e for e in candidates}
    compact = [{"endpoint": e.key, "summary": e.summary, "description": e.description[:500],
                "category": e.category, "parameters": [
                    {"name": p.get("name"), "in": p.get("in"), "required": p.get("required", False)}
                    for p in e.parameters if isinstance(p, dict)]} for e in candidates]
    prompt = ("Select only endpoint keys from the supplied candidates that can fulfill the user's intent. "
              "Return JSON only: {\"selected\":[{\"endpoint\":\"METHOD /path\",\"purpose\":\"...\","
              "\"sequence\":1}],\"clarification_needed\":false,\"reason\":\"...\"}. "
              "Never invent endpoints or parameters. Multiple endpoints are allowed only for a genuine multi-step task.\n"
              f"USER INTENT: {intent}\nCANDIDATES: {json.dumps(compact, ensure_ascii=False)}")
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("NINJA_MCP_LLM_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    timeout = float(os.getenv("NINJA_MCP_LLM_TIMEOUT", "20"))
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(f"{base_url}/chat/completions", headers=headers,
                                     json={"model": model, "temperature": 0,
                                           "response_format": {"type": "json_object"},
                                           "messages": [{"role": "system", "content": "You are a strict API endpoint selector."},
                                                        {"role": "user", "content": prompt}]})
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    selected = []
    for item in parsed.get("selected", []):
        key = item.get("endpoint") if isinstance(item, dict) else item
        if key in allowed:
            selected.append({**item, "endpoint": key} if isinstance(item, dict) else {"endpoint": key})
    return {"mode": "local_semantic", "selected": selected,
            "clarification_needed": bool(parsed.get("clarification_needed", False)),
            "reason": str(parsed.get("reason", ""))[:1000],
            "rejected_unmatched_candidates": max(0, len(parsed.get("selected", [])) - len(selected))}
