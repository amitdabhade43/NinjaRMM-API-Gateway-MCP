from pathlib import Path

from ninja_mcp.spec import Spec

SPEC_PATH = Path(__file__).resolve().parent.parent / "NinjaRMM-API-v2.json"


def test_spec_loads_all_endpoints():
    spec = Spec.load(SPEC_PATH)
    assert len(spec.endpoints) >= 300
    assert "devices" in [c.lower() for c in spec.categories]


def test_get_by_key_case_insensitive_method():
    spec = Spec.load(SPEC_PATH)
    hit = spec.get("get /v2/devices")
    assert hit is not None
    assert hit.method == "GET"


def test_unknown_endpoint_returns_none():
    spec = Spec.load(SPEC_PATH)
    assert spec.get("GET /nope") is None
    assert spec.get("malformed") is None


def test_endpoint_search_text_contains_fields():
    spec = Spec.load(SPEC_PATH)
    ep = next(iter(spec.endpoints))
    text = ep.search_text
    assert ep.method in text
    assert ep.path in text
