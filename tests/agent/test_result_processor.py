from ninjaone_agent.result_processor import process_result

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

def test_incomplete_metadata_is_preserved():
    task = {"description": "List devices", "operation": "list", "filters": []}
    result = process_result(task, {
        "endpoint": "GET /v2/devices", "complete": False, "truncated": True,
        "data": [{"id": 1}],
    })
    assert result["complete"] is False
    assert result["truncated"] is True
