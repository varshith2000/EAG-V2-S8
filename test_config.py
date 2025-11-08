#!/usr/bin/env python3
"""Test script to check MCP configuration"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.hybrid_session import create_hybrid_mcp
import asyncio

async def check_config():
    try:
        mcp = create_hybrid_mcp()
        print("MCP Configuration loaded:")
        for server in mcp.server_configs:
            if server.get('transport') == 'sse':
                print(f"  {server.get('id')}: {server.get('url')}: port {server.get('port')}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_config())