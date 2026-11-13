"""Async NinjaOne OAuth2 client with safe, bounded retries."""
from __future__ import annotations
import asyncio, logging, time
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Any
import httpx

log=logging.getLogger(__name__)
TOKEN_REFRESH_MARGIN_S=60
DEFAULT_TIMEOUT_S=30.0
MAX_RETRIES=3
MAX_RETRY_DELAY_S=30.0
RETRYABLE_STATUS={429,500,502,503,504}


def _retry_delay(headers: Any, attempt: int, now: float | None = None) -> float:
    """Read standard retry/rate-limit headers, with a bounded exponential fallback."""
    values = {str(key).casefold(): str(value).strip()
              for key, value in (headers.items() if hasattr(headers, "items") else [])}
    current = time.time() if now is None else now

    retry_after = values.get("retry-after")
    if retry_after:
        try:
            delay = float(retry_after)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(retry_after)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                delay = retry_at.timestamp() - current
            except (TypeError, ValueError, OverflowError):
                delay = 2 ** attempt
    else:
        delay = None
        # RateLimit-Reset is a relative delay; X-RateLimit-Reset is commonly
        # an epoch timestamp. Treat very large values as epoch seconds too.
        for header in ("ratelimit-reset", "x-ratelimit-reset"):
            raw = values.get(header)
            if not raw:
                continue
            try:
                parsed = float(raw)
            except ValueError:
                continue
            delay = parsed - current if header == "x-ratelimit-reset" or parsed > 1_000_000_000 else parsed
            break
        if delay is None:
            delay = 2 ** attempt

    return max(0.0, min(float(delay), MAX_RETRY_DELAY_S))

class NinjaAuthError(Exception):pass
class NinjaAPIError(Exception):
    def __init__(self,message:str,status:int|None=None,body:Any=None):
        super().__init__(message);self.status=status;self.body=body

class NinjaClient:
    def __init__(self,client_id:str,client_secret:str,instance:str="app.ninjarmm.com",
                 scope:str="monitoring management control"):
        host=instance.removeprefix("https://").removeprefix("http://").strip("/")
        if "/" in host or not host or any(c.isspace() for c in host):
            raise ValueError("NINJAONE_INSTANCE must be a regional hostname, not a URL path.")
        self.client_id=client_id;self.client_secret=client_secret
        self.base_url=f"https://{host}";self.scope=scope
        self._token:str|None=None;self._expires_at=0.0;self._token_lock=asyncio.Lock()
        self._http=httpx.AsyncClient(timeout=httpx.Timeout(DEFAULT_TIMEOUT_S),
            limits=httpx.Limits(max_connections=20,max_keepalive_connections=10))

    async def aclose(self)->None:await self._http.aclose()

    async def _ensure_token(self,force:bool=False)->str:
        if not force and self._token and time.time()<self._expires_at-TOKEN_REFRESH_MARGIN_S:return self._token
        async with self._token_lock:
            if not force and self._token and time.time()<self._expires_at-TOKEN_REFRESH_MARGIN_S:return self._token
            try:
                response=await self._http.post(f"{self.base_url}/oauth/token",
                    data={"grant_type":"client_credentials","client_id":self.client_id,
                          "client_secret":self.client_secret,"scope":self.scope},
                    headers={"Content-Type":"application/x-www-form-urlencoded"})
            except httpx.HTTPError as exc:raise NinjaAuthError(f"OAuth token transport error: {exc}") from exc
            if response.status_code!=200:
                raise NinjaAuthError(f"OAuth token request failed ({response.status_code}): {response.text[:300]}")
            try:payload=response.json();self._token=payload["access_token"]
            except (ValueError,KeyError,TypeError) as exc:raise NinjaAuthError("OAuth token response was invalid.") from exc
            self._expires_at=time.time()+int(payload.get("expires_in",3600))
            log.info("OAuth token refreshed; expiry in %ss",payload.get("expires_in",3600))
            return self._token

    async def request(self,method:str,path:str,*,params:dict[str,Any]|None=None,json_body:Any=None)->Any:
        method=method.upper()
        # Never retry non-GET requests: a timeout/5xx can occur after the server committed a mutation.
        attempts=MAX_RETRIES if method=="GET" else 1
        last_response=None
        for attempt in range(attempts):
            token=await self._ensure_token()
            try:
                response=await self._http.request(method,f"{self.base_url}{path}",
                    headers={"Authorization":f"Bearer {token}","Accept":"application/json"},
                    params=params,json=json_body)
            except httpx.HTTPError as exc:
                if method=="GET" and attempt+1<attempts:
                    await asyncio.sleep(min(2**attempt,8));continue
                raise NinjaAPIError(f"{method} {path} transport error: {exc}") from exc
            last_response=response
            if response.status_code==401 and attempt==0:
                await self._ensure_token(force=True);continue
            if response.status_code not in RETRYABLE_STATUS or method!="GET" or attempt+1>=attempts:break
            delay = _retry_delay(response.headers, attempt)
            log.warning(
                "GET %s returned HTTP %s; bounded retry %d/%d in %.1fs",
                path, response.status_code, attempt + 1, attempts - 1, delay,
            )
            await asyncio.sleep(delay)
        if last_response is None:raise NinjaAPIError("NinjaOne request failed without an HTTP response.")
        if last_response.status_code>=400:
            try:error_body=last_response.json()
            except ValueError:error_body=last_response.text[:2000]
            raise NinjaAPIError(f"{method} {path} failed ({last_response.status_code})",
                                status=last_response.status_code,body=error_body)
        if not last_response.content:return None
        if "json" in last_response.headers.get("content-type",""):return last_response.json()
        return last_response.text
