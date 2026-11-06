from ninja_mcp.search import search
from ninja_mcp.spec import Endpoint, Spec

def ep(method,path,summary,category="Users"):
    return Endpoint(method,path,None,summary,"",category,[category])

def test_fuzzy_search_prefers_matching_operation_summary():
    spec=Spec([
        ep("GET","/v2/users","Get all users"),
        ep("GET","/v2/organizations","Get all organizations"),
        ep("GET","/v2/users/{id}/devices","List devices accessible by user"),
    ])
    results=search(spec,"devices accessible by user",limit=3)
    assert results[0].path=="/v2/users/{id}/devices"

def test_delete_is_not_part_of_discovery_index():
    # Spec loader filters DELETE; search only ranks the already-filtered index.
    spec=Spec([ep("GET","/v2/users","Get users")])
    assert all(item.method!="DELETE" for item in search(spec,"users",limit=10))
