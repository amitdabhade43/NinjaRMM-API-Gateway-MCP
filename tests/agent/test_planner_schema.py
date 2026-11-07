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


def test_planner_cannot_inject_path_or_query_parameters():
    plan = validate_plan({"tasks": [{
        "entity": "devices", "operation": "list",
        "path_params": {"q": "2qn"}, "query": {"q": "2qn"},
        "filters": [{"field": "name", "operator": "startswith", "value": "2qn"}],
    }]}, "list device names starting with 2qn")
    assert plan["tasks"][0]["path_params"] == {}
    assert plan["tasks"][0]["query"] == {}


def test_unqualified_device_count_discards_planner_invented_filter():
    plan = validate_plan({"tasks": [{
        "entity": "devices", "operation": "count",
        "filters": [{"field": "status", "operator": "eq", "value": "ONLINE"}],
    }]}, "how many devices in NinjaOne?")
    assert plan["tasks"][0]["filters"] == []


def test_explicit_offline_device_count_keeps_filter():
    plan = validate_plan({"tasks": [{
        "entity": "devices", "operation": "count",
        "filters": [{"field": "status", "operator": "eq", "value": "OFFLINE"}],
    }]}, "how many offline devices?")
    assert plan["tasks"][0]["filters"] == [
        {"field": "status", "operator": "eq", "value": "OFFLINE"}
    ]
