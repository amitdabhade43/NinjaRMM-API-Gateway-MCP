import json
from pathlib import Path

from ninja_mcp.spec import Spec

def test_spec_loads_only_supported_http_methods():
    spec=Spec.load(Path(__file__).resolve().parent.parent/"NinjaRMM-API-v2.json")
    assert spec.endpoints
    assert {endpoint.method for endpoint in spec.endpoints} <= {"GET","POST","PUT","PATCH"}

def test_spec_resolves_local_parameter_and_body_refs(tmp_path):
    document={
      "components":{"parameters":{"UserId":{"name":"userId","in":"path","required":True,"schema":{"type":"string"}}},
                    "schemas":{"Update":{"type":"object","properties":{"active":{"type":"boolean"}}}}},
      "paths":{"/v2/users/{userId}":{"parameters":[{"$ref":"#/components/parameters/UserId"}],
        "patch":{"summary":"Update user","requestBody":{"required":True,"content":{"application/json":{"schema":{"$ref":"#/components/schemas/Update"}}}},
                 "responses":{"200":{"description":"Updated"}}},
        "delete":{"summary":"Delete user"}}}}
    path=tmp_path/"spec.json"
    path.write_text(json.dumps(document),encoding="utf-8")
    spec=Spec.load(path)
    assert len(spec.endpoints)==1
    endpoint=spec.get("PATCH /v2/users/{userId}")
    assert endpoint is not None
    assert endpoint.parameters[0]["name"]=="userId"
    schema=endpoint.request_body["content"]["application/json"]["schema"]
    assert schema["type"]=="object"
