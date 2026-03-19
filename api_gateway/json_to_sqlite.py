#!/usr/bin/env python3
"""
JSON to SQLite Converter for NinjaOne RMM API

This script converts the NinjaRMM-API-v2.json OpenAPI specification
into a SQLite database for efficient querying and lookup.

Usage:
    python json_to_sqlite.py <path_to_api_json> <output_sqlite_db>
"""

import json
import sqlite3
import sys
import os
import time
from typing import Dict, List, Any, Optional, Union

def create_tables(conn: sqlite3.Connection) -> None:
    """Create the necessary tables in the SQLite database."""
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS endpoints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT NOT NULL,
        method TEXT NOT NULL,
        description TEXT,
        category TEXT,
        summary TEXT,
        tags TEXT,
        UNIQUE(path, method)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS parameters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        endpoint_id INTEGER,
        name TEXT NOT NULL,
        location TEXT NOT NULL,
        required INTEGER,
        type TEXT,
        description TEXT,
        FOREIGN KEY (endpoint_id) REFERENCES endpoints (id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS request_bodies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        endpoint_id INTEGER,
        schema TEXT,
        example TEXT,
        FOREIGN KEY (endpoint_id) REFERENCES endpoints (id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS response_bodies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        endpoint_id INTEGER,
        status_code TEXT,
        description TEXT,
        schema TEXT,
        example TEXT,
        FOREIGN KEY (endpoint_id) REFERENCES endpoints (id)
    )
    ''')

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_endpoints_path ON endpoints(path)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_endpoints_method ON endpoints(method)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_endpoints_tags ON endpoints(tags)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_endpoints_category ON endpoints(category)')

    conn.commit()

def resolve_ref(spec: dict, ref: str) -> dict:
    """Resolve a $ref pointer in the OpenAPI spec."""
    if not ref.startswith('#/'):
        return {}
    parts = ref[2:].split('/')
    obj = spec
    for part in parts:
        obj = obj.get(part, {})
    return obj

def resolve_schema(spec: dict, schema: dict, depth: int = 0, max_depth: int = 3, seen_refs: set = None) -> dict:
    """Recursively resolve $ref in a schema object, with depth limit to avoid circular refs."""
    if seen_refs is None:
        seen_refs = set()
    if not isinstance(schema, dict):
        return schema
    if depth > max_depth:
        return schema
    if '$ref' in schema:
        ref = schema['$ref']
        if ref in seen_refs:
            return {"$ref": ref, "_note": "circular reference"}
        seen_refs = seen_refs | {ref}
        resolved = resolve_ref(spec, ref)
        return resolve_schema(spec, resolved, depth + 1, max_depth, seen_refs)
    result = {}
    for key, value in schema.items():
        if isinstance(value, dict):
            result[key] = resolve_schema(spec, value, depth + 1, max_depth, seen_refs)
        elif isinstance(value, list):
            result[key] = [resolve_schema(spec, item, depth + 1, max_depth, seen_refs) if isinstance(item, dict) else item for item in value]
        else:
            result[key] = value
    return result

def process_json_file(json_path: str, db_path: str) -> None:
    """Process the NinjaOne API JSON file and store the data in SQLite."""
    print(f"Starting processing of: {json_path}")
    start_time = time.time()

    conn = sqlite3.connect(db_path)
    create_tables(conn)
    cursor = conn.cursor()

    print("Opening JSON file...")
    with open(json_path, 'r') as f:
        try:
            print("Parsing JSON data...")
            api_data = json.load(f)
            print(f"JSON parsed successfully. Processing...")
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON: {e}")
            conn.close()
            return

    if 'paths' not in api_data:
        print("Error: 'paths' key not found in JSON data.")
        conn.close()
        return

    paths = api_data['paths']
    total_paths = len(paths)
    processed = 0
    endpoint_count = 0

    for path, path_data in paths.items():
        for method, method_data in path_data.items():
            if method in ['get', 'post', 'put', 'patch', 'delete']:
                description = method_data.get('description', '')
                summary = method_data.get('summary', '')
                tags = ','.join(method_data.get('tags', []))

                category = method_data.get('tags', [''])[0] if method_data.get('tags') else path.split('/')[1] if len(path.split('/')) > 1 else 'unknown'

                cursor.execute('''
                INSERT OR REPLACE INTO endpoints (path, method, description, category, summary, tags)
                VALUES (?, ?, ?, ?, ?, ?)
                ''', (path, method, description, category, summary, tags))

                endpoint_id = cursor.lastrowid
                endpoint_count += 1

                # Process parameters (including inherited from path level)
                parameters = method_data.get('parameters', [])
                # Also check path-level parameters
                path_params = path_data.get('parameters', [])
                all_params = path_params + parameters

                for param in all_params:
                    # Resolve $ref if present
                    if '$ref' in param:
                        param = resolve_ref(api_data, param['$ref'])

                    name = param.get('name', '')
                    location = param.get('in', '')
                    required = 1 if param.get('required', False) else 0

                    param_schema = param.get('schema', {})
                    if '$ref' in param_schema:
                        param_schema = resolve_ref(api_data, param_schema['$ref'])
                    param_type = param_schema.get('type', '') if isinstance(param_schema, dict) else ''

                    param_description = param.get('description', '')

                    cursor.execute('''
                    INSERT INTO parameters (endpoint_id, name, location, required, type, description)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''', (endpoint_id, name, location, required, param_type, param_description))

                # Process request body
                if 'requestBody' in method_data:
                    request_body = method_data['requestBody']
                    # Resolve $ref on request body itself
                    if '$ref' in request_body:
                        request_body = resolve_ref(api_data, request_body['$ref'])

                    content = request_body.get('content', {})
                    content_type = next(iter(content)) if content else ''

                    schema = {}
                    example = {}
                    if content_type and content_type in content:
                        raw_schema = content[content_type].get('schema', {})
                        # Resolve one level of $ref for schemas
                        schema = resolve_schema(api_data, raw_schema) if raw_schema else {}
                        example = content[content_type].get('example', {})

                    cursor.execute('''
                    INSERT INTO request_bodies (endpoint_id, schema, example)
                    VALUES (?, ?, ?)
                    ''', (endpoint_id, json.dumps(schema), json.dumps(example)))

                # Process responses
                responses = method_data.get('responses', {})
                for status_code, response_data in responses.items():
                    # Resolve $ref on response
                    if '$ref' in response_data:
                        response_data = resolve_ref(api_data, response_data['$ref'])

                    resp_description = response_data.get('description', '')
                    content = response_data.get('content', {})
                    content_type = next(iter(content)) if content else ''

                    schema = {}
                    example = {}
                    if content_type and content_type in content:
                        raw_schema = content[content_type].get('schema', {})
                        schema = resolve_schema(api_data, raw_schema) if raw_schema else {}
                        example = content[content_type].get('example', {})

                    cursor.execute('''
                    INSERT INTO response_bodies (endpoint_id, status_code, description, schema, example)
                    VALUES (?, ?, ?, ?, ?)
                    ''', (endpoint_id, status_code, resp_description, json.dumps(schema), json.dumps(example)))

        processed += 1
        if processed % 50 == 0:
            print(f"Processed {processed}/{total_paths} paths ({(processed/total_paths)*100:.1f}%)...")
            conn.commit()

    conn.commit()
    conn.close()

    elapsed_time = time.time() - start_time
    print(f"\nProcessing completed in {elapsed_time:.2f} seconds.")
    print(f"Total endpoints stored: {endpoint_count}")
    print(f"Database created at: {db_path}")

def main():
    if len(sys.argv) < 3:
        print("Usage: python json_to_sqlite.py <path_to_api_json> <output_sqlite_db>")
        sys.exit(1)

    json_path = sys.argv[1]
    db_path = sys.argv[2]

    if not os.path.exists(json_path):
        print(f"Error: JSON file does not exist at path: {json_path}")
        sys.exit(1)

    process_json_file(json_path, db_path)

if __name__ == "__main__":
    main()
