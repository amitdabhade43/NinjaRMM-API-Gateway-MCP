"""HMAC-signed, short-lived approvals for POST/PUT/PATCH execution.

The token is minted by a trusted approval UI/backend after a human approves.
Never expose NINJA_MCP_APPROVAL_SECRET to the model or MCP client.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

class ApprovalError(ValueError):
    pass

_USED_APPROVALS: dict[str, int] = {}
_MAX_USED_APPROVALS = 10000

def body_digest(body: Any) -> str:
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()

def verify_approval(token: str | None, method: str, path: str, body: Any) -> None:
    secret = os.getenv("NINJA_MCP_APPROVAL_SECRET", "")
    if not secret:
        raise ApprovalError("Write operations are disabled: approval service is not configured.")
    if not token:
        raise ApprovalError("Human approval is required for this write operation.")
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
        supplied = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        if not hmac.compare_digest(expected, supplied):
            raise ApprovalError("Approval token signature is invalid.")
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    except ApprovalError:
        raise
    except Exception as exc:
        raise ApprovalError("Approval token is malformed.") from exc

    now = int(time.time())
    expires = int(payload.get("exp", 0))
    if expires < now:
        raise ApprovalError("Approval token has expired.")
    token_id = payload.get("jti")
    if not isinstance(token_id, str) or not token_id:
        raise ApprovalError("Approval token is missing its unique jti.")

    # Process-local replay defence. A production approval service should also
    # persist consumed jti values so a gateway restart cannot make a token reusable.
    for old_id, old_expiry in list(_USED_APPROVALS.items()):
        if old_expiry < now:
            _USED_APPROVALS.pop(old_id, None)
    if token_id in _USED_APPROVALS:
        raise ApprovalError("Approval token has already been used.")
    if len(_USED_APPROVALS) >= _MAX_USED_APPROVALS:
        raise ApprovalError("Approval replay cache is full; refusing write execution.")

    expected_fields = (method.upper(), path, body_digest(body))
    actual_fields = (payload.get("method"), payload.get("path"), payload.get("body_sha256"))
    if actual_fields != expected_fields:
        raise ApprovalError("Approval token does not match this method, path and request body.")
    _USED_APPROVALS[token_id] = expires
