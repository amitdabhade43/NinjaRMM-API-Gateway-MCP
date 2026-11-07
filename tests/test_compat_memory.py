from ninja_mcp.compat_tools import _read_memories, _write_memories


def test_saved_query_memory_round_trip_uses_local_json_file(tmp_path, monkeypatch):
    memory_file = tmp_path / "saved" / "queries.json"
    monkeypatch.setenv("NINJA_MCP_MEMORY_FILE", str(memory_file))

    expected = {
        "workstations": {
            "name": "Workstations",
            "endpoint": "GET /v2/devices",
            "path_params": {},
            "query": {"pageSize": 100},
            "description": "Managed Windows workstations",
        }
    }

    _write_memories(expected)

    assert memory_file.exists()
    assert _read_memories() == expected


def test_missing_saved_query_file_returns_empty_collection(tmp_path, monkeypatch):
    monkeypatch.setenv("NINJA_MCP_MEMORY_FILE", str(tmp_path / "missing.json"))

    assert _read_memories() == {}
