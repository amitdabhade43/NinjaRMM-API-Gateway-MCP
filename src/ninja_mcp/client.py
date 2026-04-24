"""Async NinjaOne client: OAuth token caching, connection pool, retry on 429."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

TOKEN_REFRESH_MARGIN_S = 60
DEFAULT_TIMEOUT_S = 30.0
MAX_RETRIES = 3


class NinjaAuthError(Exception):
    pass


class NinjaAPIError(Exception):
    def __init__(self, message: str, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class NinjaClient:
    """Thread-safe async client for NinjaOne v2 API.

    One instance per process; maintains a pooled httpx.AsyncClient and
    caches the OAuth2 token until ~60s before expiry.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        instance: str = "app.ninjarmm.com",
        scope: str = "monitoring management control",
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = f"https://{instance}"
        self.scope = scope
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._token_lock = asyncio.Lock()
        self._http = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT_S,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _ensure_token(self, force: bool = False) -> str:
        if not force and self._token and time.time() < self._expires_at - TOKEN_REFRESH_MARGIN_S:
            return self._token
        async with self._token_lock:
            if not force and self._token and time.time() < self._expires_at - TOKEN_REFRESH_MARGIN_S:
                return self._token
            resp = await self._http.post(
                f"{self.base_url}/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": self.scope,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code != 200:
                raise NinjaAuthError(
                    f"OAuth2 token request failed ({resp.status_code}): {resp.text[:500]}"
                )
            payload = resp.json()
            self._token = payload["access_token"]
            self._expires_at = time.time() + int(payload.get("expires_in", 3600))
            log.info("OAuth2 token refreshed; expires in %ss", payload.get("expires_in"))
            return self._token

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        last_resp: httpx.Response | None = None

        for attempt in range(MAX_RETRIES):
            token = await self._ensure_token()
            resp = await self._http.request(
                method.upper(),
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                params=params,
                json=json_body,
            )
            last_resp = resp

            if resp.status_code == 401 and attempt == 0:
                log.info("401 — refreshing token and retrying")
                await self._ensure_token(force=True)
                continue
            if resp.status_code == 429:
                backoff = float(resp.headers.get("Retry-After", 2 ** attempt))
                log.warning("429 rate-limited; sleeping %.1fs", backoff)
                await asyncio.sleep(backoff)
                continue
            break

        assert last_resp is not None
        if last_resp.status_code >= 400:
            try:
                body = last_resp.json()
            except Exception:
                body = last_resp.text[:2000]
            raise NinjaAPIError(
                f"{method.upper()} {path} failed ({last_resp.status_code})",
                status=last_resp.status_code,
                body=body,
            )

        if not last_resp.content:
            return None
        ctype = last_resp.headers.get("content-type", "")
        if "json" in ctype:
            return last_resp.json()
        return last_resp.text
