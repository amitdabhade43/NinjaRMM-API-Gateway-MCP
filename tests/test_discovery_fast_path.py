import pytest

from ninja_mcp import server
from ninja_mcp.spec import Endpoint, Spec


@pytest.mark.asyncio
async def test_clear_simple_get_discovery_includes_openapi_detail(monkeypatch):
    endpoint = Endpoint(
        method="GET",
        path="/v2/devices",
        operation_id="getDevices",
        summary="Get devices",
        description="Returns devices.",
        category="Devices",
        tags=["Devices"],
    )
    monkeypatch.setattr(server, "_spec", lambda: Spec([endpoint]))
    monkeypatch.setattr(server, "search", lambda *args, **kwargs: [endpoint])
    monkeypatch.setattr(server, "score_endpoint", lambda *args, **kwargs: 100)

    async def unexpected_semantic_call(*args, **kwargs):
        raise AssertionError("A clear simple GET must not invoke semantic ranking.")

    monkeypatch.setattr(server, "semantic_rank", unexpected_semantic_call)

    result = await server.discover_endpoints("How many devices?", candidate_limit=8)

    assert result["semantic"]["mode"] == "fuzzy_fast_path"
    assert result["semantic"]["selected"] == [{"endpoint": "GET /v2/devices"}]
    assert result["selected_details"] == endpoint.to_detail()
