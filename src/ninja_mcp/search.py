"""Weighted fuzzy endpoint retrieval; semantic ranking is layered on top."""
from __future__ import annotations
import re
from rapidfuzz import fuzz
from .spec import Endpoint, Spec

STOP_WORDS = {"the", "a", "an", "please", "show", "me", "get", "find", "list", "all", "of", "for"}

def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOP_WORDS]

def score_endpoint(query: str, endpoint: Endpoint) -> float:
    q = " ".join(_tokens(query))
    if not q:
        return 0.0
    path = fuzz.token_set_ratio(q, endpoint.path.replace("/", " ").replace("{", " ").replace("}", " "))
    summary = fuzz.token_set_ratio(q, endpoint.summary)
    description = fuzz.token_set_ratio(q, endpoint.description[:1200])
    tags = fuzz.token_set_ratio(q, " ".join(endpoint.tags + [endpoint.category]))
    operation = fuzz.token_set_ratio(q, endpoint.operation_id or "")
    # Prefer explicit operation summaries and identifiers over long descriptions.
    return round(max(path * .30 + summary * .35 + tags * .20 + operation * .15,
                     summary * .30 + description * .25 + tags * .20 + path * .15 + operation * .10), 2)

def search(spec: Spec, query: str = "", *, category: str | None = None,
           method: str | None = None, limit: int = 20) -> list[Endpoint]:
    candidates = spec.endpoints
    if category:
        candidates = [e for e in candidates if e.category.casefold() == category.casefold()]
    if method:
        candidates = [e for e in candidates if e.method == method.upper()]
    if not query.strip():
        return candidates[:max(1, min(limit, 100))]
    ranked = sorted(((score_endpoint(query, e), e) for e in candidates),
                    key=lambda pair: pair[0], reverse=True)
    return [e for score, e in ranked[:max(1, min(limit, 100))] if score >= 15]
