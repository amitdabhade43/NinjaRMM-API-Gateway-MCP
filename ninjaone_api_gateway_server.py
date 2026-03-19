#!/usr/bin/env python3
"""
NinjaOne RMM API Gateway MCP Server - Entry Point

This script starts the NinjaOne RMM API Gateway MCP Server.
"""

import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api_gateway.server import main

if __name__ == "__main__":
    main()
