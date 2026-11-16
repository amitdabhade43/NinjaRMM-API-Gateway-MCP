from unittest.mock import AsyncMock, patch

import pytest

from ninja_mcp import server
from ninja_mcp.spec import Endpoint


@pytest.mark.asyncio
async def test_simple_inventory_read_skips_semantic_reranking():
    endpoint = Endpoint("GET", "/v2/devices", "getDevices", "List devices", "",
                        "Devices", ["Devices"])
    with patch.object(server, "_spec", return_value=object()):
        with patch.object(server, "search", return_value=[endpoint]) as search:
            with patch.object(server, "semantic_rank", new=AsyncMock()) as semantic:
                result = await server.discover_endpoints("How many devices?")

    assert result["semantic"]["mode"] == "fuzzy_fast_path"
    assert result["semantic"]["selected"][0]["endpoint"] == "GET /v2/devices"
    search.assert_called_once()
    assert search.call_args.kwargs["method"] == "GET"
    semantic.assert_not_awaited()


@pytest.mark.asyncio
async def test_scoped_inventory_request_keeps_semantic_reranking():
    endpoint = Endpoint("GET", "/v2/user/end-users/{id}/devices", "getUserDevices",
                        "List devices accessible by user", "", "Users", ["Users"])
    ranked = {"mode": "local_semantic", "selected": [{"endpoint": endpoint.key}]}
    with patch.object(server, "_spec", return_value=object()):
        with patch.object(server, "search", return_value=[endpoint]):
            with patch.object(server, "semantic_rank", new=AsyncMock(return_value=ranked)) as semantic:
                result = await server.discover_endpoints("List devices assigned to Rene")

    assert result["semantic"] == ranked
    semantic.assert_awaited_once()


def test_filtered_or_scoped_prompts_are_not_simple_reads():
    assert server._is_simple_read_intent("How many devices?")
    assert server._is_simple_read_intent("How many devices in total?")
    assert not server._is_simple_read_intent("Count devices with names starting with VM")
    assert not server._is_simple_read_intent("List devices assigned to Rene")
    assert not server._is_simple_read_intent("Show devices in the HOERBIGER organization")
