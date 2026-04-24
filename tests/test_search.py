from pathlib import Path

from ninja_mcp.search import search
from ninja_mcp.spec import Spec

SPEC_PATH = Path(__file__).resolve().parent.parent / "NinjaRMM-API-v2.json"


def test_search_finds_device_reboot():
    spec = Spec.load(SPEC_PATH)
    results = search(spec, "reboot device", limit=5)
    assert results, "expected at least one result for 'reboot device'"
    joined = " ".join(e.search_text.lower() for e in results)
    assert "reboot" in joined or "device" in joined


def test_category_filter():
    spec = Spec.load(SPEC_PATH)
    results = search(spec, category="devices", limit=50)
    assert results
    assert all(e.category.lower() == "devices" for e in results)


def test_method_filter():
    spec = Spec.load(SPEC_PATH)
    results = search(spec, method="POST", limit=50)
    assert results
    assert all(e.method == "POST" for e in results)


def test_empty_query_returns_candidates():
    spec = Spec.load(SPEC_PATH)
    results = search(spec, "", category="devices", limit=5)
    assert len(results) <= 5
    assert all(e.category.lower() == "devices" for e in results)
