#!/usr/bin/env python3
"""
Google Drive SSE MCP Server
Handles Google Drive operations via SSE transport
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

from models import GDriveShareInput, GDriveShareOutput

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gdrive-sse-server")

@dataclass
class SSEMessage:
    """SSE message structure"""
    event: str
    data: Dict[str, Any]
    id: Optional[str] = None
    retry: Optional[int] = None

class GDriveSSEServer:
    """Google Drive SSE MCP Server"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8083):
        self.host = host
        self.port = port
        self.app = web.Application()
        self.connections = set()
        self.message_queue = asyncio.Queue()
        self.credentials = None
        self.drive_service = None
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
        """Setup OAuth flow for Google Drive"""
        # Try service account first (recommended for server applications)
        service_account_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH")
        if service_account_file and os.path.exists(service_account_file):
            try:
                self.credentials = service_account.Credentials.from_service_account_file(
                    service_account_file,
                    scopes=['https://www.googleapis.com/auth/drive.file',
                           'https://www.googleapis.com/auth/drive.metadata']
                )
                # Create drive service immediately with service account
                self.drive_service = build('drive', 'v3', credentials=self.credentials)
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
            scopes=['https://www.googleapis.com/auth/drive.file',
                   'https://www.googleapis.com/auth/drive.metadata'],
            redirect_uri=redirect_uri
        )

    def setup_routes(self):
        """Setup API routes"""
        self.app.router.add_post('/drive/share', self.handle_share_file)
        self.app.router.add_post('/drive/upload', self.handle_upload_file)
        self.app.router.add_post('/drive/create_folder', self.handle_create_folder)
        self.app.router.add_get('/drive/list', self.handle_list_files)
        self.app.router.add_get('/drive/auth', self.handle_auth_request)
        self.app.router.add_get('/auth/callback', self.handle_auth_callback)
        self.app.router.add_get('/health', self.health_handler)
        self.app.router.add_get('/', self.root_handler)

    async def root_handler(self, request: Request) -> Response:
        """Root endpoint"""
        auth_status = "service_account" if self.drive_service else "not_authenticated"
        return Response(text=f"""
        <html>
        <head><title>Google Drive SSE MCP Server</title></head>
        <body>
            <h1>💾 Google Drive SSE MCP Server</h1>
            <p>Status: <span id="status">🟢 Running</span></p>
            <p>Auth: {auth_status}</p>
            <h2>Endpoints:</h2>
            <ul>
                <li><a href="/drive/auth">Drive Auth</a> - Authorize Drive access</li>
                <li><a href="/health">Health Check</a> - Server status</li>
                <li>/drive/share - Share file/folder</li>
                <li>/drive/upload - Upload file</li>
                <li>/drive/create_folder - Create folder</li>
                <li>/drive/list - List files</li>
            </ul>
        </body>
        </html>
        """, content_type='text/html')

    async def health_handler(self, request: Request) -> Response:
        """Health check endpoint"""
        auth_status = "service_account" if self.drive_service else "not_authenticated"
        return Response(
                text=json.dumps({
                    "status": "healthy",
                    "service": "gdrive",
                    "timestamp": datetime.now().isoformat(),
                    "auth_status": auth_status,
                    "connections": len(self.connections)
                }),
                content_type='application/json'
            )

    async def handle_auth_request(self, request: Request) -> Response:
        """Handle OAuth authorization request"""
        if self.drive_service:
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
                "message": "Visit this URL to authorize Google Drive access"
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

            # Create Drive service
            http = self.credentials.authorize(httplib2.Http())
            self.drive_service = build('drive', 'v3', http=http)

            # Store credentials for future use
            self.store_credentials()

            html_content = """
            <html>
            <head><title>Google Drive Authorization Complete</title></head>
            <body>
                <h1>✅ Google Drive Authorization Successful!</h1>
                <p>You can now use the Drive MCP tools.</p>
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
            creds_file = "drive_credentials.json"
            with open(creds_file, 'w') as f:
                f.write(self.credentials.to_json())
            logger.info(f"Credentials stored in {creds_file}")

    def load_credentials(self):
        """Load stored credentials"""
        if self.drive_service:
            return True  # Already loaded with service account

        creds_file = "drive_credentials.json"
        if os.path.exists(creds_file):
            try:
                self.credentials = Credentials.from_authorized_user_file(creds_file)
                if self.credentials.valid:
                    http = self.credentials.authorize(httplib2.Http())
                    self.drive_service = build('drive', 'v3', http=http)
                    logger.info("Loaded stored Drive credentials")
                    return True
            except Exception as e:
                logger.error(f"Failed to load credentials: {e}")
        return False

    async def handle_share_file(self, request: Request) -> Response:
        """Handle share file request"""
        try:
            # Load credentials if not already loaded
            if not self.drive_service and not self.load_credentials():
                return Response(
                    text=json.dumps({
                        "success": False,
                        "error": "Google Drive not authenticated. Please visit /drive/auth first"
                    }),
                    content_type='application/json',
                    status=401
                )

            data = await request.json()
            logger.info(f"Share file request: {data}")

            # Validate input
            share_input = GDriveShareInput(**data)

            # Share file
            result = await self.share_file(share_input)

            # Broadcast event
            await self.broadcast(SSEMessage(
                event="file_shared",
                data={
                    "type": "file_shared",
                    "file_id": share_input.file_id,
                    "email": share_input.email,
                    "role": share_input.role,
                    "result": asdict(result),
                    "timestamp": datetime.now().isoformat()
                }
            ))

            return Response(text=json.dumps(asdict(result)), content_type='application/json')

        except Exception as e:
            logger.error(f"Share file error: {e}")
            error_result = GDriveShareOutput(success=False, error=str(e))
            return Response(text=json.dumps(asdict(error_result)), content_type='application/json', status=500)

    async def handle_upload_file(self, request: Request) -> Response:
        """Handle upload file request"""
        try:
            if not self.drive_service and not self.load_credentials():
                return Response(json.dumps({
                    "success": False,
                    "error": "Google Drive not authenticated"
                }), content_type='application/json', status=401)

            data = await request.json()
            logger.info(f"Upload file request: {data}")

            result = await self.upload_file(
                data.get("filename"),
                data.get("content"),
                data.get("folder_id"),
                data.get("mime_type", "text/plain")
            )

            return Response(text=json.dumps(result), content_type='application/json')

        except Exception as e:
            logger.error(f"Upload file error: {e}")
            return Response(text=json.dumps({"success": False, "error": str(e)}), content_type='application/json', status=500)

    async def handle_create_folder(self, request: Request) -> Response:
        """Handle create folder request"""
        try:
            if not self.drive_service and not self.load_credentials():
                return Response(json.dumps({
                    "success": False,
                    "error": "Google Drive not authenticated"
                }), content_type='application/json', status=401)

            data = await request.json()
            folder_name = data.get("name")
            parent_folder_id = data.get("parent_id")

            result = await self.create_folder(folder_name, parent_folder_id)

            return Response(text=json.dumps(result), content_type='application/json')

        except Exception as e:
            logger.error(f"Create folder error: {e}")
            return Response(text=json.dumps({"success": False, "error": str(e)}), content_type='application/json', status=500)

    async def handle_list_files(self, request: Request) -> Response:
        """Handle list files request"""
        try:
            if not self.drive_service and not self.load_credentials():
                return Response(json.dumps({
                    "success": False,
                    "error": "Google Drive not authenticated"
                }), content_type='application/json', status=401)

            folder_id = request.query.get("folder_id")
            page_size = int(request.query.get("page_size", 10))

            result = await self.list_files(folder_id, page_size)

            return Response(text=json.dumps(result), content_type='application/json')

        except Exception as e:
            logger.error(f"List files error: {e}")
            return Response(text=json.dumps({"success": False, "error": str(e)}), content_type='application/json', status=500)

    async def share_file(self, input_data: GDriveShareInput) -> GDriveShareOutput:
        """Share file/folder on Google Drive"""
        try:
            if not self.drive_service:
                return GDriveShareOutput(success=False, error="Drive service not initialized")

            # Create permission
            permission_body = {
                'role': input_data.role
            }

            if input_data.email:
                permission_body['type'] = 'user'
                permission_body['emailAddress'] = input_data.email
            else:
                # Make it publicly accessible
                permission_body['type'] = 'anyone'

            permission = self.drive_service.permissions().create(
                fileId=input_data.file_id,
                body=permission_body,
                fields='id, role, type, emailAddress'
            ).execute()

            # Get file details for share URL
            file = self.drive_service.files().get(
                fileId=input_data.file_id,
                fields='name, mimeType, webViewLink'
            ).execute()

            share_url = file.get('webViewLink')
            if not share_url:
                # Construct share URL if not provided
                file_id = input_data.file_id
                share_url = f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"

            return GDriveShareOutput(
                success=True,
                share_url=share_url,
                permission_id=permission.get('id')
            )

        except HttpError as e:
            logger.error(f"Drive API error: {e}")
            return GDriveShareOutput(success=False, error=f"Drive API error: {str(e)}")
        except Exception as e:
            logger.error(f"Share file error: {e}")
            return GDriveShareOutput(success=False, error=str(e))

    async def upload_file(self, filename: str, content: str, folder_id: str = None, mime_type: str = "text/plain") -> Dict[str, Any]:
        """Upload file to Google Drive"""
        try:
            if not self.drive_service:
                return {"success": False, "error": "Drive service not initialized"}

            import io
            from googleapiclient.http import MediaIoBaseUpload

            # Create file metadata
            file_metadata = {
                'name': filename
            }

            if folder_id:
                file_metadata['parents'] = [folder_id]

            # Prepare file content
            file_stream = io.BytesIO(content.encode('utf-8'))
            media = MediaIoBaseUpload(file_stream, mimetype=mime_type)

            # Upload file
            file = self.drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id,name,webViewLink'
            ).execute()

            return {
                "success": True,
                "file_id": file.get('id'),
                "filename": file.get('name'),
                "view_url": file.get('webViewLink')
            }

        except HttpError as e:
            logger.error(f"Drive API error: {e}")
            return {"success": False, "error": f"Drive API error: {str(e)}"}
        except Exception as e:
            logger.error(f"Upload file error: {e}")
            return {"success": False, "error": str(e)}

    async def create_folder(self, folder_name: str, parent_folder_id: str = None) -> Dict[str, Any]:
        """Create folder in Google Drive"""
        try:
            if not self.drive_service:
                return {"success": False, "error": "Drive service not initialized"}

            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }

            if parent_folder_id:
                file_metadata['parents'] = [parent_folder_id]

            folder = self.drive_service.files().create(
                body=file_metadata,
                fields='id,name,webViewLink'
            ).execute()

            return {
                "success": True,
                "folder_id": folder.get('id'),
                "folder_name": folder.get('name'),
                "view_url": folder.get('webViewLink')
            }

        except HttpError as e:
            logger.error(f"Drive API error: {e}")
            return {"success": False, "error": f"Drive API error: {str(e)}"}
        except Exception as e:
            logger.error(f"Create folder error: {e}")
            return {"success": False, "error": str(e)}

    async def list_files(self, folder_id: str = None, page_size: int = 10) -> Dict[str, Any]:
        """List files in Google Drive"""
        try:
            if not self.drive_service:
                return {"success": False, "error": "Drive service not initialized"}

            query = f"'{folder_id}' in parents" if folder_id else "'root' in parents"

            results = self.drive_service.files().list(
                q=query,
                pageSize=page_size,
                fields="nextPageToken, files(id, name, mimeType, webViewLink, size, createdTime)"
            ).execute()

            files = results.get('files', [])

            return {
                "success": True,
                "files": files,
                "count": len(files)
            }

        except HttpError as e:
            logger.error(f"Drive API error: {e}")
            return {"success": False, "error": f"Drive API error: {str(e)}"}
        except Exception as e:
            logger.error(f"List files error: {e}")
            return {"success": False, "error": str(e)}

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

        auth_method = "service account" if self.drive_service else "OAuth"
        logger.info(f"🚀 Google Drive SSE Server started on http://{self.host}:{self.port}")
        logger.info(f"💾 Auth method: {auth_method}")
        logger.info(f"💾 Health check: http://{self.host}:{self.port}/health")

async def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Google Drive SSE MCP Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8083, help="Port to bind to")

    args = parser.parse_args()

    server = GDriveSSEServer(host=args.host, port=args.port)
    await server.start()

    # Keep server running
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("👋 Shutting down Drive SSE server...")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Server stopped. Goodbye!")