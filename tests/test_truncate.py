from ninja_mcp.truncate import MAX_ARRAY_ITEMS, truncate


def test_small_passthrough():
    data = {"a": 1, "b": [1, 2, 3]}
    out, was = truncate(data)
    assert out == data
    assert was is False


def test_top_level_list_truncation():
    data = [{"i": i, "pad": "x" * 500} for i in range(500)]
    out, was = truncate(data)
    assert was is True
    assert out["_truncated"] is True
    assert out["_total_items"] == 500
    assert len(out["items"]) == MAX_ARRAY_ITEMS


def test_nested_array_truncation():
    data = {"meta": "x", "results": [{"i": i, "pad": "x" * 200} for i in range(500)]}
    out, was = truncate(data)
    assert was is True
    assert out["_truncated"] is True
    assert len(out["results"]) == MAX_ARRAY_ITEMS


def test_non_serializable_returns_original():
    class Weird:
        pass

    out, was = truncate(Weird())
    assert was is False
