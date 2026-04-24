"""Protect Claude's context from oversized API responses."""

from __future__ import annotations

import json
from typing import Any

MAX_BYTES = 100_000
MAX_ARRAY_ITEMS = 50


def truncate(data: Any) -> tuple[Any, bool]:
    """Return (possibly truncated data, truncated_flag).

    Strategy:
      - Under MAX_BYTES: unchanged.
      - Top-level list: first MAX_ARRAY_ITEMS + total count.
      - Dict with oversized array child: truncate that array in place.
      - Fallback: return a preview string.
    """
    try:
        serialized = json.dumps(data)
    except (TypeError, ValueError):
        return data, False

    if len(serialized) <= MAX_BYTES:
        return data, False

    if isinstance(data, list):
        truncated_items = data[:MAX_ARRAY_ITEMS]
        return {
            "_truncated": True,
            "_total_items": len(data),
            "_showing": len(truncated_items),
            "_hint": "Result set truncated. Use pagination (pageSize, cursor) or filters (df=) to narrow.",
            "items": truncated_items,
        }, True

    if isinstance(data, dict):
        for key, value in list(data.items()):
            if isinstance(value, list) and len(value) > MAX_ARRAY_ITEMS:
                new_data = dict(data)
                new_data[key] = value[:MAX_ARRAY_ITEMS]
                new_data["_truncated"] = True
                new_data["_total_items"] = len(value)
                new_data["_showing"] = MAX_ARRAY_ITEMS
                new_data["_hint"] = (
                    f"Array '{key}' truncated from {len(value)} to {MAX_ARRAY_ITEMS}"
                )
                return new_data, True

    return {
        "_truncated": True,
        "_hint": f"Response too large ({len(serialized)} bytes). Showing first 50KB.",
        "preview": serialized[:50_000],
    }, True
