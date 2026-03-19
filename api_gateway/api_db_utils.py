#!/usr/bin/env python3
"""
API Database Utility Functions

This module provides utility functions to query the SQLite database containing
the NinjaOne RMM API endpoint information.
"""

import sqlite3
import json
from typing import Dict, List, Any, Optional, Union, Tuple

class APIDatabase:
    """Class to handle queries to the NinjaOne API SQLite database."""

    def __init__(self, db_path: str):
        """Initialize the database connection."""
        self.db_path = db_path
        self.conn = None
        self.connect()

    def connect(self) -> None:
        """Establish a connection to the SQLite database."""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        """Close the database connection."""
        if self.conn:
            self.conn.close()

    def search_endpoints(self, query: str) -> List[Dict[str, Any]]:
        """
        Search for API endpoints matching the query.

        Args:
            query: Search string (can match path, description, tags)

        Returns:
            List of matching endpoints
        """
        if not self.conn:
            self.connect()

        cursor = self.conn.cursor()
        search_pattern = f"%{query}%"

        cursor.execute('''
        SELECT * FROM endpoints
        WHERE path LIKE ?
        OR description LIKE ?
        OR tags LIKE ?
        OR summary LIKE ?
        ORDER BY category, path
        ''', (search_pattern, search_pattern, search_pattern, search_pattern))

        results = []
        for row in cursor.fetchall():
            results.append(dict(row))

        return results

    def get_endpoint_details(self, endpoint_id: int) -> Dict[str, Any]:
        """
        Get complete details for a specific endpoint.

        Args:
            endpoint_id: ID of the endpoint

        Returns:
            Dictionary with endpoint details including parameters and response info
        """
        if not self.conn:
            self.connect()

        cursor = self.conn.cursor()

        cursor.execute('SELECT * FROM endpoints WHERE id = ?', (endpoint_id,))
        endpoint = dict(cursor.fetchone() or {})

        if not endpoint:
            return {}

        # Get parameters
        cursor.execute('SELECT * FROM parameters WHERE endpoint_id = ?', (endpoint_id,))
        endpoint['parameters'] = [dict(row) for row in cursor.fetchall()]

        # Get request body
        cursor.execute('SELECT * FROM request_bodies WHERE endpoint_id = ?', (endpoint_id,))
        request_body = cursor.fetchone()
        if request_body:
            endpoint['request_body'] = dict(request_body)
            if endpoint['request_body'].get('schema'):
                try:
                    endpoint['request_body']['schema'] = json.loads(endpoint['request_body']['schema'])
                except json.JSONDecodeError:
                    pass
            if endpoint['request_body'].get('example'):
                try:
                    endpoint['request_body']['example'] = json.loads(endpoint['request_body']['example'])
                except json.JSONDecodeError:
                    pass

        # Get response bodies
        cursor.execute('SELECT * FROM response_bodies WHERE endpoint_id = ?', (endpoint_id,))
        responses = []
        for row in cursor.fetchall():
            response = dict(row)
            if response.get('schema'):
                try:
                    response['schema'] = json.loads(response['schema'])
                except json.JSONDecodeError:
                    pass
            if response.get('example'):
                try:
                    response['example'] = json.loads(response['example'])
                except json.JSONDecodeError:
                    pass
            responses.append(response)

        endpoint['responses'] = responses

        return endpoint

    def find_endpoint_by_path_method(self, path: str, method: str) -> Optional[Dict[str, Any]]:
        """
        Find an endpoint by its path and HTTP method.

        Args:
            path: API path (e.g., /v2/devices)
            method: HTTP method (get, post, put, patch, delete)

        Returns:
            Endpoint details or None if not found
        """
        if not self.conn:
            self.connect()

        cursor = self.conn.cursor()

        cursor.execute('''
        SELECT id FROM endpoints
        WHERE path = ? AND method = ?
        ''', (path, method.lower()))

        result = cursor.fetchone()
        if not result:
            return None

        return self.get_endpoint_details(result['id'])

    def get_categories(self) -> List[str]:
        """
        Get a list of all API categories.

        Returns:
            List of category names
        """
        if not self.conn:
            self.connect()

        cursor = self.conn.cursor()
        cursor.execute('SELECT DISTINCT category FROM endpoints ORDER BY category')
        return [row['category'] for row in cursor.fetchall()]

    def get_endpoints_by_category(self, category: str) -> List[Dict[str, Any]]:
        """
        Get all endpoints for a specific category.

        Args:
            category: Category name

        Returns:
            List of endpoints in that category
        """
        if not self.conn:
            self.connect()

        cursor = self.conn.cursor()

        cursor.execute('''
        SELECT * FROM endpoints
        WHERE category = ?
        ORDER BY path
        ''', (category,))

        return [dict(row) for row in cursor.fetchall()]

    def get_parameter_details(self, endpoint_id: int, param_name: str) -> Optional[Dict[str, Any]]:
        """
        Get details for a specific parameter of an endpoint.
        """
        if not self.conn:
            self.connect()

        cursor = self.conn.cursor()

        cursor.execute('''
        SELECT * FROM parameters
        WHERE endpoint_id = ? AND name = ?
        ''', (endpoint_id, param_name))

        result = cursor.fetchone()
        return dict(result) if result else None

    def search_by_natural_language(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Search for endpoints using natural language queries.

        Args:
            query: Natural language query
            limit: Maximum number of results

        Returns:
            List of matching endpoints
        """
        if not self.conn:
            self.connect()

        keywords = query.lower().split()
        common_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'with', 'by', 'about', 'like', 'from'}
        keywords = [word for word in keywords if word not in common_words]

        results = []
        if not keywords:
            return results

        for keyword in keywords:
            if len(keyword) < 3:
                continue

            search_pattern = f"%{keyword}%"
            cursor = self.conn.cursor()

            cursor.execute('''
            SELECT id, path, method, description, category
            FROM endpoints
            WHERE path LIKE ?
            OR description LIKE ?
            OR tags LIKE ?
            OR summary LIKE ?
            LIMIT ?
            ''', (search_pattern, search_pattern, search_pattern, search_pattern, limit))

            for row in cursor.fetchall():
                endpoint = dict(row)
                if endpoint not in results:
                    results.append(endpoint)

        def score_endpoint(endpoint):
            score = 0
            for keyword in keywords:
                if keyword in endpoint.get('path', '').lower():
                    score += 3
                if keyword in endpoint.get('description', '').lower():
                    score += 2
                if keyword in endpoint.get('tags', '').lower():
                    score += 1
            return score

        results.sort(key=score_endpoint, reverse=True)

        return results[:limit]

    def format_endpoint_for_display(self, endpoint: Dict[str, Any]) -> str:
        """
        Format an endpoint for display in a user-friendly way.
        """
        formatted = []

        method = endpoint.get('method', '').upper()
        path = endpoint.get('path', '')
        description = endpoint.get('description', '')

        formatted.append(f"{method} {path}")
        if description:
            formatted.append(f"Description: {description}")

        if 'parameters' in endpoint and endpoint['parameters']:
            formatted.append("\nParameters:")
            for param in endpoint['parameters']:
                name = param.get('name', '')
                location = param.get('location', '')
                required = "Required" if param.get('required') == 1 else "Optional"
                param_type = param.get('type', '')
                param_desc = param.get('description', '')

                formatted.append(f"  - {name} ({location}, {required}, {param_type}): {param_desc}")

        if 'request_body' in endpoint and endpoint['request_body']:
            formatted.append("\nRequest Body:")
            schema = endpoint['request_body'].get('schema', {})
            if isinstance(schema, dict) and schema:
                formatted.append(f"  Schema: {json.dumps(schema, indent=2)}")

            example = endpoint['request_body'].get('example', {})
            if isinstance(example, dict) and example:
                formatted.append(f"  Example: {json.dumps(example, indent=2)}")

        if 'responses' in endpoint and endpoint['responses']:
            formatted.append("\nResponses:")
            for response in endpoint['responses']:
                status = response.get('status_code', '')
                desc = response.get('description', '')
                formatted.append(f"  - {status}: {desc}")

        return "\n".join(formatted)
