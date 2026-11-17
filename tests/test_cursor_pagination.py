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


@pytest.mark.asyncio
async def test_paginated_endpoint_fuzzy_searches_all_record_fields(monkeypatch):
    endpoint = Endpoint(
        method="GET",
        path="/v2/people",
        operation_id="getPeople",
        summary="List people",
        description="Returns people records.",
        category="People",
        tags=["People"],
        parameters=[
            {"name": "page", "in": "query", "schema": {"type": "integer"}},
            {"name": "pageSize", "in": "query", "schema": {"type": "integer"}},
        ],
        responses={
            "200": {"content": {"application/json": {"schema": {
                "type": "array",
                "items": {"type": "object", "properties": {
                    "id": {"type": "integer"},
                    "firstName": {"type": "string"},
                    "lastName": {"type": "string"},
                    "email": {"type": "string"},
                }},
            }}}},
        },
    )

    class PeopleClient:
        async def request(self, method, path, params=None, json_body=None):
            assert method == "GET"
            assert path == "/v2/people"
            assert params == {"pageSize": 4, "page": 1}
            return [
                {"id": 1, "firstName": "Rene", "lastName": "Piuk", "email": "rene@example.test"},
                {"id": 2, "firstName": "Richard", "lastName": "Otrebski", "email": "richard@example.test"},
                {"id": 3, "displayName": "Other Person"},
            ]

    monkeypatch.setattr(server, "_spec", lambda: Spec([endpoint]))
    monkeypatch.setattr(server, "_client", lambda: PeopleClient())

    result = await server.execute_paginated_endpoint(
        "GET /v2/people",
        page_size=4,
        max_pages=2,
        search_text="Rene Piuk",
        search_threshold=80,
    )

    assert result["complete"] is True
    assert result["records_scanned"] == 3
    assert result["matches_found"] == 1
    assert result["items_fetched"] == 1
    assert result["data"] == [
        {"id": 1, "firstName": "Rene", "lastName": "Piuk", "email": "rene@example.test"}
    ]
