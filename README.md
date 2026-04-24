# NinjaRMM API Gateway MCP Server

Model Context Protocol server giving Claude full access to the NinjaOne (Ninja RMM) API v2 — all **306 endpoints across 26 categories** — through a small set of discovery + execution tools.

## Design

- **Zero-build gateway.** The OpenAPI spec (`NinjaRMM-API-v2.json`) is loaded into memory at startup. No SQLite, no index build step — update the spec and restart.
- **7 focused tools** (not 306). Claude finds endpoints by fuzzy search, then calls them through a single `call` tool.
- **Async HTTP with connection pooling.** One `httpx.AsyncClient` per process; OAuth2 token cached in memory and refreshed ~60s before expiry.
- **Response protection.** Large payloads (NinjaOne device lists, etc.) are truncated before reaching the model context.
- **Structured output.** Tools return dicts, not stringified JSON.

## Setup

### 1. NinjaOne API credentials

In NinjaOne → **Administration → Apps → API**, create a new application with:

- Grant type: **Client Credentials**
- Scopes: `monitoring`, `management`, `control`

Save the Client ID and Client Secret.

### 2. Install

```bash
pip install -e .
```

### 3. Configure Claude

Add to your MCP client config:

```json
{
  "mcpServers": {
    "NinjaRMM-API-Gateway-MCP": {
      "command": "python",
      "args": ["-m", "ninja_mcp"],
      "env": {
        "NINJAONE_CLIENT_ID": "your-client-id",
        "NINJAONE_CLIENT_SECRET": "your-client-secret",
        "NINJAONE_INSTANCE": "app.ninjarmm.com"
      }
    }
  }
}
```

## Tools

| Tool | Purpose |
|---|---|
| `find_endpoint` | Fuzzy search endpoints. Filters: `query`, `category`, `method`. No args → list categories. |
| `describe_endpoint` | Full details (parameters, request body, responses) for one endpoint. |
| `call` | Execute a call. Pass `endpoint: "METHOD /path"`, `path_params`, `query`, `body`. |
| `raw_call` | Quick-form execution: `raw_call("GET /v2/devices?df=class eq 'WINDOWS_WORKSTATION'")`. |
| `memory_save` | Save a reusable call with a name; returns an `id`. |
| `memory_list` | List saved calls. |
| `memory_delete` | Delete by `id`, or `"*"` to clear all. |

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `NINJAONE_CLIENT_ID` | yes | — | OAuth2 Client ID |
| `NINJAONE_CLIENT_SECRET` | yes | — | OAuth2 Client Secret |
| `NINJAONE_INSTANCE` | no | `app.ninjarmm.com` | Regional instance (`eu.ninjarmm.com`, `ca.ninjarmm.com`, `oc.ninjarmm.com`) |
| `NINJA_MCP_SPEC` | no | bundled | Override path to OpenAPI JSON |
| `NINJA_MCP_HOME` | no | `~/.ninja-mcp` | Directory for persistent fast-memory store |
| `NINJA_MCP_LOG_LEVEL` | no | `INFO` | Python logging level (stderr only) |

## Updating the API spec

```bash
curl -o NinjaRMM-API-v2.json https://app.ninjarmm.com/apidocs/NinjaRMM-API-v2.json
```

Restart the server; changes are picked up on startup — no rebuild required.

## Development

```bash
pip install -e ".[dev]"
pytest
```

## Categories

System, Management, Queries, Devices, Knowledge Base Articles, Custom Tabs, Ticketing, Organization Checklists, Organization Documents, Related Items, Custom Fields, Document Templates, Asset Tags, Organizations, Checklist Templates, Software Licenses, Unmanaged Devices, Backup, Node Roles, Users, Vulnerability Management, Location, Webhooks, Groups, Billing, Asset Relationships.
