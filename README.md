# NinjaRMM API Gateway MCP Server

A Model Context Protocol (MCP) server that provides full access to the NinjaOne (Ninja RMM) API v2 through Claude Code. Uses a database-backed gateway pattern for 100% API coverage with 306 endpoints across 26 categories.

## Features

- **Full API Coverage**: All 306 NinjaOne API v2 endpoints indexed in a searchable SQLite database
- **Smart Discovery**: Search endpoints by keyword, natural language, or browse by category
- **Fast Memory**: Save and reuse frequently-used API queries
- **OAuth2 Authentication**: Automatic token management with client credentials flow
- **Raw Request Support**: Send raw API requests in `METHOD /path` format

## Setup

### 1. Create NinjaOne API Credentials

1. Log into NinjaOne (app.ninjarmm.com)
2. Go to **Administration > Apps > API**
3. Create a new API application with **Client Credentials** grant type
4. Enable scopes: `monitoring`, `management`, `control`
5. Save the **Client ID** and **Client Secret**

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Build the API Database (if not already built)

```bash
python build_database.py
```

### 4. Configure Claude Code

Add to your Claude Code MCP settings:

```json
{
  "mcpServers": {
    "NinjaRMM-API-Gateway-MCP": {
      "command": "python",
      "args": ["C:/Users/jd656/NinjaRMM-API-Gateway-MCP/ninjaone_api_gateway_server.py"],
      "env": {
        "NINJAONE_CLIENT_ID": "your-client-id",
        "NINJAONE_CLIENT_SECRET": "your-client-secret",
        "NINJAONE_INSTANCE": "app.ninjarmm.com"
      }
    }
  }
}
```

## Available Tools

| Tool | Description |
|------|-------------|
| `search_api_endpoints` | Full-text search across all API endpoints |
| `get_api_endpoint_details` | Get detailed info for a specific endpoint (params, schemas, responses) |
| `execute_api_call` | Execute an API call with automatic Fast Memory integration |
| `natural_language_api_search` | Search endpoints using natural language |
| `list_api_categories` | List all 26 API categories |
| `get_category_endpoints` | Browse endpoints within a category |
| `send_raw_api_request` | Send raw requests (e.g., `GET /v2/devices`) |
| `save_to_fast_memory` | Save a query for quick reuse |
| `list_fast_memory` | List saved queries |
| `delete_from_fast_memory` | Delete a saved query |
| `clear_fast_memory` | Clear all saved queries |

## API Categories

System, Management, Queries, Devices, Knowledge Base Articles, Custom Tabs, Ticketing, Organization Checklists, Organization Documents, Related Items, Custom Fields, Document Templates, Asset Tags, Organizations, Checklist Templates, Software Licenses, Unmanaged Devices, Backup, Node Roles, Users, Vulnerability Management, Location, Webhooks, Groups, Billing, Asset Relationships

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NINJAONE_CLIENT_ID` | Yes | - | OAuth2 Client ID |
| `NINJAONE_CLIENT_SECRET` | Yes | - | OAuth2 Client Secret |
| `NINJAONE_INSTANCE` | No | `app.ninjarmm.com` | Regional instance URL |

## Rebuilding the Database

If the NinjaOne API spec is updated, download the new spec and rebuild:

```bash
# Download updated spec
curl -o NinjaRMM-API-v2.json https://app.ninjarmm.com/apidocs/NinjaRMM-API-v2.json

# Rebuild database
python build_database.py
```
