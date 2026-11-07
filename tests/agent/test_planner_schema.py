from ninjaone_agent.planner import validate_plan

def test_count_only_typo_is_normalized():
    plan = validate_plan({
        "intent": "technician_count", "response_format": "count_only",
        "tasks": [{"entity": "technicians", "operation": "count",
                   "filters": [{"field": "userType", "operator": "eq", "value": "TECHNICIAN"}]}],
    }, "i want cont of ninjaone technician")
    assert plan["tasks"][0]["operation"] == "count"
    assert plan["response_format"] == "count_only"

def test_independent_requests_remain_separate():
    plan = validate_plan({"response_format": "summary", "tasks": [
        {"entity": "organizations", "operation": "count"},
        {"entity": "technicians", "operation": "count"},
    ]}, "count organizations and technicians")
    assert len(plan["tasks"]) == 2
    assert all(not task["depends_on"] for task in plan["tasks"])

def test_unsafe_filter_operator_is_dropped():
    plan = validate_plan({"tasks": [{"entity": "devices", "operation": "count",
        "filters": [{"field": "status", "operator": "execute", "value": "offline"}]}]},
        "count offline devices")
    assert plan["tasks"][0]["filters"] == []
