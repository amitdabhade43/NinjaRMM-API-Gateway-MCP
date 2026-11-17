import pytest

from ninja_mcp import server
from ninja_mcp.spec import Endpoint, Spec


class FakeNinjaClient:
    def __init__(self):
        self.calls = []

    async def request(self, method, path, params=None, json_body=None):
        self.calls.append((method, path, dict(params or {})))
        if "after" not in (params or {}):
            return [{"id": 1}, {"id": 2}]
        if params["after"] == 2:
            return [{"id": 3}]
        raise AssertionError("Unexpected cursor value")


@pytest.mark.asyncio
async def test_cursor_pagination_uses_last_record_id_from_openapi(monkeypatch):
    endpoint = Endpoint(
        method="GET",
        path="/v2/devices",
        operation_id="getDevices",
        summary="List devices",
        description="Returns devices.",
        category="Devices",
        tags=["Devices"],
        parameters=[
            {"name": "pageSize", "in": "query", "schema": {"type": "integer"}},
            {"name": "after", "in": "query", "description": "Last Node ID from previous page",
             "schema": {"type": "integer"}},
        ],
        responses={
            "default": {"content": {"application/json": {"schema": {
                "type": "array",
                "items": {"type": "object", "properties": {"id": {"type": "integer"}}},
            }}}}
        },
    )
    client = FakeNinjaClient()
    monkeypatch.setattr(server, "_spec", lambda: Spec([endpoint]))
    monkeypatch.setattr(server, "_client", lambda: client)

    result = await server.execute_paginated_endpoint(
        "GET /v2/devices",
        cursor_parameter="after",
        cursor_field="id",
        page_size_parameter="pageSize",
        page_size=2,
        max_pages=5,
    )

    assert result["complete"] is True
    assert result["items_fetched"] == 3
    assert result["pages_fetched"] == 2
    assert client.calls == [
        ("GET", "/v2/devices", {"pageSize": 2}),
        ("GET", "/v2/devices", {"pageSize": 2, "after": 2}),
    ]
