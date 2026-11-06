# NinjaOne API Gateway MCP

A schema-driven MCP gateway for the NinjaOne REST API v2. It discovers operations from the bundled OpenAPI document and exposes a small, general-purpose tool surface. It does not hardcode a separate tool for every NinjaOne resource.

## Security model

- **GET** is permitted automatically.
- **POST, PUT and PATCH** are permitted only with a trusted, short-lived HMAC approval token bound to the exact HTTP method, resolved path and JSON body.
- **DELETE is blocked** in endpoint discovery and at execution. A token cannot override this restriction.
- The approval secret must remain in the trusted approval service/gateway environment. Never expose it to an LLM or MCP client.
- Non-GET calls are never automatically retried, avoiding accidental duplicate mutations after ambiguous network failures.

### Approval token contract

The trusted approval service should sign the base64url-encoded UTF-8 JSON payload using HMAC-SHA256 with `NINJA_MCP_APPROVAL_SECRET`. Payload fields:

```json
{"method":"PATCH","path":"/v2/organizations/123","body_sha256":"<sha256 of canonical JSON body>","exp":<unix-seconds>}
```

The token is `<base64url(payload)>.<base64url(hmac_sha256(secret, encoded_payload))>`. Canonical body JSON uses sorted keys, compact separators and UTF-8. Tokens are single-purpose and short-lived. A production approval service should additionally authenticate the human, authorize their NinjaOne scope, log the approval, and prevent token replay.

## Tools

| Tool | Purpose |
|---|---|
| `discover_endpoints` | Fuzzy candidate retrieval plus optional local-LLM semantic ranking grounded in OpenAPI candidates |
| `inspect_endpoint` | Exact parameters, required fields, request body and response schemas |
| `execute_endpoint` | Execute a discovered endpoint using structured path/query/body arguments |
| `execute_raw_request` | Execute a concrete method/path; extracts concrete path values into OpenAPI placeholders |
| `execute_paginated_endpoint` | Bounded GET pagination using explicitly selected, OpenAPI-declared page and page-size parameters |

Only GET/POST/PUT/PATCH operations are loaded from the specification. DELETE is excluded and separately blocked at runtime.

## Search and semantic ranking

Fuzzy search uses RapidFuzz over operation ID, path, summary, tags/category and a bounded description. It retrieves a candidate set; it does not claim to understand the whole task.

For semantic ranking, configure a local OpenAI-compatible chat-completions endpoint:

- `NINJA_MCP_LLM_BASE_URL`: base URL, e.g. `http://127.0.0.1:52072/v1`
- `NINJA_MCP_LLM_MODEL`: model ID exposed by the local runtime
- `NINJA_MCP_LLM_API_KEY`: optional
- `NINJA_MCP_LLM_TIMEOUT`: optional, default 20 seconds

The model can select only endpoint keys in the fuzzy candidate set. If the local model is unavailable, discovery returns fuzzy-ranked candidates. The gateway validates the chosen operation and all supplied parameters against the OpenAPI document before execution. Multi-step joins and business logic belong in the calling orchestrator, which must inspect each operation and verify intermediate results.

## Setup

Python 3.10+:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Configure environment variables (PowerShell):

```powershell
$env:NINJAONE_CLIENT_ID = "your-client-id"
$env:NINJAONE_CLIENT_SECRET = "your-client-secret"
$env:NINJAONE_INSTANCE = "eu.ninjarmm.com"
$env:NINJAONE_SCOPE = "monitoring management control"
$env:NINJA_MCP_APPROVAL_SECRET = "long-random-secret-held-by-the-approval-service"
$env:NINJA_MCP_LLM_BASE_URL = "http://127.0.0.1:52072/v1"
$env:NINJA_MCP_LLM_MODEL = "your-local-model-id"
python -m ninja_mcp
```

For MCP clients using stdio, launch `python -m ninja_mcp` with the same environment. Do not commit credentials or approval secrets.

## Correctness and pagination

- OpenAPI local `$ref` values are resolved, including nested schemas and parameter references. Circular/unresolved references are surfaced rather than silently treated as valid schemas.
- Required path/query parameters and required request bodies are checked before HTTP execution.
- Concrete raw paths are matched against OpenAPI templates and path values are URL-decoded then safely re-encoded.
- Large responses are marked `complete: false` and include truncation metadata. Use `execute_paginated_endpoint` when the OpenAPI schema documents page and page-size parameters; provide their exact names and, for envelope responses, the dotted `result_path`. The tool is bounded (maximum 20 pages, 200 items per page), and reports incomplete results if the page cap or response-size cap is reached. For cursor/offset or unusual pagination, call the endpoint manually using its documented query parameters. Never treat a truncated response as complete.
- GET requests may retry bounded transient failures and 429 responses. POST/PUT/PATCH are not automatically retried.

## Development

```powershell
python -m pytest
```
