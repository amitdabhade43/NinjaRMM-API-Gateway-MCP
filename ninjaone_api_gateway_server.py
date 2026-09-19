"""Compatibility shim: older MCP client configs launch this file directly.
The server now lives in the ninja_mcp package (pip install -e .). Run it."""
from ninja_mcp.__main__ import main

if __name__ == "__main__":
    main()
