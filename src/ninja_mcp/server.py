"""NinjaOne RMM API Gateway — MCP server.

Tools (7):
    find_endpoint, describe_endpoint, call, raw_call,
    memory_save, memory_list, memory_delete
"""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from mcp.server.fastmcp import FastMCP

from .client import NinjaAPIError, NinjaAuthError, NinjaClient
from .memory import FastMemory
from .search import search
from .spec import Spec
from .truncate import truncate

logging.basicConfig(
    level=os.environ.get("NINJA_MCP_LOG_LEVEL", "INFO"),
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("ninja_mcp")

PATH_PARAM_RE = re.compile(r"\{([^}]+)\}")

mcp = FastMCP("NinjaRMM-API-Gateway-MCP")

_SPEC: Spec | None = None
_MEMORY: FastMemory | None = None
_CLIENT: NinjaClient | None = None


def _spec_path() -> Path:
    override = os.environ.get("NINJA_MCP_SPEC")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent.parent / "NinjaRMM-API-v2.json"


def _spec() -> Spec:
    global _SPEC
    if _SPEC is None:
        _SPEC = Spec.load(_spec_path())
        log.info("Loaded %d endpoints from %s", len(_SPEC.endpoints), _spec_path())
    return _SPEC


def _memory() -> FastMemory:
    global _MEMORY
    if _MEMORY is None:
        _MEMORY = FastMemory()
    return _MEMORY


def _client() -> NinjaClient:
    global _CLIENT
    if _CLIENT is None:
        client_id = os.environ.get("NINJAONE_CLIENT_ID")
        client_secret = os.environ.get("NINJAONE_CLIENT_SECRET")
        instance = os.environ.get("NINJAONE_INSTANCE", "app.ninjarmm.com")
        if not client_id or not client_secret:
            raise NinjaAuthError(
                "NINJAONE_CLIENT_ID and NINJAONE_CLIENT_SECRET must be set"
            )
        _CLIENT = NinjaClient(client_id, client_secret, instance)
    return _CLIENT


def _interpolate_path(path: str, path_params: dict[str, Any] | None) -> str:
    path_params = path_params or {}
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in path_params:
            missing.append(name)
            return match.group(0)
        return str(path_params[name])

    resolved = PATH_PARAM_RE.sub(replace, path)
    if missing:
        raise ValueError(
            f"Missing path parameter(s): {', '.join(missing)}. Required: {PATH_PARAM_RE.findall(path)}"
        )
    return resolved


async def _execute(
    endpoint_key: str,
    *,
    path_params: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    body: Any = None,
) -> dict[str, Any]:
    endpoint = _spec().get(endpoint_key)
    if not endpoint:
        return {"error": f"Unknown endpoint: {endpoint_key!r}. Use find_endpoint to discover."}
    try:
        resolved_path = _interpolate_path(endpoint.path, path_params)
    except ValueError as e:
        return {"error": str(e)}

    try:
        data = await _client().request(
            endpoint.method, resolved_path, params=query, json_body=body
        )
    except NinjaAuthError as e:
        return {"error": f"Authentication failed: {e}", "hint": "Check NINJAONE_CLIENT_ID / _SECRET."}
    except NinjaAPIError as e:
        return {"error": str(e), "status": e.status, "body": e.body}

    result, was_truncated = truncate(data)
    return {
        "endpoint": f"{endpoint.method} {resolved_path}",
        "truncated": was_truncated,
        "data": result,
    }


@mcp.tool()
async def find_endpoint(
    query: str = "",
    category: str | None = None,
    method: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Discover NinjaOne API endpoints.

    Use with no args to list categories. Pass `query` for fuzzy text search
    across path, summary, description, and tags. Filter by `category`
    (e.g. 'devices', 'Billing') and/or `method` (GET/POST/PUT/PATCH/DELETE).

    Returns a list of endpoint summaries. Use `describe_endpoint` for full
    parameter/schema detail on a specific match.
    """
    spec = _spec()
    if not query and not category and not method:
        return {
            "categories": spec.categories,
            "total_endpoints": len(spec.endpoints),
            "hint": "Call find_endpoint again with a `query` or `category` filter to see endpoints.",
        }
    results = search(spec, query, category=category, method=method, limit=limit)
    return {
        "count": len(results),
        "results": [e.to_summary() for e in results],
    }


@mcp.tool()
async def describe_endpoint(endpoint: str) -> dict[str, Any]:
    """Full details for a specific endpoint: parameters, request body schema, responses.

    `endpoint` format: 'METHOD /path' — e.g. 'GET /v2/devices/{id}'.
    """
    e = _spec().get(endpoint)
    if not e:
        return {"error": f"Unknown endpoint: {endpoint!r}"}
    return e.to_detail()


@mcp.tool()
async def call(
    endpoint: str,
    path_params: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    body: Any = None,
    memory_id: str | None = None,
) -> dict[str, Any]:
    """Execute a NinjaOne API call.

    `endpoint`: 'METHOD /path' exactly as shown by find_endpoint (can include
    `{placeholders}` — supply values via `path_params`).
    `path_params`: values for `{name}` placeholders in the path.
    `query`: query-string parameters (e.g. filters, pagination).
    `body`: JSON request body for POST/PUT/PATCH.
    `memory_id`: load previously-saved params from fast memory; explicit args
    still override the saved values.
    """
    if memory_id:
        entry = _memory().get(memory_id)
        if not entry:
            return {"error": f"No memory entry with id {memory_id!r}"}
        endpoint = endpoint or entry["endpoint"]
        path_params = path_params or entry.get("path_params") or None
        query = query or entry.get("query") or None
        if body is None:
            body = entry.get("body")
    return await _execute(endpoint, path_params=path_params, query=query, body=body)


@mcp.tool()
async def raw_call(request: str, body: Any = None) -> dict[str, Any]:
    """Quick-form API call. Parses 'METHOD /path?query=value'.

    Example: raw_call("GET /v2/devices?df=class eq 'WINDOWS_WORKSTATION'")
    Pass `body` separately for POST/PUT/PATCH.
    """
    parts = request.strip().split(None, 1)
    if len(parts) != 2:
        return {"error": "Format: 'METHOD /path[?query]'"}
    method, rest = parts[0].upper(), parts[1]
    split = urlsplit(rest)
    path, query_string = split.path, split.query
    query = dict(parse_qsl(query_string, keep_blank_values=True)) if query_string else None
    endpoint_key = f"{method} {path}"

    # Path-param interpolation is skipped for raw_call — caller supplies a concrete path.
    # Just verify the spec shape by stripping any {placeholders} to match the template.
    if _spec().get(endpoint_key) is None:
        template_match = _match_template(method, path)
        if template_match:
            endpoint_key = template_match

    return await _execute(endpoint_key, query=query, body=body)


def _match_template(method: str, concrete_path: str) -> str | None:
    """Find a spec entry whose {templated} path matches a concrete path."""
    for ep in _spec().endpoints:
        if ep.method != method:
            continue
        pattern = re.sub(r"\{[^}]+\}", r"[^/]+", ep.path)
        if re.fullmatch(pattern, concrete_path):
            return ep.key
    return None


@mcp.tool()
async def memory_save(
    name: str,
    endpoint: str,
    path_params: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    body: Any = None,
    description: str = "",
) -> dict[str, Any]:
    """Save an API call for quick reuse later.

    Returns the saved entry including its `id`, which can be passed to
    `call(memory_id=...)` to replay.
    """
    entry = _memory().save(
        name,
        endpoint,
        path_params=path_params,
        query=query,
        body=body,
        description=description,
    )
    return {"saved": entry}


@mcp.tool()
async def memory_list() -> dict[str, Any]:
    """List all saved fast-memory entries."""
    return {"entries": _memory().list_all()}


@mcp.tool()
async def memory_delete(memory_id: str) -> dict[str, Any]:
    """Delete a fast-memory entry. Pass `memory_id='*'` to clear all."""
    if memory_id == "*":
        n = _memory().clear()
        return {"cleared": n}
    ok = _memory().delete(memory_id)
    return {"deleted": ok, "id": memory_id}


def main() -> None:
    log.info("Starting NinjaOne MCP server; spec path=%s", _spec_path())
    _spec()  # fail fast if spec is missing / malformed
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
