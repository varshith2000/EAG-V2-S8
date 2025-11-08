#!/usr/bin/env python3
"""
Simplified Google Sheets SSE MCP Server (without API initialization)
For testing the SSE server connection
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from typing import Dict, Any

from aiohttp import web, WSMsgType
from aiohttp.web import Application, Request, Response
import aiohttp_cors

# Add current directory to path to import our modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from models import SheetsCreateInput, SheetsCreateOutput

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sheets-sse-simple-server")

class SimpleSheetsSSEServer:
    """Simplified Google Sheets SSE MCP Server for testing"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8082):
        self.host = host
        self.port = port
        self.app = web.Application()
        self.setup_routes()
        self.setup_cors()

    def setup_cors(self):
        """Setup CORS for the application"""
        cors = aiohttp_cors.setup(self.app, defaults={
            "*": aiohttp_cors.ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*",
                allow_methods="*"
            )
        })

        # Add CORS to all routes
        for route in list(self.app.router.routes()):
            cors.add(route)

    def setup_routes(self):
        """Setup API routes"""
        self.app.router.add_post('/sheets/create', self.handle_create_sheet)
        self.app.router.add_get('/health', self.health_handler)
        self.app.router.add_get('/', self.root_handler)

    async def root_handler(self, request: Request) -> Response:
        """Root endpoint"""
        return Response(text=f"""
        <html>
        <head><title>Google Sheets SSE MCP Server (Simple)</title></head>
        <body>
            <h1>📊 Google Sheets SSE MCP Server (Simple Mode)</h1>
            <p>Status: <span id="status">🟢 Running</span></p>
            <h2>Endpoints:</h2>
            <ul>
                <li><a href="/health">Health Check</a> - Server status</li>
                <li>/sheets/create - Create spreadsheet</li>
            </ul>
        </body>
        </html>
        """, content_type='text/html')

    async def health_handler(self, request: Request) -> Response:
        """Health check endpoint"""
        try:
            return Response(json.dumps({
                "status": "healthy",
                "service": "sheets",
                "mode": "simple",
                "timestamp": datetime.now().isoformat()
            }), content_type='application/json')
        except Exception as e:
            logger.error(f"Health check error: {e}")
            return Response(json.dumps({
                "status": "unhealthy",
                "service": "sheets",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }), content_type='application/json', status=500)

    async def handle_create_sheet(self, request: Request) -> Response:
        """Handle create sheet request"""
        try:
            data = await request.json()
            logger.info(f"Create sheet request: {data}")

            # Validate input
            create_input = SheetsCreateInput(**data)

            # Mock sheet creation (without actual Google Sheets API)
            sheet_id = f"mock_sheet_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"

            result = {
                "success": True,
                "sheet_id": sheet_id,
                "sheet_url": sheet_url
            }

            logger.info(f"Created mock sheet: {sheet_id}")
            return Response(json.dumps(result), content_type='application/json')

        except Exception as e:
            logger.error(f"Create sheet error: {e}")
            error_result = {
                "success": False,
                "error": str(e)
            }
            return Response(json.dumps(error_result), content_type='application/json', status=500)

    async def start(self):
        """Start the SSE server"""
        from aiohttp import web

        runner = web.AppRunner(self.app)
        await runner.setup()

        site = web.TCPSite(runner, self.host, self.port)
        await site.start()

        logger.info(f"🚀 Google Sheets SSE Simple Server started on http://{self.host}:{self.port}")
        logger.info(f"💾 Health check: http://{self.host}:{self.port}/health")

async def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Google Sheets SSE MCP Server (Simple)")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8082, help="Port to bind to")

    args = parser.parse_args()

    server = SimpleSheetsSSEServer(host=args.host, port=args.port)
    await server.start()

    # Keep server running
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("👋 Shutting down Sheets SSE server...")

if __name__ == "__main__":
    try:
        import asyncio
        import os
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Server stopped. Goodbye!")
    except Exception as e:
        print(f"\n❌ Server error: {e}")
        import traceback
        traceback.print_exc()