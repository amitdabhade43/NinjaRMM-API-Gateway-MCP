"""Optional local-LLM semantic endpoint ranking with strict candidate grounding."""
from __future__ import annotations
import copy
import hashlib
import json
import os
import time
from typing import Any
import httpx
from .spec import Endpoint

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CLIENTS: dict[tuple[str, float], httpx.AsyncClient] = {}


def _cache_ttl() -> float:
    try:
        return max(0.0, float(os.getenv("NINJA_MCP_SEMANTIC_CACHE_TTL", "60")))
    except ValueError:
        return 60.0


def _http_client(base_url: str, timeout: float) -> httpx.AsyncClient:
    key = (base_url, timeout)
    client = _CLIENTS.get(key)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(timeout=timeout)
        _CLIENTS[key] = client
    return client


async def close_semantic_clients() -> None:
    clients = list(_CLIENTS.values())
    _CLIENTS.clear()
    for client in clients:
        if not client.is_closed:
            await client.aclose()


async def _semantic_rank_uncached(intent: str, candidates: list[Endpoint]) -> dict[str, Any]:
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
    started = time.perf_counter()
    client = _http_client(base_url, timeout)
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
            "rejected_unmatched_candidates": max(0, len(parsed.get("selected", [])) - len(selected)),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1)}


async def semantic_rank(intent: str, candidates: list[Endpoint]) -> dict[str, Any]:
    """Cache exact semantic selections and reuse HTTP keep-alive connections."""
    base_url = os.getenv("NINJA_MCP_LLM_BASE_URL", "").rstrip("/")
    model = os.getenv("NINJA_MCP_LLM_MODEL", "")
    if not base_url or not model:
        return await _semantic_rank_uncached(intent, candidates)

    material = json.dumps(
        [base_url, model, intent.strip().casefold(), [endpoint.key for endpoint in candidates]],
        ensure_ascii=False, separators=(",", ":"),
    )
    cache_key = hashlib.sha256(material.encode("utf-8")).hexdigest()
    now = time.monotonic()
    ttl = _cache_ttl()
    cached = _CACHE.get(cache_key)
    if cached and ttl > 0 and now - cached[0] < ttl:
        cached_result = copy.deepcopy(cached[1])
        cached_result["cache_hit"] = True
        cached_result["elapsed_ms"] = 0.0
        return cached_result

    result = await _semantic_rank_uncached(intent, candidates)
    if result.get("mode") == "local_semantic":
        result["cache_hit"] = False
    if result.get("mode") == "local_semantic" and ttl > 0:
        if len(_CACHE) >= 256:
            oldest = min(_CACHE, key=lambda key: _CACHE[key][0])
            _CACHE.pop(oldest, None)
        _CACHE[cache_key] = (time.monotonic(), copy.deepcopy(result))
    return result
