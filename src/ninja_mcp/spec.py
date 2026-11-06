"""OpenAPI loader with local $ref resolution and endpoint metadata."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HTTP_METHODS = frozenset({"get", "post", "put", "patch"})

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
    deprecated: bool = False

    @property
    def key(self) -> str:
        return f"{self.method} {self.path}"

    @property
    def search_text(self) -> str:
        return " | ".join([self.method, self.path, self.operation_id or "", self.summary,
                           self.description, " ".join(self.tags), self.category])

    def to_summary(self) -> dict[str, Any]:
        return {"endpoint": self.key, "method": self.method, "path": self.path,
                "category": self.category, "summary": self.summary,
                "operation_id": self.operation_id, "deprecated": self.deprecated}

    def to_detail(self) -> dict[str, Any]:
        return {**self.to_summary(), "description": self.description, "tags": self.tags,
                "parameters": self.parameters, "request_body": self.request_body,
                "responses": self.responses}

class Spec:
    def __init__(self, endpoints: list[Endpoint]):
        self.endpoints = endpoints
        self.by_key = {e.key: e for e in endpoints}
        self.by_category: dict[str, list[Endpoint]] = {}
        for endpoint in endpoints:
            self.by_category.setdefault(endpoint.category, []).append(endpoint)

    @property
    def categories(self) -> list[str]:
        return sorted(self.by_category)

    def get(self, endpoint: str) -> Endpoint | None:
        parts = endpoint.strip().split(None, 1)
        if len(parts) != 2:
            return None
        return self.by_key.get(f"{parts[0].upper()} {parts[1]}")

    @classmethod
    def load(cls, path: Path) -> "Spec":
        with path.open(encoding="utf-8") as stream:
            document = json.load(stream)

        def resolve(value: Any, stack: tuple[str, ...] = ()) -> Any:
            if isinstance(value, list):
                return [resolve(item, stack) for item in value]
            if not isinstance(value, dict):
                return value
            ref = value.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/"):
                if ref in stack:
                    return {"$ref": ref, "description": "Circular reference"}
                target: Any = document
                try:
                    for part in ref[2:].split("/"):
                        target = target[part.replace("~1", "/").replace("~0", "~")]
                except (KeyError, TypeError):
                    return {"$ref": ref, "description": "Unresolved OpenAPI reference"}
                resolved = resolve(target, stack + (ref,))
                siblings = {k: v for k, v in value.items() if k != "$ref"}
                if isinstance(resolved, dict):
                    return {**resolved, **resolve(siblings, stack)}
                return resolved
            return {key: resolve(item, stack) for key, item in value.items()}

        paths = document.get("paths", {})
        endpoints: list[Endpoint] = []
        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            path_parameters = resolve(path_item.get("parameters", []) or [])
            for method, raw_operation in path_item.items():
                if method.lower() not in HTTP_METHODS or not isinstance(raw_operation, dict):
                    continue
                operation = resolve(raw_operation)
                tags = operation.get("tags") or []
                params = list(path_parameters) + list(operation.get("parameters") or [])
                # Merge path-level and operation-level parameter overrides by (name, in).
                merged: dict[tuple[str, str], dict[str, Any]] = {}
                for parameter in params:
                    if isinstance(parameter, dict):
                        merged[(str(parameter.get("name", "")), str(parameter.get("in", "")))] = parameter
                endpoints.append(Endpoint(
                    method=method.upper(), path=path,
                    operation_id=operation.get("operationId"),
                    summary=operation.get("summary") or "",
                    description=operation.get("description") or "",
                    category=tags[0] if tags else "Uncategorized",
                    tags=tags, parameters=list(merged.values()),
                    request_body=operation.get("requestBody"),
                    responses=operation.get("responses") or {},
                    deprecated=bool(operation.get("deprecated", False)),
                ))
        return cls(endpoints)
