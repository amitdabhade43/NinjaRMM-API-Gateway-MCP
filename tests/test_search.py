from pathlib import Path

from ninja_mcp.search import search
from ninja_mcp.spec import Spec

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "minimal_openapi.json"


def test_search_finds_device_reboot():
    spec = Spec.load(FIXTURE_PATH)
    results = search(spec, "reboot device", limit=5)
    assert results, "expected at least one result for 'reboot device'"
    joined = " ".join(endpoint.search_text.lower() for endpoint in results)
    assert "reboot" in joined or "device" in joined


def test_category_filter():
    spec = Spec.load(FIXTURE_PATH)
    results = search(spec, category="devices", limit=50)
    assert results
    assert all(endpoint.category.lower() == "devices" for endpoint in results)


def test_method_filter():
    spec = Spec.load(FIXTURE_PATH)
    results = search(spec, method="POST", limit=50)
    assert results
    assert all(endpoint.method == "POST" for endpoint in results)


def test_empty_query_returns_candidates():
    spec = Spec.load(FIXTURE_PATH)
    results = search(spec, "", category="devices", limit=5)
    assert len(results) <= 5
    assert all(endpoint.category.lower() == "devices" for endpoint in results)
