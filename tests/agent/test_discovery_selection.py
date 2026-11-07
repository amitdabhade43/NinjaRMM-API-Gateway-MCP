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
                                {"operation": "details", "identifier": "ABC123"})
    assert selected["endpoint"] == "GET /v2/devices/{id}"

def test_local_semantic_selection_is_respected():
    candidates = [
        {"endpoint": "GET /v2/users", "path": "/v2/users"},
        {"endpoint": "GET /v2/organizations", "path": "/v2/organizations"},
    ]
    selected = choose_candidate(candidates, {"mode": "local_semantic", "selected": [
        {"endpoint": "GET /v2/organizations", "purpose": "organization collection"}
    ]}, {"operation": "list", "identifier": None})
    assert selected["endpoint"] == "GET /v2/organizations"
