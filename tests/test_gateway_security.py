import base64, hashlib, hmac, json, time
import pytest

from ninja_mcp.approval import ApprovalError, body_digest, verify_approval
from ninja_mcp.server import _check_method, _interpolate_path, _match_template
from ninja_mcp.spec import Endpoint, Spec

def token(secret, method, path, body, exp=None):
    payload={"method":method,"path":path,"body_sha256":body_digest(body),"exp":exp or int(time.time())+60,"jti":hashlib.sha256((method+path+str(exp)).encode()).hexdigest()}
    encoded=base64.urlsafe_b64encode(json.dumps(payload,separators=(",",":")).encode()).decode().rstrip("=")
    signature=base64.urlsafe_b64encode(hmac.new(secret.encode(),encoded.encode(),hashlib.sha256).digest()).decode().rstrip("=")
    return encoded+"."+signature

def test_get_allowed():
    assert _check_method("get")=="GET"

@pytest.mark.parametrize("method", ["POST","PUT","PATCH"])
def test_write_methods_are_allowed_at_gateway(method):
    assert _check_method(method)==method

def test_delete_is_permanently_blocked():
    with pytest.raises(ValueError, match="permanently blocked"):
        _check_method("DELETE")

def test_unknown_method_rejected():
    with pytest.raises(ValueError, match="Unsupported method"):
        _check_method("OPTIONS")

def test_interpolate_path_encodes_values_and_checks_missing():
    assert _interpolate_path("/v2/users/{id}", {"id":"A B/1"})=="/v2/users/A%20B%2F1"
    with pytest.raises(ValueError, match="Missing required"):
        _interpolate_path("/v2/users/{id}", {})

def test_interpolate_path_rejects_extra_values():
    with pytest.raises(ValueError, match="Unexpected"):
        _interpolate_path("/v2/users/{id}", {"id":1,"other":2})

def test_raw_path_matches_template_and_extracts_values(monkeypatch):
    endpoint=Endpoint("GET","/v2/users/{id}/devices/{deviceId}",None,"","","Users",[])
    monkeypatch.setattr("ninja_mcp.server._SPEC",Spec([endpoint]))
    assert _match_template("GET","/v2/users/abc/devices/123") == (
        "GET /v2/users/{id}/devices/{deviceId}", {"id":"abc","deviceId":"123"})

def test_approval_token_bound_to_method_path_and_body(monkeypatch):
    monkeypatch.setenv("NINJA_MCP_APPROVAL_SECRET","unit-test-secret")
    payload={"enabled":False}
    signed=token("unit-test-secret","PATCH","/v2/devices/123",payload)
    verify_approval(signed,"PATCH","/v2/devices/123",payload)
    with pytest.raises(ApprovalError,match="already been used"):\n        verify_approval(signed,"PATCH","/v2/devices/123",payload)\n    signed_mismatch=token("unit-test-secret","PATCH","/v2/devices/123",{"enabled":True})\n    with pytest.raises(ApprovalError,match="does not match"):
        verify_approval(signed_mismatch,"PATCH","/v2/devices/123",{"enabled":False})

def test_approval_required_and_expiry(monkeypatch):
    monkeypatch.setenv("NINJA_MCP_APPROVAL_SECRET","unit-test-secret")
    with pytest.raises(ApprovalError,match="required"):
        verify_approval(None,"POST","/v2/devices",{})
    expired=token("unit-test-secret","POST","/v2/devices",{},int(time.time())-1)
    with pytest.raises(ApprovalError,match="expired"):
        verify_approval(expired,"POST","/v2/devices",{})
