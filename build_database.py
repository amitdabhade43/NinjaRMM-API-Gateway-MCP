#!/usr/bin/env python3
"""
Build the NinjaOne API SQLite database from the OpenAPI JSON spec.

Usage:
    python build_database.py
"""

import os
import sys

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api_gateway.json_to_sqlite import process_json_file

def main():
    project_root = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(project_root, "NinjaRMM-API-v2.json")
    db_path = os.path.join(project_root, "api_gateway", "ninjaone_api.db")

    if not os.path.exists(json_path):
        print(f"Error: API spec not found at {json_path}")
        print("Please place NinjaRMM-API-v2.json in the project root.")
        sys.exit(1)

    # Remove existing database if present
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"Removed existing database: {db_path}")

    print(f"Building database from: {json_path}")
    print(f"Output: {db_path}")
    print()

    process_json_file(json_path, db_path)

if __name__ == "__main__":
    main()
