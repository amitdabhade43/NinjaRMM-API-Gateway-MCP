from unittest.mock import AsyncMock

import pytest

from ninja_mcp import semantic
from ninja_mcp.search import search
from ninja_mcp.spec import Endpoint, Spec

def ep(method,path,summary,category="Users"):
    return Endpoint(method,path,None,summary,"",category,[category])

def test_fuzzy_search_prefers_matching_operation_summary():
    spec=Spec([
        ep("GET","/v2/users","Get all users"),
        ep("GET","/v2/organizations","Get all organizations"),
        ep("GET","/v2/users/{id}/devices","List devices accessible by user"),
    ])
    results=search(spec,"devices accessible by user",limit=3)
    assert results[0].path=="/v2/users/{id}/devices"

def test_delete_is_not_part_of_discovery_index():
    # Spec loader filters DELETE; search only ranks the already-filtered index.
    spec=Spec([ep("GET","/v2/users","Get users")])
    assert all(item.method!="DELETE" for item in search(spec,"users",limit=10))


@pytest.mark.asyncio
async def test_semantic_rank_reuses_cached_selection(monkeypatch):
    monkeypatch.setenv("NINJA_MCP_LLM_BASE_URL", "http://127.0.0.1:50000/v1")
    monkeypatch.setenv("NINJA_MCP_LLM_MODEL", "local-model")
    monkeypatch.setenv("NINJA_MCP_SEMANTIC_CACHE_TTL", "60")
    semantic._CACHE.clear()
    endpoint = ep("GET", "/v2/devices", "List devices", "Devices")
    expected = {"mode": "local_semantic", "selected": [{"endpoint": "GET /v2/devices"}]}
    uncached = AsyncMock(return_value=expected)
    monkeypatch.setattr(semantic, "_semantic_rank_uncached", uncached)

    first = await semantic.semantic_rank("list devices", [endpoint])
    second = await semantic.semantic_rank("list devices", [endpoint])

    assert first["selected"] == expected["selected"]
    assert first["cache_hit"] is False
    assert second["selected"] == expected["selected"]
    assert second["cache_hit"] is True
    assert second["elapsed_ms"] == 0.0
    assert uncached.await_count == 1


@pytest.mark.asyncio
async def test_semantic_failure_is_cached_briefly(monkeypatch):
    monkeypatch.setenv("NINJA_MCP_LLM_BASE_URL", "http://127.0.0.1:50000/v1")
    monkeypatch.setenv("NINJA_MCP_LLM_MODEL", "local-model")
    monkeypatch.setenv("NINJA_MCP_SEMANTIC_FAILURE_CACHE_TTL", "8")
    semantic._CACHE.clear()
    endpoint = ep("GET", "/v2/devices", "List devices", "Devices")
    uncached = AsyncMock(side_effect=TimeoutError("local model timed out"))
    monkeypatch.setattr(semantic, "_semantic_rank_uncached", uncached)

    first = await semantic.semantic_rank("list devices", [endpoint])
    second = await semantic.semantic_rank("list devices", [endpoint])

    assert first["mode"] == "fuzzy_fallback"
    assert first["cache_hit"] is False
    assert second["mode"] == "fuzzy_fallback"
    assert second["cache_hit"] is True
    assert second["elapsed_ms"] == 0.0
    assert uncached.await_count == 1


@pytest.mark.asyncio
async def test_semantic_rank_cache_key_includes_intent(monkeypatch):
    monkeypatch.setenv("NINJA_MCP_LLM_BASE_URL", "http://127.0.0.1:50000/v1")
    monkeypatch.setenv("NINJA_MCP_LLM_MODEL", "local-model")
    semantic._CACHE.clear()
    endpoint = ep("GET", "/v2/devices", "List devices", "Devices")
    uncached = AsyncMock(side_effect=[
        {"mode": "local_semantic", "selected": [{"endpoint": "GET /v2/devices"}]},
        {"mode": "local_semantic", "selected": [{"endpoint": "GET /v2/devices"}]},
    ])
    monkeypatch.setattr(semantic, "_semantic_rank_uncached", uncached)

    await semantic.semantic_rank("list devices", [endpoint])
    await semantic.semantic_rank("find devices", [endpoint])

    assert uncached.await_count == 2
