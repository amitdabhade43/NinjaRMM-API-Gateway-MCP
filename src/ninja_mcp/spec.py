"""OpenAPI spec loader — in-memory index of NinjaOne endpoints."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HTTP_METHODS = frozenset({"get", "post", "put", "delete", "patch"})


@dataclass
class Endpoint:
    method: str
    path: str
    operation_id: str | None
    summary: str
    description: str
    category: str
    tags: list[str]
    parameters: list[dict[str, Any]] = field(default_factory=list)
    request_body: dict[str, Any] | None = None
    responses: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.method} {self.path}"

    @property
    def search_text(self) -> str:
        return " | ".join(
            [
                self.method,
                self.path,
                self.summary,
                self.description,
                " ".join(self.tags),
                self.category,
            ]
        )

    def to_summary(self) -> dict[str, Any]:
        return {
            "endpoint": self.key,
            "category": self.category,
            "summary": self.summary,
            "operation_id": self.operation_id,
        }

    def to_detail(self) -> dict[str, Any]:
        return {
            "endpoint": self.key,
            "method": self.method,
            "path": self.path,
            "operation_id": self.operation_id,
            "category": self.category,
            "summary": self.summary,
            "description": self.description,
            "tags": self.tags,
            "parameters": self.parameters,
            "request_body": self.request_body,
            "responses": self.responses,
        }


class Spec:
    def __init__(self, endpoints: list[Endpoint]):
        self.endpoints = endpoints
        self.by_key: dict[str, Endpoint] = {e.key: e for e in endpoints}
        self.by_category: dict[str, list[Endpoint]] = {}
        for e in endpoints:
            self.by_category.setdefault(e.category, []).append(e)

    @property
    def categories(self) -> list[str]:
        return sorted(self.by_category.keys())

    def get(self, endpoint: str) -> Endpoint | None:
        """Look up by 'METHOD /path'. Case-insensitive on method."""
        parts = endpoint.strip().split(None, 1)
        if len(parts) != 2:
            return None
        normalized = f"{parts[0].upper()} {parts[1]}"
        return self.by_key.get(normalized)

    @classmethod
    def load(cls, path: Path) -> Spec:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)

        endpoints: list[Endpoint] = []
        for url_path, operations in data.get("paths", {}).items():
            path_level_params = operations.get("parameters", []) or []
            for method, op in operations.items():
                if method.lower() not in HTTP_METHODS:
                    continue
                tags = op.get("tags", []) or []
                category = tags[0] if tags else "Uncategorized"
                merged_params = list(path_level_params) + list(op.get("parameters", []) or [])
                endpoints.append(
                    Endpoint(
                        method=method.upper(),
                        path=url_path,
                        operation_id=op.get("operationId"),
                        summary=op.get("summary", "") or "",
                        description=op.get("description", "") or "",
                        category=category,
                        tags=tags,
                        parameters=merged_params,
                        request_body=op.get("requestBody"),
                        responses=op.get("responses", {}) or {},
                    )
                )
        return cls(endpoints)
