"""Fuzzy search across the OpenAPI index.

Scoring combines per-token substring hits (dominant signal — catches
"reboot device" landing on `/v2/device/{id}/reboot/{mode}`) with a
partial-ratio fuzzy fallback for typo tolerance.
"""

from __future__ import annotations

from rapidfuzz import fuzz

from .spec import Endpoint, Spec


def _score(query_lower: str, query_tokens: list[str], target: str) -> float:
    t = target.lower()
    if query_tokens:
        hits = sum(1 for tok in query_tokens if tok in t)
        token_score = (hits / len(query_tokens)) * 100.0
    else:
        token_score = 0.0
    fuzzy_score = max(
        fuzz.partial_ratio(query_lower, t),
        fuzz.token_set_ratio(query_lower, t),
    )
    # Heavy bias to token-presence; fuzzy only wins for typos.
    return max(token_score, fuzzy_score * 0.75)


def search(
    spec: Spec,
    query: str = "",
    *,
    category: str | None = None,
    method: str | None = None,
    limit: int = 10,
) -> list[Endpoint]:
    candidates = spec.endpoints
    if category:
        cat_lower = category.lower()
        candidates = [e for e in candidates if e.category.lower() == cat_lower]
    if method:
        m = method.upper()
        candidates = [e for e in candidates if e.method == m]

    if not query.strip():
        return candidates[:limit]

    q_lower = query.lower()
    q_tokens = [t for t in q_lower.split() if t]
    scored = [
        (_score(q_lower, q_tokens, e.search_text), e) for e in candidates
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [e for score, e in scored[:limit] if score > 0]
