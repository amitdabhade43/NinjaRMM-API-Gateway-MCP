"""JSON-backed fast memory for saved API queries."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any


def _default_store_path() -> Path:
    override = os.environ.get("NINJA_MCP_HOME")
    base = Path(override) if override else Path.home() / ".ninja-mcp"
    return base / "fast_memory.json"


class FastMemory:
    """Single-process JSON store. Writes atomically via temp-rename."""

    def __init__(self, path: Path | None = None):
        self.path = path or _default_store_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _flush(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def save(
        self,
        name: str,
        endpoint: str,
        *,
        path_params: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        body: Any = None,
        description: str = "",
    ) -> dict[str, Any]:
        mid = uuid.uuid4().hex[:8]
        entry = {
            "id": mid,
            "name": name,
            "description": description,
            "endpoint": endpoint,
            "path_params": path_params or {},
            "query": query or {},
            "body": body,
            "created_at": time.time(),
        }
        self._data[mid] = entry
        self._flush()
        return entry

    def list_all(self) -> list[dict[str, Any]]:
        return sorted(self._data.values(), key=lambda e: e.get("created_at", 0))

    def get(self, mid: str) -> dict[str, Any] | None:
        return self._data.get(mid)

    def delete(self, mid: str) -> bool:
        if mid in self._data:
            del self._data[mid]
            self._flush()
            return True
        return False

    def clear(self) -> int:
        n = len(self._data)
        self._data = {}
        self._flush()
        return n
