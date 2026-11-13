from pathlib import Path

import pytest

from ninja_mcp.spec import Spec

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "minimal_openapi.json"
OFFICIAL_SPEC_PATH = ROOT / "NinjaRMM-API-v2.json"


def test_downloaded_official_spec_loads_all_supported_endpoints():
    if not OFFICIAL_SPEC_PATH.is_file():
        pytest.skip("Run scripts/sync_openapi_spec.py to enable the full official-spec smoke test.")
    spec = Spec.load(OFFICIAL_SPEC_PATH)
    assert len(spec.endpoints) >= 200
    assert {e.method for e in spec.endpoints} <= {"GET", "POST", "PUT", "PATCH"}
    assert "devices" in [category.lower() for category in spec.categories]


def test_fixture_loads_supported_methods_and_categories():
    spec = Spec.load(FIXTURE_PATH)
    assert len(spec.endpoints) == 3
    assert {endpoint.method for endpoint in spec.endpoints} == {"GET", "POST"}
    assert "devices" in [category.lower() for category in spec.categories]


def test_get_by_key_case_insensitive_method():
    spec = Spec.load(FIXTURE_PATH)
    hit = spec.get("get /v2/devices")
    assert hit is not None
    assert hit.method == "GET"


def test_unknown_endpoint_returns_none():
    spec = Spec.load(FIXTURE_PATH)
    assert spec.get("GET /nope") is None
    assert spec.get("malformed") is None


def test_endpoint_search_text_contains_fields():
    spec = Spec.load(FIXTURE_PATH)
    endpoint = next(iter(spec.endpoints))
    text = endpoint.search_text
    assert endpoint.method in text
    assert endpoint.path in text
