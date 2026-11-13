"""Download and validate NinjaOne's official Public API v2 OpenAPI document.

Run from the repository root:
    .\\.venv\\Scripts\\python.exe .\\scripts\\sync_openapi_spec.py
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "https://app.ninjarmm.com/apidocs/NinjaRMM-API-v2.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download NinjaOne's official Public API v2 OpenAPI document."
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="Official OpenAPI JSON URL.")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "NinjaRMM-API-v2.json",
        help="Output path (defaults to the gateway repository root).",
    )
    args = parser.parse_args()

    request = urllib.request.Request(
        args.url,
        headers={"User-Agent": "NinjaOne-API-Gateway-MCP OpenAPI sync"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            document = json.loads(response.read().decode("utf-8-sig"))
        if not isinstance(document, dict) or not isinstance(document.get("paths"), dict):
            raise ValueError("Downloaded document is not an OpenAPI document with a paths object.")
        info = document.get("info") or {}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"ERROR: Could not download or validate NinjaOne OpenAPI JSON: {exc}", file=sys.stderr)
        return 1

    print(f"Created: {args.output}")
    print(f"API: {info.get('title', 'NinjaOne Public API')}")
    print(f"Version: {info.get('version', 'unknown')}")
    print(f"Paths: {len(document['paths'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
