import json

from ninja_mcp.spec import Spec


def test_spec_excludes_http_delete_and_post_delete_or_decommission(tmp_path):
    document = {
        "openapi": "3.0.1",
        "paths": {
            "/v2/things": {
                "get": {"summary": "List things"},
                "delete": {"summary": "Delete all things"},
            },
            "/v2/things/delete": {
                "post": {"operationId": "deleteThings", "summary": "Delete things"},
            },
            "/v2/things/{id}/decommission": {
                "post": {"operationId": "decommissionThing", "summary": "Decommission thing"},
            },
            "/v2/things/{id}/members": {
                "patch": {"operationId": "removeMembers", "summary": "Remove members"},
            },
        },
    }
    spec_path = tmp_path / "openapi.json"
    spec_path.write_text(json.dumps(document), encoding="utf-8")

    spec = Spec.load(spec_path)

    assert spec.get("GET /v2/things") is not None
    assert spec.get("DELETE /v2/things") is None
    assert spec.get("POST /v2/things/delete") is None
    assert spec.get("POST /v2/things/{id}/decommission") is None
    # Other explicitly approved PATCH operations are not silently reclassified.
    assert spec.get("PATCH /v2/things/{id}/members") is not None
