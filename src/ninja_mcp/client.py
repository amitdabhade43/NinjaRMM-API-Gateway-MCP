"""Async NinjaOne OAuth2 client with safe, bounded retries."""
from __future__ import annotations
import asyncio, logging, time
from typing import Any
import httpx

log=logging.getLogger(__name__)
TOKEN_REFRESH_MARGIN_S=60
DEFAULT_TIMEOUT_S=30.0
MAX_RETRIES=3
RETRYABLE_STATUS={429,500,502,503,504}

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
            retry_after=response.headers.get("Retry-After")
            try:delay=float(retry_after) if retry_after else 2**attempt
            except ValueError:delay=2**attempt
            delay=max(0.0,min(delay,15.0))
            log.warning("GET rate/availability response %s; retrying in %.1fs",response.status_code,delay)
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
