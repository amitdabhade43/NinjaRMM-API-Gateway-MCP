import pytest
from ninjaone_agent.result_processor import process_result
from ninjaone_agent.response import format_fast


def test_count_applies_filter_before_counting():
    task = {"description": "Count technicians", "operation": "count",
            "filters": [{"field": "userType", "operator": "eq", "value": "TECHNICIAN"}]}
    result = process_result(task, {
        "endpoint": "GET /v2/user/technicians", "complete": True, "truncated": False,
        "data": [{"firstName": "A", "userType": "TECHNICIAN"},
                 {"firstName": "B", "userType": "END_USER"},
                 {"firstName": "C", "userType": "TECHNICIAN"}],
    })
    assert result["count"] == 2
    assert "data" not in result


def test_unfiltered_inventory_count_counts_every_returned_record():
    task = {"description": "Count all devices", "operation": "count", "filters": []}
    result = process_result(task, {
        "endpoint": "GET /v2/devices", "complete": True,
        "data": [{"id": i, "displayName": f"PC-{i}"} for i in range(500)],
    })
    assert result["count"] == 500
    assert result["total_records_received"] == 500
    assert result["complete"] is True


def test_device_name_prefix_checks_documented_name_fields():
    task = {"description": "List device names starting with 2qn", "operation": "list",
            "filters": [{"field": "name", "operator": "startswith", "value": "2qn"}]}
    result = process_result(task, {
        "endpoint": "GET /v2/devices", "complete": True, "truncated": False,
        "data": [
            {"id": 1, "displayName": "2QN-LAPTOP-01", "systemName": "LAPTOP-01"},
            {"id": 2, "displayName": "Other", "systemName": "2qn-server-02"},
            {"id": 3, "displayName": "Other", "systemName": "server-03"},
        ],
    })
    assert result["count"] == 2
    assert [row["id"] for row in result["data"]] == [1, 2]


def test_gateway_truncation_wrapper_is_readable_and_incomplete():
    task = {"description": "List devices", "operation": "list", "filters": []}
    result = process_result(task, {
        "endpoint": "GET /v2/devices", "complete": False,
        "data": {"_truncated": True, "_total_items": 90, "_showing": 50,
                 "items": [{"id": 1, "displayName": "2qn-01"}]},
    })
    assert result["count"] == 1
    assert result["complete"] is False
    assert result["truncated"] is True


def test_single_record_detail_response_is_supported():
    task = {"description": "Get device details", "operation": "details", "filters": []}
    result = process_result(task, {
        "endpoint": "GET /v2/device/123", "complete": True,
        "data": {"id": 123, "displayName": "2QN-LAPTOP-01", "systemName": "LAPTOP-01"},
    })
    assert result["count"] == 1
    assert result["data"][0]["id"] == 123


def test_incomplete_zero_is_explained_as_partial():
    task = {"description": "List device names starting with 2qn", "operation": "list",
            "filters": [{"field": "name", "operator": "startswith", "value": "2qn"}]}
    result = process_result(task, {
        "endpoint": "GET /v2/devices", "complete": False, "truncated": True,
        "data": [{"id": 1, "displayName": "other-device"}],
    })
    response = format_fast({"response_format": "list"}, [result])
    assert "not a confirmed total" in response
    assert "other records may still match" in response


def test_incomplete_metadata_is_preserved():
    task = {"description": "List devices", "operation": "list", "filters": []}
    result = process_result(task, {
        "endpoint": "GET /v2/devices", "complete": False, "truncated": True,
        "data": [{"id": 1}],
    })
    assert result["complete"] is False
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_cursor_pagination_uses_last_device_id():
    from types import SimpleNamespace
    from ninjaone_agent.executor import _execute_cursor_pages

    class FakeGateway:
        def __init__(self):
            self.calls = []
        async def call(self, name, args):
            self.calls.append((name, args))
            if len(self.calls) == 1:
                return {"endpoint": "GET /v2/devices", "complete": True,
                        "data": [{"id": i, "displayName": f"PC-{i}"} for i in range(1, 51)]}
            return {"endpoint": "GET /v2/devices", "complete": True,
                    "data": [{"id": 51, "displayName": "2qn-PC-51"}]}

    gateway = FakeGateway()
    config = SimpleNamespace(page_size=100, max_pages=10)
    result = await _execute_cursor_pages(
        gateway, config, "GET /v2/devices", {}, {}, ("after", "pageSize")
    )
    assert result["complete"] is True
    assert result["pages_fetched"] == 2
    assert result["items_fetched"] == 51
    assert gateway.calls[0][1]["query"] == {"pageSize": 50}
    assert gateway.calls[1][1]["query"] == {"pageSize": 50, "after": 50}


@pytest.mark.asyncio
async def test_cursor_pagination_continues_after_gateway_page_wrapper():
    from types import SimpleNamespace
    from ninjaone_agent.executor import _execute_cursor_pages

    class FakeGateway:
        def __init__(self):
            self.calls = []
        async def call(self, name, args):
            self.calls.append(args)
            if len(self.calls) == 1:
                return {"endpoint": "GET /v2/devices", "complete": False,
                        "data": {"_truncated": True, "items": [
                            {"id": i, "displayName": f"PC-{i}"} for i in range(1, 51)
                        ]}}
            return {"endpoint": "GET /v2/devices", "complete": True,
                    "data": [{"id": 51, "displayName": "PC-51"}]}

    gateway = FakeGateway()
    result = await _execute_cursor_pages(
        gateway, SimpleNamespace(page_size=100, max_pages=10),
        "GET /v2/devices", {}, {}, ("after", "pageSize")
    )
    assert result["complete"] is True
    assert result["items_fetched"] == 51
    assert gateway.calls[1]["query"]["after"] == 50
