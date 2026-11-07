"""Compatibility tools inspired by the seven-tool NinjaOne MCP interface.

These are thin aliases over the existing schema-driven Gateway. They do not
create a second HTTP client or bypass OpenAPI validation/approval checks.
Saved memories are local GET-query templates, not tenant data or credentials.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from .search import search

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,79}$")


def _memory_path() -> Path:
    configured = os.getenv("NINJA_MCP_MEMORY_FILE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".ninjaone_agent" / "saved_queries.json"


def _read_memories() -> dict[str, dict[str, Any]]:
    path = _memory_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_memories(payload: dict[str, dict[str, Any]]) -> None:
    path = _memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def register_compat_tools(mcp, spec_getter, execute, match_template) -> None:
    """Register seven familiar tool names while reusing the current Gateway."""

    @mcp.tool()
    async def find_endpoint(query: str, category: str | None = None,
                            method: str | None = None, limit: int = 20) -> dict[str, Any]:
        """Find NinjaOne API endpoints by natural-language query, category or HTTP method."""
        spec = spec_getter()
        if method:
            method = method.upper()
            if method not in {"GET", "POST", "PUT", "PATCH"}:
                return {"error": "Supported methods are GET, POST, PUT and PATCH."}
        candidates = search(spec, query, category=category, method=method, limit=limit)
        return {"count": len(candidates), "results": [item.to_summary() for item in candidates]}

    @mcp.tool()
    async def describe_endpoint(endpoint: str) -> dict[str, Any]:
        """Describe the exact parameters, request body and response schema for an API endpoint."""
        found = spec_getter().get(endpoint)
        if found is None:
            return {"error": f"Unknown endpoint {endpoint!r}. Use find_endpoint."}
        if found.method == "DELETE":
            return {"error": "DELETE endpoints are not available through this Gateway."}
        return found.to_detail()

    @mcp.tool()
    async def call(endpoint: str, path_params: dict[str, Any] | None = None,
                   query: dict[str, Any] | None = None, body: Any = None,
                   approval_token: str | None = None) -> dict[str, Any]:
        """Call a documented NinjaOne endpoint by its exact OpenAPI key."""
        return await execute(endpoint, path_params=path_params, query=query,
                             body=body, approval_token=approval_token)

    @mcp.tool()
    async def raw_call(request: str, body: Any = None,
                       approval_token: str | None = None) -> dict[str, Any]:
        """Call a concrete relative NinjaOne API path such as 'GET /v2/devices?page=1'."""
        parts = request.strip().split(None, 1)
        if len(parts) != 2:
            return {"error": "Expected 'METHOD /path[?query]'.", "executed": False}
        method = parts[0].upper()
        if method not in {"GET", "POST", "PUT", "PATCH"}:
            return {"error": "Supported methods are GET, POST, PUT and PATCH; DELETE is blocked.",
                    "executed": False}
        split = urlsplit(parts[1])
        if split.scheme or split.netloc or not split.path.startswith("/"):
            return {"error": "Only relative NinjaOne API paths beginning with / are accepted.",
                    "executed": False}
        endpoint_key = f"{method} {split.path}"
        path_params = None
        if spec_getter().get(endpoint_key) is None:
            matched = match_template(method, split.path)
            if not matched:
                return {"error": f"No OpenAPI endpoint matches {method} {split.path}",
                        "executed": False}
            endpoint_key, path_params = matched
        query: dict[str, Any] = {}
        for key, value in parse_qsl(split.query, keep_blank_values=True):
            if key in query:
                query[key] = query[key] + [value] if isinstance(query[key], list) else [query[key], value]
            else:
                query[key] = value
        return await execute(endpoint_key, path_params=path_params, query=query or None,
                             body=body, approval_token=approval_token)

    @mcp.tool()
    async def memory_save(name: str, endpoint: str,
                          path_params: dict[str, Any] | None = None,
                          query: dict[str, Any] | None = None,
                          description: str = "") -> dict[str, Any]:
        """Save a reusable GET endpoint and its non-secret path/query parameters locally."""
        if not _NAME.fullmatch(name.strip()):
            return {"error": "Name must be 1-80 characters and use letters, numbers, spaces, dot, dash or underscore."}
        found = spec_getter().get(endpoint)
        if found is None:
            return {"error": f"Unknown endpoint {endpoint!r}. Discover it first."}
        if found.method != "GET":
            return {"error": "Only GET query templates can be saved."}
        item = {
            "name": name.strip(),
            "endpoint": endpoint,
            "path_params": path_params or {},
            "query": query or {},
            "description": description[:500],
        }
        memories = _read_memories()
        memories[name.strip().casefold()] = item
        _write_memories(memories)
        return {"saved": True, "memory": item,
                "note": "Saved locally as a reusable query template; no API data or credentials were stored."}

    @mcp.tool()
    async def memory_list(name: str | None = None) -> dict[str, Any]:
        """List saved NinjaOne query templates, optionally matching one name."""
        memories = _read_memories()
        values = list(memories.values())
        if name:
            values = [item for item in values if item.get("name", "").casefold() == name.casefold()]
        return {"count": len(values), "memories": values}

    @mcp.tool()
    async def memory_delete(name: str) -> dict[str, Any]:
        """Delete one locally saved NinjaOne query template by its exact name."""
        memories = _read_memories()
        key = name.strip().casefold()
        if key not in memories:
            return {"deleted": False, "error": f"No saved query named {name!r}."}
        del memories[key]
        _write_memories(memories)
        return {"deleted": True, "name": name}
