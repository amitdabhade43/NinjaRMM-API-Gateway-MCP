#!/usr/bin/env python3
"""
NinjaOne RMM API Gateway MCP Server Implementation

This module implements a Model Context Protocol server that allows:
1. Searching for NinjaOne API endpoints
2. Executing API calls with parameters
3. Sending raw API requests
4. Storing and retrieving frequently used API queries in Fast Memory
"""

import os
import sys
import json
import re
import httpx
import asyncio
import time
import sqlite3
import logging
from typing import Dict, List, Optional, Any, Union
from mcp.server.fastmcp import FastMCP
from api_gateway.api_db_utils import APIDatabase
from api_gateway.fast_memory_db import FastMemoryDB

# Set up logging
log_dir = os.path.dirname(os.path.abspath(__file__))
log_file = os.path.join(log_dir, "ninjaone_api_gateway.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ninjaone_api_gateway")

# Initialize FastMCP server
mcp = FastMCP("NinjaRMM-API-Gateway-MCP")

# Global variables
NINJAONE_CLIENT_ID = None
NINJAONE_CLIENT_SECRET = None
NINJAONE_INSTANCE = None  # e.g., app.ninjarmm.com
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ninjaone_api.db")
FAST_MEMORY_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fast_memory_ninjaone.db")
api_db = None
fast_memory_db = None

# OAuth2 token cache
_token_cache = {"access_token": None, "expires_at": 0}

# Track if a query came from Fast Memory
current_query_from_fast_memory = False


class APIError(Exception):
    """Exception raised for API errors"""
    def __init__(self, message, status_code=None, response=None):
        self.message = message
        self.status_code = status_code
        self.response = response
        super().__init__(self.message)


# Initialization Functions

def setup_config():
    """Set up API configuration from environment variables"""
    global NINJAONE_CLIENT_ID, NINJAONE_CLIENT_SECRET, NINJAONE_INSTANCE

    NINJAONE_CLIENT_ID = os.environ.get('NINJAONE_CLIENT_ID')
    NINJAONE_CLIENT_SECRET = os.environ.get('NINJAONE_CLIENT_SECRET')
    NINJAONE_INSTANCE = os.environ.get('NINJAONE_INSTANCE', 'app.ninjarmm.com')

    logger.info("NinjaOne API Configuration:")
    logger.info(f"INSTANCE: {NINJAONE_INSTANCE}")
    logger.info(f"CLIENT_ID: {NINJAONE_CLIENT_ID}")
    logger.info(f"CLIENT_SECRET: {'*' * len(NINJAONE_CLIENT_SECRET) if NINJAONE_CLIENT_SECRET else 'Missing'}")

    if not all([NINJAONE_CLIENT_ID, NINJAONE_CLIENT_SECRET]):
        logger.error("NinjaOne API configuration incomplete. Please set NINJAONE_CLIENT_ID and NINJAONE_CLIENT_SECRET.")
        return False
    return True


def initialize_database():
    """Initialize the API database connection"""
    global api_db

    if not os.path.exists(DB_PATH):
        logger.error(f"Database file not found at {DB_PATH}")
        logger.error("Please run build_database.py script first to generate the database")
        return False

    try:
        api_db = APIDatabase(DB_PATH)
        logger.info("Connected to API database.")
        return True
    except sqlite3.Error as e:
        logger.error(f"Error connecting to database: {e}")
        return False


def initialize_fast_memory():
    """Initialize the Fast Memory database connection"""
    global fast_memory_db

    try:
        fast_memory_db = FastMemoryDB(FAST_MEMORY_DB_PATH)
        logger.info("Connected to Fast Memory database.")
        return True
    except sqlite3.Error as e:
        logger.error(f"Error connecting to Fast Memory database: {e}")
        return False


# OAuth2 Authentication

