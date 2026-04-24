from pathlib import Path

from ninja_mcp.memory import FastMemory


def test_save_list_delete(tmp_path: Path):
    mem = FastMemory(tmp_path / "mem.json")
    entry = mem.save("win workstations", "GET /v2/devices", query={"df": "class eq 'WINDOWS_WORKSTATION'"})
    assert "id" in entry

    listed = mem.list_all()
    assert len(listed) == 1
    assert listed[0]["name"] == "win workstations"

    assert mem.delete(entry["id"]) is True
    assert mem.list_all() == []


def test_delete_missing_returns_false(tmp_path: Path):
    mem = FastMemory(tmp_path / "mem.json")
    assert mem.delete("nope") is False


def test_clear(tmp_path: Path):
    mem = FastMemory(tmp_path / "mem.json")
    mem.save("a", "GET /v2/devices")
    mem.save("b", "GET /v2/organizations")
    assert mem.clear() == 2
    assert mem.list_all() == []


def test_persistence(tmp_path: Path):
    path = tmp_path / "mem.json"
    FastMemory(path).save("saved", "GET /v2/devices")
    reloaded = FastMemory(path)
    assert len(reloaded.list_all()) == 1
    assert reloaded.list_all()[0]["name"] == "saved"


def test_corrupt_file_resets(tmp_path: Path):
    path = tmp_path / "mem.json"
    path.write_text("not valid json{{{")
    mem = FastMemory(path)
    assert mem.list_all() == []
