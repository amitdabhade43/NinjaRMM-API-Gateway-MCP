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
        "endpoint": "GET /v2/devices", "complete": False, "truncated": True,
        "data": {"_truncated": True, "_total_items": 90, "_showing": 50,
                 "items": [{"id": 1, "displayName": "2qn-01"}]},
    })
    assert result["count"] == 1
    assert result["complete"] is False
    assert result["truncated"] is True

def test_incomplete_zero_is_explained_as_partial():
    task = {"description": "List device names starting with 2qn", "operation": "list",
            "filters": [{"field": "name", "operator": "startswith", "value": "2qn"}]}
    result = process_result(task, {
        "endpoint": "GET /v2/devices", "complete": False, "truncated": True,
        "data": [{"id": 1, "displayName": "other-device"}],
    })
    text = format_fast({"response_format": "list"}, [result])
    assert "not a confirmed total" in text
    assert "other records may still match" in text

def test_incomplete_metadata_is_preserved():
    task = {"description": "List devices", "operation": "list", "filters": []}
    result = process_result(task, {
        "endpoint": "GET /v2/devices", "complete": False, "truncated": True,
        "data": [{"id": 1}],
    })
    assert result["complete"] is False
    assert result["truncated"] is True
