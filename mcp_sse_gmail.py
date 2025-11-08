#!/usr/bin/env python3
"""
Gmail SSE MCP Server
Handles Gmail operations via SSE transport
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

from models import GmailSendInput, GmailSendOutput, GmailSearchInput, GmailSearchOutput

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gmail-sse-server")

@dataclass
class SSEMessage:
    """SSE message structure"""
    event: str
    data: Dict[str, Any]
    id: Optional[str] = None
    retry: Optional[int] = None

class GmailSSEServer:
    """Gmail SSE MCP Server"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8081):
        self.host = host
        self.port = port
        self.app = web.Application()
        self.connections = set()
        self.message_queue = asyncio.Queue()
        self.credentials = None
        self.gmail_service = None
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
        """Setup authentication for Gmail"""
        # Try service account first (recommended for server applications)
        service_account_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH")
        if service_account_file and os.path.exists(service_account_file):
            try:
                # Normalize path for Windows
                service_account_file = os.path.normpath(service_account_file)
                self.credentials = service_account.Credentials.from_service_account_file(
                    service_account_file,
                    scopes=['https://www.googleapis.com/auth/gmail.send', 'https://www.googleapis.com/auth/gmail.readonly']
                )
                # Create gmail service immediately with service account
                self.gmail_service = build('gmail', 'v1', credentials=self.credentials)
                logger.info(f"✅ Service account loaded successfully from {service_account_file}")
                return
            except Exception as e:
                logger.error(f"Failed to load service account: {e}")
                logger.info("Falling back to OAuth authentication...")

        # Fall back to OAuth if service account fails
        client_secrets_file = os.getenv("GOOGLE_CLIENT_SECRETS_FILE")
        if not client_secrets_file:
            logger.warning("Neither service account nor OAuth configured. Please set GOOGLE_SERVICE_ACCOUNT_PATH or GOOGLE_CLIENT_SECRETS_FILE")
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
            scopes=['https://www.googleapis.com/auth/gmail.send', 'https://www.googleapis.com/auth/gmail.readonly'],
            redirect_uri=redirect_uri
        )

    def setup_routes(self):
        """Setup API routes"""
        self.app.router.add_post('/gmail/send', self.handle_send_email)
        self.app.router.add_post('/gmail/search', self.handle_search_emails)
        self.app.router.add_get('/gmail/auth', self.handle_auth_request)
        self.app.router.add_get('/auth/callback', self.handle_auth_callback)
        self.app.router.add_get('/health', self.health_handler)
        self.app.router.add_get('/', self.root_handler)

    async def root_handler(self, request: Request) -> Response:
        """Root endpoint"""
        return Response(text="""
        <html>
        <head><title>Gmail SSE MCP Server</title></head>
        <body>
            <h1>📧 Gmail SSE MCP Server</h1>
            <p>Status: <span id="status">🟢 Running</span></p>
            <h2>Endpoints:</h2>
            <ul>
                <li><a href="/gmail/auth">Gmail Auth</a> - Authorize Gmail access</li>
                <li><a href="/health">Health Check</a> - Server status</li>
                <li>/gmail/send - Send email</li>
                <li>/gmail/search - Search emails</li>
            </ul>
        </body>
        </html>
        """, content_type='text/html')

    async def health_handler(self, request: Request) -> Response:
        """Health check endpoint"""
        auth_status = "authenticated" if self.gmail_service else "not_authenticated"
        return Response(
                text=json.dumps({
                    "status": "healthy",
                    "service": "gmail",
                    "timestamp": datetime.now().isoformat(),
                    "auth_status": auth_status,
                    "connections": len(self.connections)
                }),
                content_type='application/json'
            )

    async def handle_auth_request(self, request: Request) -> Response:
        """Handle OAuth authorization request"""
        if not self.oauth_flow:
            return Response(text="OAuth not configured", status=500)

        auth_url, _ = self.oauth_flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true'
        )

        return Response(
            text=json.dumps({
                "auth_url": auth_url,
                "message": "Visit this URL to authorize Gmail access"
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

            # Create Gmail service
            self.gmail_service = build('gmail', 'v1', credentials=self.credentials)

            # Store credentials for future use
            self.store_credentials()

            html_content = """
            <html>
            <head><title>Gmail Authorization Complete</title></head>
            <body>
                <h1>✅ Gmail Authorization Successful!</h1>
                <p>You can now use the Gmail MCP tools.</p>
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
            creds_file = "gmail_credentials.json"
            try:
                with open(creds_file, 'w') as f:
                    f.write(self.credentials.to_json())
                logger.info(f"Credentials stored in {creds_file}")
            except Exception as e:
                logger.error(f"Failed to store credentials: {e}")

    def load_credentials(self):
        """Load stored credentials"""
        creds_file = "gmail_credentials.json"
        if os.path.exists(creds_file):
            try:
                from google.oauth2.credentials import Credentials
                self.credentials = Credentials.from_authorized_user_file(creds_file)
                if self.credentials.valid:
                    http = self.credentials.authorize(httplib2.Http())
                    self.gmail_service = build('gmail', 'v1', http=http)
                    logger.info("Loaded stored Gmail credentials")
                    return True
            except Exception as e:
                logger.error(f"Failed to load credentials: {e}")
        return False

    async def handle_send_email(self, request: Request) -> Response:
        """Handle send email request"""
        try:
            # Load credentials if not already loaded
            if not self.gmail_service and not self.load_credentials():
                return Response(
                    text=json.dumps({
                        "success": False,
                        "error": "Gmail not authenticated. Please visit /gmail/auth first"
                    }),
                    content_type='application/json',
                    status=401
                )

            data = await request.json()
            logger.info(f"Send email request: {data}")

            # Validate input
            send_input = GmailSendInput(**data)

            # Send email
            result = await self.send_email(send_input)

            # Broadcast event
            await self.broadcast(SSEMessage(
                event="email_sent",
                data={
                    "type": "email_sent",
                    "to": send_input.to,
                    "subject": send_input.subject,
                    "result": asdict(result),
                    "timestamp": datetime.now().isoformat()
                }
            ))

            return Response(text=json.dumps(asdict(result)), content_type='application/json')

        except Exception as e:
            logger.error(f"Send email error: {e}")
            error_result = GmailSendOutput(success=False, error=str(e))
            return Response(text=json.dumps(asdict(error_result)), content_type='application/json', status=500)

    async def handle_search_emails(self, request: Request) -> Response:
        """Handle search emails request"""
        try:
            # Load credentials if not already loaded
            if not self.gmail_service and not self.load_credentials():
                return Response(
                    text=json.dumps({
                        "success": False,
                        "error": "Gmail not authenticated. Please visit /gmail/auth first"
                    }),
                    content_type='application/json',
                    status=401
                )

            data = await request.json()
            logger.info(f"Search emails request: {data}")

            # Validate input
            search_input = GmailSearchInput(**data)

            # Search emails
            result = await self.search_emails(search_input)

            # Broadcast event
            await self.broadcast(SSEMessage(
                event="emails_searched",
                data={
                    "type": "emails_searched",
                    "query": search_input.query,
                    "result": asdict(result),
                    "timestamp": datetime.now().isoformat()
                }
            ))

            return Response(text=json.dumps(asdict(result)), content_type='application/json')

        except Exception as e:
            logger.error(f"Search emails error: {e}")
            error_result = GmailSearchOutput(emails=[], count=0, error=str(e))
            return Response(text=json.dumps(asdict(error_result)), content_type='application/json', status=500)

    async def send_email(self, input_data: GmailSendInput) -> GmailSendOutput:
        """Send email using Gmail API"""
        try:
            if not self.gmail_service:
                return GmailSendOutput(success=False, error="Gmail service not initialized")

            # Create email message
            message = self.create_message(input_data.to, input_data.subject, input_data.body)

            # Send message
            sent_message = self.gmail_service.users().messages().send(
                userId='me', body=message
            ).execute()

            return GmailSendOutput(
                success=True,
                message_id=sent_message['id']
            )

        except HttpError as e:
            logger.error(f"Gmail API error: {e}")
            return GmailSendOutput(success=False, error=f"Gmail API error: {str(e)}")
        except Exception as e:
            logger.error(f"Send email error: {e}")
            return GmailSendOutput(success=False, error=str(e))

    async def search_emails(self, input_data: GmailSearchInput) -> GmailSearchOutput:
        """Search emails using Gmail API"""
        try:
            if not self.gmail_service:
                return GmailSearchOutput(emails=[], count=0, error="Gmail service not initialized")

            # Search messages
            results = self.gmail_service.users().messages().list(
                userId='me',
                q=input_data.query,
                maxResults=input_data.limit
            ).execute()

            messages = results.get('messages', [])
            email_details = []

            # Get message details
            for msg in messages:
                message_detail = self.gmail_service.users().messages().get(
                    userId='me', id=msg['id'], format='metadata'
                ).execute()

                headers = {h['name']: h['value'] for h in message_detail['payload'].get('headers', [])}

                email_details.append({
                    'id': message_detail['id'],
                    'threadId': message_detail.get('threadId'),
                    'subject': headers.get('Subject', '(No Subject)'),
                    'from': headers.get('From', ''),
                    'to': headers.get('To', ''),
                    'date': headers.get('Date', ''),
                    'snippet': message_detail.get('snippet', '')
                })

            return GmailSearchOutput(
                emails=email_details,
                count=len(email_details)
            )

        except HttpError as e:
            logger.error(f"Gmail API error: {e}")
            return GmailSearchOutput(emails=[], count=0, error=f"Gmail API error: {str(e)}")
        except Exception as e:
            logger.error(f"Search emails error: {e}")
            return GmailSearchOutput(emails=[], count=0, error=str(e))

    def create_message(self, to: str, subject: str, body: str) -> Dict[str, Any]:
        """Create email message"""
        import base64
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        message = MIMEMultipart()
        message['to'] = to
        message['subject'] = subject

        msg = MIMEText(body, 'plain')
        message.attach(msg)

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        return {'raw': raw}

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

        logger.info(f"🚀 Gmail SSE Server started on http://{self.host}:{self.port}")
        logger.info(f"📧 Gmail auth: http://{self.host}:{self.port}/gmail/auth")
        logger.info(f"💾 Health check: http://{self.host}:{self.port}/health")

async def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Gmail SSE MCP Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8081, help="Port to bind to")

    args = parser.parse_args()

    server = GmailSSEServer(host=args.host, port=args.port)
    await server.start()

    # Keep server running
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("👋 Shutting down Gmail SSE server...")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Server stopped. Goodbye!")