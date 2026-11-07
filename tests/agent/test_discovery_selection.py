from ninjaone_agent.discovery import choose_candidate


def test_fuzzy_list_prefers_collection_endpoint_without_entity_specific_rules():
    candidates = [
        {"endpoint": "GET /v2/user/technician/{id}", "path": "/v2/user/technician/{id}"},
        {"endpoint": "GET /v2/user/technicians", "path": "/v2/user/technicians"},
    ]
    selected = choose_candidate(candidates, {"mode": "fuzzy_fallback", "selected": [
        "GET /v2/user/technician/{id}", "GET /v2/user/technicians"
    ]}, {"operation": "count", "identifier": None})
    assert selected["endpoint"] == "GET /v2/user/technicians"


def test_details_prefers_item_endpoint_when_identifier_exists():
    candidates = [
        {"endpoint": "GET /v2/devices", "path": "/v2/devices"},
        {"endpoint": "GET /v2/devices/{id}", "path": "/v2/devices/{id}"},
    ]
    selected = choose_candidate(candidates, {"mode": "fuzzy_fallback", "selected": []},
                                {"entity": "devices", "operation": "details", "identifier": "ABC123"})
    assert selected["endpoint"] == "GET /v2/devices/{id}"


def test_local_semantic_selection_is_respected():
    candidates = [
        {"endpoint": "GET /v2/users", "path": "/v2/users"},
        {"endpoint": "GET /v2/organizations", "path": "/v2/organizations"},
    ]
    selected = choose_candidate(candidates, {"mode": "local_semantic", "selected": [
        {"endpoint": "GET /v2/organizations", "purpose": "organization collection"}
    ]}, {"entity": "organizations", "operation": "list", "identifier": None})
    assert selected["endpoint"] == "GET /v2/organizations"


def test_semantic_item_route_is_rejected_for_unscoped_collection_search():
    candidates = [
        {"endpoint": "GET /v2/devices/{id}", "path": "/v2/devices/{id}"},
        {"endpoint": "GET /v2/devices", "path": "/v2/devices"},
    ]
    selected = choose_candidate(candidates, {"mode": "local_semantic", "selected": [
        {"endpoint": "GET /v2/devices/{id}", "purpose": "device detail"}
    ]}, {"entity": "devices", "operation": "details", "identifier": None})
    assert selected["endpoint"] == "GET /v2/devices"


def test_unscoped_search_never_falls_back_to_item_endpoint():
    candidates = [{"endpoint": "GET /v2/devices/{id}", "path": "/v2/devices/{id}"}]
    try:
        choose_candidate(candidates, {"mode": "fuzzy_fallback", "selected": []},
                         {"entity": "devices", "operation": "list", "identifier": None})
        assert False, "Expected collection endpoint selection to fail safely"
    except RuntimeError as exc:
        assert "no collection get endpoint" in str(exc).casefold()


def test_startswith_filter_is_case_insensitive():
    from ninjaone_agent.result_processor import _matches
    assert _matches({"name": "2QN-LAPTOP-01"},
                    {"field": "name", "operator": "startswith", "value": "2qn"})


def test_device_name_prefix_prefers_device_collection_not_search_endpoint():
    candidates = [
        {"endpoint": "GET /v2/devices/search", "path": "/v2/devices/search"},
        {"endpoint": "GET /v2/devices", "path": "/v2/devices"},
        {"endpoint": "GET /v2/device/{id}", "path": "/v2/device/{id}"},
    ]
    selected = choose_candidate(
        candidates, {"mode": "local_semantic", "selected": [
            {"endpoint": "GET /v2/devices/search", "purpose": "search devices"}
        ]},
        {"entity": "devices", "operation": "list", "identifier": None,
         "filters": [{"field": "name", "operator": "startswith", "value": "2qn"}]},
    )
    assert selected["endpoint"] == "GET /v2/devices"


def test_device_search_rejects_unrelated_organization_endpoint():
    candidates = [
        {"endpoint": "GET /v2/organization/documents", "path": "/v2/organization/documents"}
    ]
    try:
        choose_candidate(candidates, {"mode": "local_semantic", "selected": [
            {"endpoint": "GET /v2/organization/documents", "purpose": "organization documents"}
        ]}, {"entity": "devices", "operation": "list", "identifier": None, "filters": []})
        assert False, "Device search must not execute an organization endpoint"
    except RuntimeError as exc:
        assert "device collection endpoint" in str(exc).casefold()


def test_device_details_rejects_unrelated_item_endpoint():
    candidates = [
        {"endpoint": "GET /v2/organization/{id}/documents", "path": "/v2/organization/{id}/documents"}
    ]
    try:
        choose_candidate(candidates, {"mode": "local_semantic", "selected": [
            {"endpoint": "GET /v2/organization/{id}/documents", "purpose": "organization documents"}
        ]}, {"entity": "devices", "operation": "details", "identifier": "123"})
        assert False, "Device details must not execute an organization endpoint"
    except RuntimeError as exc:
        assert "no matching item get endpoint" in str(exc).casefold()


def test_systems_alias_uses_ninjaone_device_collection():
    from ninjaone_agent.planner import normalize_entity
    task = {"entity": normalize_entity("systems"), "operation": "count", "identifier": None}
    candidates = [
        {"endpoint": "GET /v2/organization/documents", "path": "/v2/organization/documents"},
        {"endpoint": "GET /v2/devices", "path": "/v2/devices"},
    ]
    selected = choose_candidate(candidates, {"mode": "local_semantic", "selected": [
        {"endpoint": "GET /v2/organization/documents", "purpose": "organization documents"}
    ]}, task)
    assert selected["endpoint"] == "GET /v2/devices"
