import pytest

from ninjaone_agent.mcp_registry import MCPServerConfig, MCPToolInfo, MultiMCPManager


def test_default_configuration_keeps_existing_ninjaone_gateway(monkeypatch):
    monkeypatch.delenv("NINJA_AGENT_MCP_SERVERS_JSON", raising=False)

    servers = MCPServerConfig.load_all("python.exe", ("-m", "ninja_mcp"))

    assert servers == [
        MCPServerConfig(name="ninjaone", command="python.exe", args=("-m", "ninja_mcp"))
    ]


def test_loads_multiple_independent_server_configurations(monkeypatch):
    monkeypatch.setenv(
        "NINJA_AGENT_MCP_SERVERS_JSON",
        '[{"name":"ninjaone","command":"python","args":["-m","ninja_mcp"]},'
        '{"name":"filesystem","command":"node","args":["server.js"],"env":{"MODE":"local"}}]',
    )

    servers = MCPServerConfig.load_all("python.exe", ("-m", "ninja_mcp"))

    assert [server.name for server in servers] == ["ninjaone", "filesystem"]
    assert servers[1].command == "node"
    assert servers[1].args == ("server.js",)
    assert servers[1].env == {"MODE": "local"}


def test_rejects_duplicate_server_names_case_insensitively(monkeypatch):
    monkeypatch.setenv(
        "NINJA_AGENT_MCP_SERVERS_JSON",
        '[{"name":"Files","command":"one"},{"name":"files","command":"two"}]',
    )

    with pytest.raises(ValueError, match="Duplicate MCP server name"):
        MCPServerConfig.load_all("python.exe", ("-m", "ninja_mcp"))


def test_rejects_invalid_server_configuration(monkeypatch):
    monkeypatch.setenv("NINJA_AGENT_MCP_SERVERS_JSON", "not-json")
    with pytest.raises(ValueError, match="valid JSON"):
        MCPServerConfig.load_all("python.exe", ("-m", "ninja_mcp"))

    monkeypatch.setenv("NINJA_AGENT_MCP_SERVERS_JSON", '[{"name":"bad name","command":"x"}]')
    with pytest.raises(ValueError, match="Invalid MCP server name"):
        MCPServerConfig.load_all("python.exe", ("-m", "ninja_mcp"))


def test_tool_names_are_server_qualified_and_do_not_collide():
    manager = MultiMCPManager([])
    manager.tools = {
        "ninjaone.list_devices": MCPToolInfo("ninjaone", "list_devices", "ninjaone.list_devices", "NinjaOne devices", {}),
        "inventory.list_devices": MCPToolInfo("inventory", "list_devices", "inventory.list_devices", "Other inventory", {}),
        "filesystem.read_file": MCPToolInfo("filesystem", "read_file", "filesystem.read_file", "Read a file", {}),
    }

    names = [tool.qualified_name for tool in manager.list_tools()]

    assert names == [
        "filesystem.read_file",
        "inventory.list_devices",
        "ninjaone.list_devices",
    ]