async def get_access_token() -> str:
    """Get OAuth2 access token, refreshing if expired."""
    global _token_cache

    # Return cached token if still valid (with 60s buffer)
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["access_token"]

    if not all([NINJAONE_CLIENT_ID, NINJAONE_CLIENT_SECRET, NINJAONE_INSTANCE]):
        if not setup_config():
            raise APIError("NinjaOne API configuration incomplete. Check environment variables.")

    token_url = f"https://{NINJAONE_INSTANCE}/oauth/token"
    logger.info(f"Requesting OAuth2 token from {token_url}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": NINJAONE_CLIENT_ID,
                    "client_secret": NINJAONE_CLIENT_SECRET,
                    "scope": "monitoring management control"
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            response.raise_for_status()
            token_data = response.json()

            _token_cache["access_token"] = token_data["access_token"]
            _token_cache["expires_at"] = time.time() + token_data.get("expires_in", 3600)
            logger.info("OAuth2 token obtained successfully.")
            return _token_cache["access_token"]

        except httpx.HTTPStatusError as e:
            error_msg = f"OAuth2 token request failed ({e.response.status_code}): {e.response.text}"
            logger.error(error_msg)
            raise APIError(error_msg, status_code=e.response.status_code)
        except Exception as e:
            error_msg = f"OAuth2 token request failed: {str(e)}"
            logger.error(error_msg)
            raise APIError(error_msg)


async def get_auth_header() -> Dict[str, str]:
    """Create authorization header for NinjaOne API"""
    token = await get_access_token()
    return {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }


async def make_api_request(
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None
) -> Any:
    """Make a request to the NinjaOne API"""
    if not NINJAONE_INSTANCE:
        if not setup_config():
            raise APIError("NinjaOne API not configured. Check environment variables.")

    url = f"https://{NINJAONE_INSTANCE}{endpoint}"
    if not headers:
        headers = await get_auth_header()

    logger.info(f"Making {method} request to: {url}")
    if params:
        logger.info(f"Params: {json.dumps(params)}")
    if data:
        logger.info(f"Data: {json.dumps(data)}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            if method.upper() == "GET":
                response = await client.get(url, headers=headers, params=params)
            elif method.upper() == "POST":
                response = await client.post(url, headers=headers, json=data)
            elif method.upper() == "PUT":
                response = await client.put(url, headers=headers, json=data)
            elif method.upper() == "PATCH":
                response = await client.patch(url, headers=headers, json=data)
            elif method.upper() == "DELETE":
                response = await client.delete(url, headers=headers)
            else:
                raise APIError(f"Unsupported HTTP method: {method}")

            logger.info(f"Response status: {response.status_code}")

            response.raise_for_status()
            return response.json() if response.content else {}

        except httpx.HTTPStatusError as e:
            error_message = f"HTTP error {e.response.status_code}: {e.response.text}"
            logger.error(error_message)
            raise APIError(error_message, status_code=e.response.status_code, response=e.response)
        except httpx.TimeoutException:
            logger.error("Request timed out.")
            raise APIError("Request timed out. NinjaOne API may be slow to respond.")
        except httpx.RequestError as e:
            logger.error(f"API request error: {str(e)}")
            raise APIError(f"API request failed: {str(e)}")
        except Exception as e:
            logger.error(f"Unknown error: {str(e)}")
            raise APIError(f"Unknown error: {str(e)}")


# Fast Memory Helper Functions

def check_fast_memory(path: str, method: str) -> Optional[Dict[str, Any]]:
    """Check if a query exists in Fast Memory."""
    global fast_memory_db, current_query_from_fast_memory

    if not fast_memory_db:
        if not initialize_fast_memory():
            logger.error("Failed to initialize Fast Memory database.")
            return None

    query = fast_memory_db.find_query(path, method)
    if query:
        current_query_from_fast_memory = True
        fast_memory_db.increment_usage(query['id'])
        logger.info(f"Found query in Fast Memory: {path} {method}")
        return query

    current_query_from_fast_memory = False
    return None


def format_endpoint_for_saving(method: str, path: str, params: Optional[Dict[str, Any]] = None, data: Optional[Dict[str, Any]] = None) -> str:
    """Format endpoint details for easy reference and saving."""
    formatted = f"Endpoint: {method.upper()} {path}\n"

    if params:
        formatted += "\nQuery Parameters:\n"
        formatted += json.dumps(params, indent=2)

    if data:
        formatted += "\nRequest Body:\n"
        formatted += json.dumps(data, indent=2)

    formatted += "\n\nTo save this endpoint to Fast Memory:"
    formatted += "\n```"
    formatted += f"\nsave_to_fast_memory("
    formatted += f"\n    path=\"{path}\","
    formatted += f"\n    method=\"{method}\","
    formatted += f"\n    description=\"YOUR DESCRIPTION HERE\","

    if params:
        formatted += f"\n    params={json.dumps(params)}"
    else:
        formatted += "\n    params=None"

    if data:
        formatted += f",\n    data={json.dumps(data)}"

    formatted += "\n)"
    formatted += "\n```"

    return formatted


# MCP Tool Implementations

@mcp.tool()
async def search_api_endpoints(query: str, max_results: int = 10) -> str:
    """
    Search for available API endpoints based on a query.

    Args:
        query: Search string to find matching endpoints
        max_results: Maximum number of results to return
    """
    if not api_db:
        if not initialize_database():
            return "Error: Failed to initialize API database."

    try:
        results = api_db.search_endpoints(query)

        if not results:
            return "No API endpoints found matching your query."

        formatted_results = []
        for i, endpoint in enumerate(results[:max_results], 1):
            method = endpoint.get('method', '').upper()
            path = endpoint.get('path', '')
            description = endpoint.get('description', 'No description available')

            formatted_results.append(f"{i}. {method} {path}\n   {description}")

        response = "Found the following API endpoints:\n\n"
        response += "\n\n".join(formatted_results)

        if len(results) > max_results:
            response += f"\n\nShowing {max_results} of {len(results)} results. Refine your search for more specific results."

        return response

    except Exception as e:
        logger.error(f"Error searching API endpoints: {str(e)}")
        return f"Error searching API endpoints: {str(e)}"


@mcp.tool()
async def get_api_endpoint_details(path: str, method: str = "GET") -> str:
    """
    Get detailed information about a specific API endpoint.

    Args:
        path: API path (e.g., /v2/devices)
        method: HTTP method (GET, POST, PUT, PATCH, DELETE)
    """
    if not api_db:
        if not initialize_database():
            return "Error: Failed to initialize API database."

    try:
        endpoint = api_db.find_endpoint_by_path_method(path, method)

        if not endpoint:
            return f"No API endpoint found for {method} {path}."

        formatted_details = api_db.format_endpoint_for_display(endpoint)
        return formatted_details
    except Exception as e:
        logger.error(f"Error getting API endpoint details: {str(e)}")
        return f"Error getting API endpoint details: {str(e)}"


@mcp.tool()
async def execute_api_call(
    path: str,
    method: str = "GET",
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None
) -> str:
    """
    Execute an API call to the NinjaOne API.

    Args:
        path: API endpoint path (e.g., /v2/devices)
        method: HTTP method (GET, POST, PUT, PATCH, DELETE)
        params: Query parameters for the request
        data: Request body data (for POST, PUT, PATCH)
    """
    global current_query_from_fast_memory

    if not api_db:
        if not initialize_database():
            return "Error: Failed to initialize API database."

    # Check Fast Memory first
    fast_memory_entry = check_fast_memory(path, method)
    if fast_memory_entry:
        if params is None and 'params' in fast_memory_entry and fast_memory_entry['params']:
            params = fast_memory_entry['params']
            logger.info(f"Using parameters from Fast Memory: {json.dumps(params)}")

        if data is None and 'data' in fast_memory_entry and fast_memory_entry['data']:
            data = fast_memory_entry['data']
            logger.info(f"Using data from Fast Memory: {json.dumps(data)}")

    try:
        # Verify the endpoint exists in our database
        endpoint = api_db.find_endpoint_by_path_method(path, method)
        if not endpoint:
            return f"Warning: No documented API endpoint found for {method} {path}. Proceeding with caution."

        # Execute the API call
        result = await make_api_request(method, path, params, data)

        # Format the response
        response = ""
        if isinstance(result, list):
            if len(result) > 10:
                summary = f"Retrieved {len(result)} items. Showing first 10:"
                formatted_data = json.dumps(result[:10], indent=2)
                response = f"{summary}\n\n{formatted_data}\n\n(Response truncated. Full response contained {len(result)} items.)"
            else:
                response = json.dumps(result, indent=2)
        else:
            response = json.dumps(result, indent=2)

        # Prompt to save if not from Fast Memory
        if not current_query_from_fast_memory:
            endpoint_details = format_endpoint_for_saving(method, path, params, data)
            response += f"\n\n=== SUCCESSFUL API CALL ===\n{endpoint_details}\n\nWould you like to save this query to Fast Memory for quicker access in the future? You can use the save_to_fast_memory function above or reply with a description."
        else:
            current_query_from_fast_memory = False
            response = f"[Using query from Fast Memory: {fast_memory_entry['description']}]\n\n" + response

        return response

    except APIError as e:
        current_query_from_fast_memory = False
        return f"API Error ({e.status_code if e.status_code else 'Unknown'}): {e.message}"
    except Exception as e:
        current_query_from_fast_memory = False
        logger.error(f"Error executing API call: {str(e)}")
        return f"Error executing API call: {str(e)}"


@mcp.tool()
async def natural_language_api_search(query: str, max_results: int = 5) -> str:
    """
    Search for API endpoints using natural language.

    Args:
        query: Natural language description of what you're looking for
        max_results: Maximum number of results to return
    """
    if not api_db:
        if not initialize_database():
            return "Error: Failed to initialize API database."

    try:
        results = api_db.search_by_natural_language(query, max_results)

        if not results:
            return "No API endpoints found matching your query."

        formatted_results = []
        for i, endpoint in enumerate(results, 1):
            method = endpoint.get('method', '').upper()
            path = endpoint.get('path', '')
            description = endpoint.get('description', 'No description available')
            category = endpoint.get('category', 'Unknown')

            formatted_results.append(
                f"{i}. {method} {path}\n"
                f"   Category: {category}\n"
                f"   Description: {description}"
            )

        response = "Based on your query, here are the most relevant API endpoints:\n\n"
        response += "\n\n".join(formatted_results)
        response += "\n\nTo get more details about a specific endpoint, use get_api_endpoint_details with the path and method."

        return response

    except Exception as e:
        logger.error(f"Error searching API endpoints: {str(e)}")
        return f"Error searching API endpoints: {str(e)}"


@mcp.tool()
async def list_api_categories() -> str:
    """
    List all available API categories.
    """
    if not api_db:
        if not initialize_database():
            return "Error: Failed to initialize API database."

    try:
        categories = api_db.get_categories()

        if not categories:
            return "No API categories found."

        response = "Available API categories:\n\n"
        response += "\n".join([f"- {category}" for category in categories])

        return response

    except Exception as e:
        logger.error(f"Error listing API categories: {str(e)}")
        return f"Error listing API categories: {str(e)}"


@mcp.tool()
async def get_category_endpoints(category: str, max_results: int = 20) -> str:
    """
    Get all endpoints for a specific API category.

    Args:
        category: Category name (use list_api_categories to see available categories)
        max_results: Maximum number of results to return
    """
    if not api_db:
        if not initialize_database():
            return "Error: Failed to initialize API database."

    try:
        endpoints = api_db.get_endpoints_by_category(category)

        if not endpoints:
            return f"No endpoints found for category: {category}"

        formatted_results = []
        for i, endpoint in enumerate(endpoints[:max_results], 1):
            method = endpoint.get('method', '').upper()
            path = endpoint.get('path', '')
            summary = endpoint.get('summary', 'No summary available')

            formatted_results.append(f"{i}. {method} {path}\n   {summary}")

        response = f"Endpoints in category '{category}':\n\n"
        response += "\n\n".join(formatted_results)

        if len(endpoints) > max_results:
            response += f"\n\nShowing {max_results} of {len(endpoints)} endpoints. Use a higher max_results value to see more."

        return response

    except Exception as e:
        logger.error(f"Error getting category endpoints: {str(e)}")
        return f"Error getting category endpoints: {str(e)}"


@mcp.tool()
async def send_raw_api_request(raw_request: str) -> str:
    """
    Send a raw API request to the NinjaOne API.

    Args:
        raw_request: Raw API request in the format "METHOD /path?params [JSON body]"
                     Example: "GET /v2/devices?df=class%20eq%20'WINDOWS_WORKSTATION'"
                     Example: "POST /v2/ticketing/ticket { \"summary\": \"Test ticket\" }"
    """
    if not setup_config():
        return "Error: Failed to initialize API configuration."

    try:
        parts = raw_request.strip().split(' ', 2)

        if len(parts) < 2:
            return "Error: Invalid request format. Use 'METHOD /path [JSON body]'"

        method = parts[0].upper()
        path_with_params = parts[1]

        if '?' in path_with_params:
            path, query_string = path_with_params.split('?', 1)
            params = {}
            for param in query_string.split('&'):
                if '=' in param:
                    key, value = param.split('=', 1)
                    params[key] = value
                else:
                    params[param] = ''
        else:
            path = path_with_params
            params = {}

        data = None
        if len(parts) > 2:
            try:
                data = json.loads(parts[2])
            except json.JSONDecodeError:
                return f"Error: Invalid JSON body: {parts[2]}"

        return await execute_api_call(path, method, params if params else None, data)

    except Exception as e:
        logger.error(f"Error executing raw API request: {str(e)}")
        return f"Error executing raw API request: {str(e)}"


@mcp.tool()
async def save_to_fast_memory(
    path: str,
    method: str,
    description: str,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None
) -> str:
    """
    Save an API query to Fast Memory.

    Args:
        path: API endpoint path
        method: HTTP method
        description: User-friendly description of the query
        params: Query parameters
        data: Request body data
    """
    if not fast_memory_db:
        if not initialize_fast_memory():
            return "Error: Failed to initialize Fast Memory database."

    try:
        query_id = fast_memory_db.save_query(description, path, method, params, data)
        return f"Successfully saved query to Fast Memory with ID {query_id}."
    except Exception as e:
        logger.error(f"Error saving query to Fast Memory: {str(e)}")
        return f"Error saving query to Fast Memory: {str(e)}"


@mcp.tool()
async def list_fast_memory(search_term: Optional[str] = None) -> str:
    """
    List queries saved in Fast Memory.

    Args:
        search_term: Optional search term to filter queries
    """
    if not fast_memory_db:
        if not initialize_fast_memory():
            return "Error: Failed to initialize Fast Memory database."

    try:
        if search_term:
            queries = fast_memory_db.search_queries(search_term)
            if not queries:
                return f"No queries found in Fast Memory matching '{search_term}'."
        else:
            queries = fast_memory_db.get_all_queries()
            if not queries:
                return "No queries saved in Fast Memory yet."

        formatted_queries = []
        for i, query in enumerate(queries, 1):
            params_str = json.dumps(query.get('params', {}), indent=2) if query.get('params') else "None"
            data_str = json.dumps(query.get('data', {}), indent=2) if query.get('data') else "None"

            if len(params_str) > 100:
                params_str = params_str[:100] + "... (truncated)"
            if len(data_str) > 100:
                data_str = data_str[:100] + "... (truncated)"

            formatted_queries.append(
                f"{i}. {query['description']}\n"
                f"   ID: {query['id']}\n"
                f"   Path: {query['method'].upper()} {query['path']}\n"
                f"   Usage Count: {query['usage_count']}\n"
                f"   Parameters: {params_str}\n"
                f"   Data: {data_str}"
            )

        response = "Queries saved in Fast Memory:\n\n"
        response += "\n\n".join(formatted_queries)

        response += "\n\nTo use a query from Fast Memory, use execute_api_call with the same path and method."
        response += "\nTo delete a query, use delete_from_fast_memory with the query ID."

        return response

    except Exception as e:
        logger.error(f"Error listing Fast Memory queries: {str(e)}")
        return f"Error listing Fast Memory queries: {str(e)}"


@mcp.tool()
async def delete_from_fast_memory(query_id: int) -> str:
    """
    Delete a query from Fast Memory.

    Args:
        query_id: ID of the query to delete
    """
    if not fast_memory_db:
        if not initialize_fast_memory():
            return "Error: Failed to initialize Fast Memory database."

    try:
        success = fast_memory_db.delete_query(query_id)
        if success:
            return f"Successfully deleted query with ID {query_id} from Fast Memory."
        else:
            return f"No query found with ID {query_id}."
    except Exception as e:
        logger.error(f"Error deleting query from Fast Memory: {str(e)}")
        return f"Error deleting query from Fast Memory: {str(e)}"


@mcp.tool()
async def clear_fast_memory() -> str:
    """
    Clear all queries from Fast Memory.
    """
    if not fast_memory_db:
        if not initialize_fast_memory():
            return "Error: Failed to initialize Fast Memory database."

    try:
        count = fast_memory_db.clear_all()
        return f"Successfully cleared {count} queries from Fast Memory."
    except Exception as e:
        logger.error(f"Error clearing Fast Memory: {str(e)}")
        return f"Error clearing Fast Memory: {str(e)}"


def main():
    """Main entry point for the server"""
    logger.info("Starting NinjaOne RMM API Gateway MCP Server...")
    setup_config()
    initialize_database()
    initialize_fast_memory()
    mcp.run(transport='stdio')


if __name__ == "__main__":
    main()
