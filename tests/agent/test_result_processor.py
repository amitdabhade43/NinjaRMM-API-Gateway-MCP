import pytest
from types import SimpleNamespace
from ninjaone_agent.executor import _cursor_pagination, _execute_cursor_pages
from ninjaone_agent.result_processor import process_result
from ninjaone_agent.response import format_fast


def test_cursor_pagination_does_not_depend_on_description_wording():
    detail = {"parameters": [
        {"name": "after", "in": "query", "description": "Cursor for the next request"},
        {"name": "pageSize", "in": "query", "description": "Maximum number of records"},
    ]}
    assert _cursor_pagination(detail) == ("after", "pageSize")


def test_cursor_pagination_is_case_insensitive_for_schema_names():
    detail = {"parameters": [
        {"name": "AFTER", "in": "query"},
        {"name": "PAGESIZE", "in": "query"},
    ]}
    assert _cursor_pagination(detail) == ("AFTER", "PAGESIZE")


def test_cursor_pagination_requires_both_declared_query_parameters():
    assert _cursor_pagination({"parameters": [{"name": "after", "in": "query"}]}) is None
    assert _cursor_pagination({"parameters": [{"name": "pageSize", "in": "query"}]}) is None


@pytest.mark.asyncio
async def test_cursor_pagination_checks_empty_page_after_exact_multiple():
    class FakeGateway:
        def __init__(self):
            self.calls = []
        async def call(self, name, args):
            self.calls.append(args)
            if len(self.calls) <= 2:
                start = (len(self.calls) - 1) * 50 + 1
                return {"endpoint": "GET /v2/devices", "complete": True,
                        "data": [{"id": i, "displayName": f"PC-{i}"} for i in range(start, start + 50)]}
            return {"endpoint": "GET /v2/devices", "complete": True, "data": []}

    gateway = FakeGateway()
    result = await _execute_cursor_pages(
        gateway, SimpleNamespace(page_size=100, max_pages=10),
        "GET /v2/devices", {}, {}, ("after", "pageSize")
    )
    assert result["complete"] is True
    assert result["items_fetched"] == 100
    assert result["pages_fetched"] == 3
    assert gateway.calls[2]["query"] == {"pageSize": 50, "after": 100}


@pytest.mark.asyncio
async def test_cursor_pagination_marks_page_limit_as_partial():
    class FakeGateway:
        async def call(self, name, args):
            after = (args.get("query") or {}).get("after", 0)
            return {"endpoint": "GET /v2/devices", "complete": True,
                    "data": [{"id": after + i, "displayName": f"PC-{after+i}"} for i in range(1, 51)]}

    result = await _execute_cursor_pages(
        FakeGateway(), SimpleNamespace(page_size=50, max_pages=2),
        "GET /v2/devices", {}, {}, ("after", "pageSize")
    )
    assert result["complete"] is False
    assert result["max_pages_reached"] is True
    assert result["items_fetched"] == 100


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


def test_accessible_device_count_counts_user_access_ids_not_all_devices():
    task = {"description": "Count devices accessible to Richard O", "operation": "count",
            "filters": [{"field": "name", "operator": "contains", "value": "richard o"}],
            "count_field": "accessibleDeviceIds"}
    result = process_result(task, {
        "endpoint": "GET /v2/user/end-users", "complete": True,
        "data": [
            {"id": 1, "firstName": "Richard", "lastName": "O", "assignedDeviceIds": [1, 2],
             "accessibleDeviceIds": [1, 2, 3]},
            {"id": 2, "firstName": "Other", "lastName": "Person", "accessibleDeviceIds": [4, 5]},
        ],
    })
    assert result["count"] == 3
    assert result["matched_subjects"] == 1
    assert result["total_records_received"] == 2


def test_accessible_device_count_deduplicates_device_ids_across_matching_users():
    task = {"description": "Count devices accessible to Richard O", "operation": "count",
            "filters": [{"field": "name", "operator": "contains", "value": "richard o"}],
            "count_field": "accessibleDeviceIds"}
    result = process_result(task, {"complete": True, "data": [
        {"firstName": "Richard", "lastName": "O", "accessibleDeviceIds": [1, 2]},
        {"firstName": "Richard", "lastName": "O", "accessibleDeviceIds": [2, 3]},
    ]})
    assert result["count"] == 3
    assert result["clarification_required"] is False


def test_access_count_requires_clarification_when_multiple_people_match():
    task = {"description": "Count devices accessible to Arthur", "operation": "count",
            "filters": [{"field": "name", "operator": "contains", "value": "Arthur"}],
            "count_field": "accessibleDeviceIds"}
    result = process_result(task, {"complete": True, "data": [
        {"id": 1, "firstName": "Arthur", "lastName": "Brown", "email": "arthur.brown@example.com",
         "accessibleDeviceIds": [1, 2]},
        {"id": 2, "firstName": "Arthur", "lastName": "Smith", "email": "arthur.smith@example.com",
         "accessibleDeviceIds": [3]},
    ]})
    assert result["clarification_required"] is True
    assert result["count"] is None
    assert len(result["data"]) == 2


def test_person_name_filter_tolerates_simple_typo():
    task = {"description": "Find user", "operation": "list",
            "filters": [{"field": "name", "operator": "contains", "value": "aurthur"}]}
    result = process_result(task, {"complete": True, "data": [
        {"id": 1, "firstName": "Arthur", "lastName": "Brown"},
        {"id": 2, "firstName": "Maria", "lastName": "Jones"},
    ]})
    assert result["count"] == 1
    assert result["data"][0]["id"] == 1


def test_duplicate_rows_for_same_person_are_deduplicated_by_identity():
    task = {"description": "Count devices accessible to Richard O", "operation": "count",
            "filters": [{"field": "name", "operator": "contains", "value": "richard o"}],
            "count_field": "accessibleDeviceIds"}
    result = process_result(task, {"complete": True, "data": [
        {"id": 7, "firstName": "Richard", "lastName": "O", "email": "richard@example.com",
         "accessibleDeviceIds": [1, 2]},
        {"id": 7, "firstName": "Richard", "lastName": "O", "email": "richard@example.com",
         "accessibleDeviceIds": [2, 3]},
    ]})
    assert result["count"] == 3
    assert result["matched_subjects"] == 1
    assert result.get("clarification_required") is not True
