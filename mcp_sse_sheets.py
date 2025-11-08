#!/usr/bin/env python3
"""
Google Sheets SSE MCP Server
Handles Google Sheets operations via SSE transport
"""

import asyncio
import json
import logging
import os
import sys
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

from aiohttp import web, WSMsgType
from aiohttp.web import Application, Request, Response
import aiohttp_cors
from dotenv import load_dotenv

# Google API imports
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google_auth_oauthlib.flow import Flow
from google_auth_httplib2 import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import httplib2

# Add current directory to path to import our modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from models import SheetsCreateInput, SheetsCreateOutput, SheetsUpdateInput, SheetsUpdateOutput

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sheets-sse-server")

@dataclass
class SSEMessage:
    """SSE message structure"""
    event: str
    data: Dict[str, Any]
    id: Optional[str] = None
    retry: Optional[int] = None

class SheetsSSEServer:
    """Google Sheets SSE MCP Server"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8082):
        self.host = host
        self.port = port
        self.app = web.Application()
        self.connections = set()
        self.message_queue = asyncio.Queue()
        self.credentials = None
        self.sheets_service = None
        self.oauth_flow = None

        # Load environment variables
        load_dotenv()

        self.setup_routes()
        self.setup_cors()
        self.setup_oauth()

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

    def setup_oauth(self):
        """Setup OAuth flow for Google Sheets"""
        # Try service account first (recommended for server applications)
        service_account_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH")
        if service_account_file and os.path.exists(service_account_file):
            try:
                self.credentials = service_account.Credentials.from_service_account_file(
                    service_account_file,
                    scopes=['https://www.googleapis.com/auth/spreadsheets',
                           'https://www.googleapis.com/auth/drive.file']
                )
                # Create sheets service immediately with service account
                self.sheets_service = build('sheets', 'v4', credentials=self.credentials)
                logger.info("✅ Service account loaded successfully")
                return
            except Exception as e:
                logger.error(f"Failed to load service account: {e}")

        # Fall back to OAuth if service account fails
        client_secrets_file = os.getenv("GOOGLE_CLIENT_SECRETS_FILE")
        if not client_secrets_file:
            logger.warning("GOOGLE_CLIENT_SECRETS_FILE not configured")
            return

        redirect_uri = f"http://{self.host}:{self.port}/auth/callback"

        config = {
            "web": {
                "client_id": os.getenv("GOOGLE_OAUTH_CLIENT_ID"),
                "client_secret": os.getenv("GOOGLE_OAUTH_CLIENT_SECRET"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri]
            }
        }

        self.oauth_flow = Flow.from_client_config(
            config,
            scopes=['https://www.googleapis.com/auth/spreadsheets',
                   'https://www.googleapis.com/auth/drive.file'],
            redirect_uri=redirect_uri
        )

    def setup_routes(self):
        """Setup API routes"""
        self.app.router.add_post('/sheets/create', self.handle_create_sheet)
        self.app.router.add_post('/sheets/update', self.handle_update_sheet)
        self.app.router.add_post('/sheets/share', self.handle_share_sheet)
        self.app.router.add_get('/sheets/auth', self.handle_auth_request)
        self.app.router.add_get('/auth/callback', self.handle_auth_callback)
        self.app.router.add_get('/health', self.health_handler)
        self.app.router.add_get('/', self.root_handler)

    async def root_handler(self, request: Request) -> Response:
        """Root endpoint"""
        auth_status = "service_account" if self.sheets_service else "not_authenticated"
        return Response(text=f"""
        <html>
        <head><title>Google Sheets SSE MCP Server</title></head>
        <body>
            <h1>📊 Google Sheets SSE MCP Server</h1>
            <p>Status: <span id="status">🟢 Running</span></p>
            <p>Auth: {auth_status}</p>
            <h2>Endpoints:</h2>
            <ul>
                <li><a href="/sheets/auth">Sheets Auth</a> - Authorize Sheets access</li>
                <li><a href="/health">Health Check</a> - Server status</li>
                <li>/sheets/create - Create spreadsheet</li>
                <li>/sheets/update - Update spreadsheet</li>
                <li>/sheets/share - Share spreadsheet</li>
            </ul>
        </body>
        </html>
        """, content_type='text/html')

    async def health_handler(self, request: Request) -> Response:
        """Health check endpoint"""
        try:
            auth_status = "service_account" if self.sheets_service else "not_authenticated"
            return Response(
                text=json.dumps({
                    "status": "healthy",
                    "service": "sheets",
                    "timestamp": datetime.now().isoformat(),
                    "auth_status": auth_status,
                    "connections": len(self.connections)
                }),
                content_type='application/json'
            )
        except Exception as e:
            logger.error(f"Health check error: {e}")
            logger.exception("Full exception:")
            return Response(
                text=json.dumps({
                    "status": "unhealthy",
                    "service": "sheets",
                    "error": str(e),
                    "timestamp": datetime.now().isoformat()
                }),
                content_type='application/json',
                status=500
            )

    async def handle_auth_request(self, request: Request) -> Response:
        """Handle OAuth authorization request"""
        if self.sheets_service:
            return Response(
                text=json.dumps({
                    "message": "Already authenticated with service account"
                }),
                content_type='application/json'
            )

        if not self.oauth_flow:
            return Response(text="OAuth not configured", status=500)

        auth_url, _ = self.oauth_flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true'
        )

        return Response(
            text=json.dumps({
                "auth_url": auth_url,
                "message": "Visit this URL to authorize Google Sheets access"
            }),
            content_type='application/json'
        )

    async def handle_auth_callback(self, request: Request) -> Response:
        """Handle OAuth callback"""
        if not self.oauth_flow:
            return Response(text="OAuth not configured", status=500)

        code = request.query.get('code')
        if not code:
            return Response(text="Authorization code not found", status=400)

        try:
            self.oauth_flow.fetch_token(code=code)
            self.credentials = self.oauth_flow.credentials

            # Create Sheets service
            self.sheets_service = build('sheets', 'v4', credentials=self.credentials)

            # Store credentials for future use
            self.store_credentials()

            html_content = """
            <html>
            <head><title>Google Sheets Authorization Complete</title></head>
            <body>
                <h1>✅ Google Sheets Authorization Successful!</h1>
                <p>You can now use the Sheets MCP tools.</p>
                <p>You can close this window.</p>
            </body>
            </html>
            """
            return Response(text=html_content, content_type='text/html')

        except Exception as e:
            logger.error(f"OAuth callback error: {e}")
            return Response(text=f"Authorization failed: {str(e)}", status=500)

    def store_credentials(self):
        """Store credentials for future use"""
        if self.credentials and not isinstance(self.credentials, service_account.Credentials):
            creds_file = "sheets_credentials.json"
            with open(creds_file, 'w') as f:
                f.write(self.credentials.to_json())
            logger.info(f"Credentials stored in {creds_file}")

    def load_credentials(self):
        """Load stored credentials"""
        if self.sheets_service:
            return True  # Already loaded with service account

        creds_file = "sheets_credentials.json"
        if os.path.exists(creds_file):
            try:
                self.credentials = Credentials.from_authorized_user_file(creds_file)
                if self.credentials.valid:
                    self.sheets_service = build('sheets', 'v4', credentials=self.credentials)
                    logger.info("Loaded stored Sheets credentials")
                    return True
            except Exception as e:
                logger.error(f"Failed to load credentials: {e}")
        return False

    async def handle_create_sheet(self, request: Request) -> Response:
        """Handle create sheet request"""
        try:
            # Load credentials if not already loaded
            if not self.sheets_service and not self.load_credentials():
                return Response(
                    text=json.dumps({
                        "success": False,
                        "error": "Google Sheets not authenticated. Please visit /sheets/auth first"
                    }),
                    content_type='application/json',
                    status=401
                )

            data = await request.json()
            logger.info(f"Create sheet request: {data}")

            # Validate input
            create_input = SheetsCreateInput(**data)

            # Create sheet
            result = await self.create_spreadsheet(create_input)

            # Broadcast event
            await self.broadcast(SSEMessage(
                event="sheet_created",
                data={
                    "type": "sheet_created",
                    "title": create_input.title,
                    "result": asdict(result),
                    "timestamp": datetime.now().isoformat()
                }
            ))

            return Response(text=json.dumps(asdict(result)), content_type='application/json')

        except Exception as e:
            logger.error(f"Create sheet error: {e}")
            error_result = SheetsCreateOutput(success=False, error=str(e))
            return Response(text=json.dumps(asdict(error_result)), content_type='application/json', status=500)

    async def handle_update_sheet(self, request: Request) -> Response:
        """Handle update sheet request"""
        try:
            # Load credentials if not already loaded
            if not self.sheets_service and not self.load_credentials():
                return Response(
                    text=json.dumps({
                        "success": False,
                        "error": "Google Sheets not authenticated. Please visit /sheets/auth first"
                    }),
                    content_type='application/json',
                    status=401
                )

            data = await request.json()
            logger.info(f"Update sheet request: {data}")

            # Validate input
            update_input = SheetsUpdateInput(**data)

            # Update sheet
            result = await self.update_spreadsheet(update_input)

            # Broadcast event
            await self.broadcast(SSEMessage(
                event="sheet_updated",
                data={
                    "type": "sheet_updated",
                    "sheet_id": update_input.sheet_id,
                    "range": update_input.range,
                    "result": asdict(result),
                    "timestamp": datetime.now().isoformat()
                }
            ))

            return Response(text=json.dumps(asdict(result)), content_type='application/json')

        except Exception as e:
            logger.error(f"Update sheet error: {e}")
            error_result = SheetsUpdateOutput(success=False, error=str(e))
            return Response(text=json.dumps(asdict(error_result)), content_type='application/json', status=500)

    async def handle_share_sheet(self, request: Request) -> Response:
        """Handle share sheet request"""
        try:
            data = await request.json()
            sheet_id = data.get("sheet_id")
            email = data.get("email")
            role = data.get("role", "reader")

            result = await self.share_spreadsheet(sheet_id, email, role)

            # Broadcast event
            await self.broadcast(SSEMessage(
                event="sheet_shared",
                data={
                    "type": "sheet_shared",
                    "sheet_id": sheet_id,
                    "email": email,
                    "role": role,
                    "result": result,
                    "timestamp": datetime.now().isoformat()
                }
            ))

            return Response(text=json.dumps(result), content_type='application/json')

        except Exception as e:
            logger.error(f"Share sheet error: {e}")
            return Response(text=json.dumps({"success": False, "error": str(e)}), content_type='application/json', status=500)

    async def create_spreadsheet(self, input_data: SheetsCreateInput) -> SheetsCreateOutput:
        """Create Google Sheet"""
        try:
            if not self.sheets_service:
                return SheetsCreateOutput(success=False, error="Sheets service not initialized")

            # Create spreadsheet
            spreadsheet_body = {
                'properties': {
                    'title': input_data.title
                },
                'sheets': [
                    {
                        'properties': {
                            'title': 'Sheet1'
                        }
                    }
                ]
            }

            spreadsheet = self.sheets_service.spreadsheets().create(
                body=spreadsheet_body,
                fields='spreadsheetId,spreadsheetUrl'
            ).execute()

            sheet_id = spreadsheet.get('spreadsheetId')
            sheet_url = spreadsheet.get('spreadsheetUrl')

            # Move to folder if specified
            if input_data.folder_id:
                await self.move_to_folder(sheet_id, input_data.folder_id)

            return SheetsCreateOutput(
                success=True,
                sheet_id=sheet_id,
                sheet_url=sheet_url
            )

        except HttpError as e:
            logger.error(f"Sheets API error: {e}")
            return SheetsCreateOutput(success=False, error=f"Sheets API error: {str(e)}")
        except Exception as e:
            logger.error(f"Create spreadsheet error: {e}")
            return SheetsCreateOutput(success=False, error=str(e))

    async def update_spreadsheet(self, input_data: SheetsUpdateInput) -> SheetsUpdateOutput:
        """Update Google Sheet"""
        try:
            if not self.sheets_service:
                return SheetsUpdateOutput(success=False, error="Sheets service not initialized")

            # Update range
            body = {
                'values': input_data.values
            }

            result = self.sheets_service.spreadsheets().values().update(
                spreadsheetId=input_data.sheet_id,
                range=input_data.range,
                valueInputOption='USER_ENTERED',
                body=body
            ).execute()

            updated_cells = result.get('updatedCells', 0)

            return SheetsUpdateOutput(
                success=True,
                updated_cells=updated_cells
            )

        except HttpError as e:
            logger.error(f"Sheets API error: {e}")
            return SheetsUpdateOutput(success=False, error=f"Sheets API error: {str(e)}")
        except Exception as e:
            logger.error(f"Update spreadsheet error: {e}")
            return SheetsUpdateOutput(success=False, error=str(e))

    async def share_spreadsheet(self, sheet_id: str, email: str = None, role: str = "reader") -> Dict[str, Any]:
        """Share spreadsheet"""
        try:
            # For sharing, we need Drive API
            from googleapiclient.discovery import build as build_drive

            if not self.credentials:
                return {"success": False, "error": "No credentials available"}

            drive_service = build('drive', 'v3', credentials=self.credentials)

            # Make sheet publicly accessible
            permission_body = {
                'role': role,
                'type': 'anyone'
            }

            permission = drive_service.permissions().create(
                fileId=sheet_id,
                body=permission_body
            ).execute()

            share_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit?usp=sharing"

            return {
                "success": True,
                "share_url": share_url,
                "permission_id": permission.get('id')
            }

        except HttpError as e:
            logger.error(f"Drive API error: {e}")
            return {"success": False, "error": f"Drive API error: {str(e)}"}
        except Exception as e:
            logger.error(f"Share spreadsheet error: {e}")
            return {"success": False, "error": str(e)}

    async def move_to_folder(self, sheet_id: str, folder_id: str):
        """Move spreadsheet to folder"""
        try:
            from googleapiclient.discovery import build as build_drive

            drive_service = build('drive', 'v3', credentials=self.credentials)

            # Get current parent
            file = drive_service.files().get(
                fileId=sheet_id,
                fields='parents'
            ).execute()

            previous_parents = ",".join(file.get('parents', []))

            # Move file to new folder
            drive_service.files().update(
                fileId=sheet_id,
                addParents=folder_id,
                removeParents=previous_parents,
                fields='id, parents'
            ).execute()

        except Exception as e:
            logger.error(f"Move to folder error: {e}")

    async def broadcast(self, message: SSEMessage):
        """Broadcast SSE message to all connected clients"""
        if not self.connections:
            logger.debug("No SSE connections to broadcast to")
            return

        # Format SSE message
        sse_data = self._format_sse_message(message)

        # Send to all connections
        disconnected = set()
        for connection in self.connections:
            try:
                connection.write(sse_data.encode('utf-8'))
                await connection.drain()
            except (ConnectionResetError, RuntimeError) as e:
                logger.warning(f"Failed to send to connection: {e}")
                disconnected.add(connection)

        # Remove dead connections
        for conn in disconnected:
            self.connections.discard(conn)

    def _format_sse_message(self, message: SSEMessage) -> str:
        """Format message as SSE format"""
        lines = []
        if message.event:
            lines.append(f"event: {message.event}")
        if message.id:
            lines.append(f"id: {message.id}")
        if message.retry:
            lines.append(f"retry: {message.retry}")

        # JSON serialize data
        data_str = json.dumps(message.data, ensure_ascii=False)
        lines.append(f"data: {data_str}")
        lines.append("")  # Empty line to end message
        lines.append("")  # Extra newline

        return "\n".join(lines)

    async def start(self):
        """Start the SSE server"""
        # Try to load existing credentials
        self.load_credentials()

        runner = web.AppRunner(self.app)
        await runner.setup()

        site = web.TCPSite(runner, self.host, self.port)
        await site.start()

        auth_method = "service account" if self.sheets_service else "OAuth"
        logger.info(f"🚀 Google Sheets SSE Server started on http://{self.host}:{self.port}")
        logger.info(f"📊 Auth method: {auth_method}")
        logger.info(f"💾 Health check: http://{self.host}:{self.port}/health")

async def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Google Sheets SSE MCP Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8082, help="Port to bind to")

    args = parser.parse_args()

    server = SheetsSSEServer(host=args.host, port=args.port)
    await server.start()

    # Keep server running
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("👋 Shutting down Sheets SSE server...")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Server stopped. Goodbye!")