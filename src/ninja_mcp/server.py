"""NinjaOne API Gateway MCP.

The tool surface is intentionally small and schema-driven:
discover_endpoints, inspect_endpoint, execute_endpoint, execute_raw_request.
DELETE is never exposed or executed. Write calls require an external human approval token.
"""
from __future__ import annotations
import asyncio, logging, os, re, sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, unquote, urlsplit

from mcp.server.fastmcp import FastMCP
from .approval import ApprovalError, verify_approval
from .client import NinjaAPIError, NinjaAuthError, NinjaClient
from .search import search
from .semantic import semantic_rank
from .spec import Endpoint, Spec
from .truncate import truncate

logging.basicConfig(level=os.getenv("NINJA_MCP_LOG_LEVEL","INFO"), stream=sys.stderr,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log=logging.getLogger("ninja_mcp")
ALLOWED_METHODS=frozenset({"GET","POST","PUT","PATCH"})
PATH_PARAM_RE=re.compile(r"\{([^}]+)\}")
mcp=FastMCP("NinjaOne-API-Gateway")
_SPEC: Spec|None=None
_CLIENT: NinjaClient|None=None

def _spec_path()->Path:
    return Path(os.getenv("NINJA_MCP_SPEC")) if os.getenv("NINJA_MCP_SPEC") else Path(__file__).resolve().parent.parent.parent/"NinjaRMM-API-v2.json"

def _spec()->Spec:
    global _SPEC
    if _SPEC is None:
        _SPEC=Spec.load(_spec_path())
        log.info("Loaded %d supported NinjaOne endpoints",len(_SPEC.endpoints))
    return _SPEC

def _client()->NinjaClient:
    global _CLIENT
    if _CLIENT is None:
        cid=os.getenv("NINJAONE_CLIENT_ID"); secret=os.getenv("NINJAONE_CLIENT_SECRET")
        if not cid or not secret:
            raise NinjaAuthError("NINJAONE_CLIENT_ID and NINJAONE_CLIENT_SECRET must be configured")
        _CLIENT=NinjaClient(cid,secret,os.getenv("NINJAONE_INSTANCE","app.ninjarmm.com"),
                            scope=os.getenv("NINJAONE_SCOPE","monitoring management control"))
    return _CLIENT

def _check_method(method:str)->str:
    value=method.upper()
    if value=="DELETE":
        raise ValueError("DELETE is permanently blocked by this gateway.")
    if value not in ALLOWED_METHODS:
        raise ValueError(f"Unsupported method {value}. Allowed: GET, POST, PUT, PATCH.")
    return value

def _interpolate_path(path:str, values:dict[str,Any]|None)->str:
    values=values or {}
    required=PATH_PARAM_RE.findall(path)
    missing=[name for name in required if name not in values or values[name] is None]
    if missing:
        raise ValueError(f"Missing required path parameter(s): {', '.join(missing)}")
    extra=set(values)-set(required)
    if extra:
        raise ValueError(f"Unexpected path parameter(s): {', '.join(sorted(extra))}")
    def replace(match:re.Match[str])->str:
        value=values[match.group(1)]
        if isinstance(value,(dict,list)) or str(value)=="":
            raise ValueError(f"Path parameter {match.group(1)!r} must be a non-empty scalar")
        return quote(str(value),safe="")
    return PATH_PARAM_RE.sub(replace,path)

def _validate_inputs(endpoint:Endpoint, query:dict[str,Any]|None, body:Any)->None:
    query=query or {}
    params=[p for p in endpoint.parameters if isinstance(p,dict)]
    known_query={p.get("name"):p for p in params if p.get("in")=="query"}
    unknown=set(query)-set(known_query)
    if unknown:
        raise ValueError(f"Unknown query parameter(s): {', '.join(sorted(unknown))}. Inspect endpoint schema.")
    for p in params:
        if p.get("required") and p.get("in")=="query" and p.get("name") not in query:
            raise ValueError(f"Missing required query parameter: {p.get('name')}")
    if endpoint.request_body and endpoint.request_body.get("required") and body is None:
        raise ValueError("This endpoint requires a JSON request body.")

def _match_template(method:str, concrete_path:str)->tuple[str,dict[str,str]]|None:
    for endpoint in _spec().endpoints:
        if endpoint.method!=method: continue
        names=PATH_PARAM_RE.findall(endpoint.path)
        pattern="^"+PATH_PARAM_RE.sub(lambda m:"([^/]+)",re.escape(endpoint.path).replace(r"\{", "{").replace(r"\}", "}"))+"$"
        # Build safely by escaping literal path segments.
        pieces=[]; cursor=0
        for match in PATH_PARAM_RE.finditer(endpoint.path):
            pieces.append(re.escape(endpoint.path[cursor:match.start()]))
            pieces.append("([^/]+)")
            cursor=match.end()
        pieces.append(re.escape(endpoint.path[cursor:]))
        match=re.fullmatch("".join(pieces),concrete_path)
        if match:
            return endpoint.key,{name:unquote(value)
                                 for name,value in zip(names,match.groups())}
    return None

async def _execute(endpoint_key:str,*,path_params:dict[str,Any]|None=None,
                   query:dict[str,Any]|None=None,body:Any=None,
                   approval_token:str|None=None)->dict[str,Any]:
    endpoint=_spec().get(endpoint_key)
    if endpoint is None: return {"error":f"Unknown endpoint {endpoint_key!r}. Discover it first."}
    try:
        method=_check_method(endpoint.method)
        path=_interpolate_path(endpoint.path,path_params)
        _validate_inputs(endpoint,query,body)
        if method!="GET":
            verify_approval(approval_token,method,path,body)
    except (ValueError,ApprovalError) as exc:
        return {"error":str(exc),"executed":False}
    try:
        data=await _client().request(method,path,params=query,json_body=body)
    except NinjaAuthError as exc:
        return {"error":f"Authentication failed: {exc}","executed":False}
    except NinjaAPIError as exc:
        return {"error":str(exc),"status":exc.status,"body":exc.body,"executed":True}
    result,was_truncated=truncate(data)
    return {"endpoint":f"{method} {path}","executed":True,"complete":not was_truncated,
            "truncated":was_truncated,"pagination":{"automatic":False,
            "note":"If complete=false, use the endpoint's documented page/pageSize/cursor parameters to retrieve remaining results."}
            if was_truncated else {"automatic":False,"note":"No automatic pagination was applied."},
            "data":result}

@mcp.tool()
async def discover_endpoints(intent:str,category:str|None=None,method:str|None=None,
                             candidate_limit:int=20)->dict[str,Any]:
    """Find real NinjaOne API operations using fuzzy retrieval and optional local semantic ranking.

    Supply a natural-language intent such as 'find a user by email and list assigned devices'.
    Semantic selection is grounded only in the OpenAPI candidates returned by fuzzy retrieval.
    """
    if method:
        try: method=_check_method(method)
        except ValueError as exc: return {"error":str(exc)}
    spec=_spec()
    if not intent.strip() and not category:
        return {"categories":spec.categories,"supported_methods":sorted(ALLOWED_METHODS),
                "total_supported_endpoints":len(spec.endpoints)}
    candidates=search(spec,intent,category=category,method=method,limit=candidate_limit)
    if not candidates:
        return {"count":0,"results":[],"reason":"No matching supported OpenAPI operation was found."}
    try:
        ranked=await semantic_rank(intent,[e for e in candidates])
    except Exception as exc:
        log.warning("Local semantic ranking unavailable: %s",exc)
        ranked={"mode":"fuzzy_fallback","selected":[e.key for e in candidates[:5]],
                "warning":f"Semantic ranking unavailable: {type(exc).__name__}"}
    return {"candidate_count":len(candidates),"semantic":ranked,
            "candidates":[e.to_summary() for e in candidates]}

@mcp.tool()
async def inspect_endpoint(endpoint:str)->dict[str,Any]:
    """Return the exact OpenAPI parameters, request body and response schema for an endpoint."""
    found=_spec().get(endpoint)
    if not found:return {"error":f"Unknown endpoint {endpoint!r}. Use discover_endpoints."}
    if found.method not in ALLOWED_METHODS:return {"error":"This HTTP method is blocked."}
    return found.to_detail()

@mcp.tool()
async def execute_endpoint(endpoint:str,path_params:dict[str,Any]|None=None,
                            query:dict[str,Any]|None=None,body:Any=None,
                            approval_token:str|None=None)->dict[str,Any]:
    """Execute an OpenAPI endpoint. GET is automatic. POST/PUT/PATCH require a signed human approval token.

    The token is issued by the trusted approval service and bound to the exact method, resolved path and JSON body.
    DELETE is blocked regardless of token. Never invent or self-approve a token.
    """
    return await _execute(endpoint,path_params=path_params,query=query,body=body,approval_token=approval_token)

@mcp.tool()
async def execute_raw_request(request:str,body:Any=None,approval_token:str|None=None)->dict[str,Any]:
    """Execute 'METHOD /concrete/path?query=value'; concrete path segments are mapped to OpenAPI path parameters."""
    parts=request.strip().split(None,1)
    if len(parts)!=2:return {"error":"Expected 'METHOD /path[?query]'","executed":False}
    try:method=_check_method(parts[0])
    except ValueError as exc:return {"error":str(exc),"executed":False}
    split=urlsplit(parts[1])
    if split.scheme or split.netloc or not split.path.startswith("/"):
        return {"error":"Only relative NinjaOne API paths beginning with / are accepted.","executed":False}
    query_items=parse_qsl(split.query,keep_blank_values=True)
    query={}
    for key,value in query_items:
        if key in query:
            query[key]=query[key]+[value] if isinstance(query[key],list) else [query[key],value]
        else:query[key]=value
    endpoint_key=f"{method} {split.path}"
    path_params=None
    if _spec().get(endpoint_key) is None:
        matched=_match_template(method,split.path)
        if not matched:return {"error":f"No OpenAPI endpoint matches {method} {split.path}","executed":False}
        endpoint_key,path_params=matched
    return await _execute(endpoint_key,path_params=path_params,query=query or None,
                           body=body,approval_token=approval_token)


@mcp.tool()
async def execute_paginated_endpoint(endpoint:str,query:dict[str,Any]|None=None,
                                     page_parameter:str="page",page_size_parameter:str="pageSize",
                                     page_size:int=100,start_page:int=1,max_pages:int=10,
                                     result_path:str|None=None)->dict[str,Any]:
    """Fetch multiple GET pages using explicitly selected OpenAPI-declared page parameters.

    Supply the page and page-size parameter names and optional dotted result_path (e.g. 'results').
    Stops on a short page or max_pages; no undocumented pagination convention is guessed.
    """
    found=_spec().get(endpoint)
    if found is None:return {"error":f"Unknown endpoint {endpoint!r}","complete":False}
    if found.method!="GET":return {"error":"Automatic pagination is GET-only.","complete":False}
    if not (1<=page_size<=200 and 1<=max_pages<=20 and start_page>=0):
        return {"error":"page_size must be 1-200, max_pages 1-20, and start_page non-negative.","complete":False}
    declared={p.get("name") for p in found.parameters if isinstance(p,dict) and p.get("in")=="query"}
    if page_parameter not in declared or page_size_parameter not in declared:
        return {"error":"Pagination parameters are not both declared by this endpoint. Inspect its OpenAPI schema.","complete":False}
    if page_parameter==page_size_parameter:return {"error":"Page and page-size parameters must differ.","complete":False}
    base_query=dict(query or {})
    if page_parameter in base_query or page_size_parameter in base_query:
        return {"error":"Pass pagination values through the dedicated arguments, not query.","complete":False}
    items=[];pages=0;finished=False
    try:
        for offset in range(max_pages):
            page_query={**base_query,page_parameter:start_page+offset,page_size_parameter:page_size}
            payload=await _client().request("GET",found.path,params=page_query)
            current=payload
            if result_path:
                for segment in result_path.split("."):
                    if not isinstance(current,dict) or segment not in current:
                        return {"error":f"Result path {result_path!r} was not present.",
                                "pages_fetched":pages,"items_fetched":len(items),"complete":False}
                    current=current[segment]
            elif isinstance(current,dict):
                arrays=[value for value in current.values() if isinstance(value,list)]
                if len(arrays)==1:current=arrays[0]
                else:return {"error":"Cannot identify the paged array safely; supply result_path.",
                             "pages_fetched":pages,"items_fetched":len(items),"complete":False}
            if not isinstance(current,list):
                return {"error":"The pagination result is not an array.",
                        "pages_fetched":pages,"items_fetched":len(items),"complete":False}
            pages+=1;items.extend(current)
            if len(current)<page_size:
                finished=True;break
    except NinjaAuthError as exc:
        return {"error":f"Authentication failed: {exc}","pages_fetched":pages,
                "items_fetched":len(items),"complete":False}
    except NinjaAPIError as exc:
        return {"error":str(exc),"status":exc.status,"body":exc.body,
                "pages_fetched":pages,"items_fetched":len(items),"complete":False}
    data,truncated=truncate(items)
    return {"endpoint":endpoint,"pages_fetched":pages,"items_fetched":len(items),
            "complete":finished and not truncated,"truncated":truncated,
            "max_pages_reached":not finished,"data":data,
            "note":"If complete=false, increase max_pages or narrow the query."}

async def _shutdown()->None:
    global _CLIENT
    if _CLIENT is not None:
        await _CLIENT.aclose()
        _CLIENT=None

def main()->None:
    log.info("Starting NinjaOne API Gateway MCP; spec=%s",_spec_path())
    _spec()
    try:\n        mcp.run(transport="stdio")\n    finally:\n        if _CLIENT is not None:\n            asyncio.run(_shutdown())

if __name__=="__main__":main()
