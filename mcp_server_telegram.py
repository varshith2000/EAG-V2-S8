#!/usr/bin/env python3
"""
Telegram MCP Server - Integrates with Telegram Bot API
Provides tools for receiving and sending Telegram messages
"""

import asyncio
import json
import logging
import sys
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime

try:
    import aiohttp
    from mcp.server.models import InitializationOptions
    from mcp.server import NotificationOptions, Server
    from mcp.types import (
        Resource, Tool, TextContent, ImageContent, EmbeddedResource,
        LoggingLevel
    )
except ImportError as e:
    print(f"Missing required dependencies: {e}")
    print("Please install: pip install mcp aiohttp python-telegram-bot")
    sys.exit(1)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("telegram-mcp")

@dataclass
class TelegramConfig:
    bot_token: str
    chat_id: Optional[str] = None
    webhook_url: Optional[str] = None
    api_base: str = "https://api.telegram.org"

class TelegramMCPServer:
    def __init__(self, config: TelegramConfig):
        self.server = Server("telegram-mcp")
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        self.pending_messages: Dict[str, Dict] = {}
        self._setup_handlers()

    def _setup_handlers(self):
        """Set up MCP tool handlers"""

        @self.server.list_tools()
        async def handle_list_tools() -> List[Tool]:
            """List available Telegram tools"""
            return [
                Tool(
                    name="send_telegram_message",
                    description="Send a message to a Telegram chat",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "chat_id": {
                                "type": "string",
                                "description": "Telegram chat ID to send message to"
                            },
                            "text": {
                                "type": "string",
                                "description": "Message text to send"
                            },
                            "parse_mode": {
                                "type": "string",
                                "enum": ["HTML", "Markdown", "MarkdownV2"],
                                "description": "Optional parse mode for formatting",
                                "default": "HTML"
                            }
                        },
                        "required": ["chat_id", "text"]
                    }
                ),
                Tool(
                    name="get_telegram_updates",
                    description="Get recent updates/messages from Telegram",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "offset": {
                                "type": "integer",
                                "description": "Starting offset for updates",
                                "default": 0
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of updates to retrieve",
                                "default": 10
                            },
                            "timeout": {
                                "type": "integer",
                                "description": "Timeout in seconds for long polling",
                                "default": 30
                            }
                        },
                        "required": []
                    }
                ),
                Tool(
                    name="set_telegram_webhook",
                    description="Set up webhook for receiving Telegram messages",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "Webhook URL to receive updates"
                            },
                            "secret_token": {
                                "type": "string",
                                "description": "Optional secret token for webhook security"
                            }
                        },
                        "required": ["url"]
                    }
                ),
                Tool(
                    name="get_telegram_bot_info",
                    description="Get information about the Telegram bot",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                )
            ]

        @self.server.call_tool()
        async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
            """Handle tool calls"""
            try:
                if not self.session:
                    self.session = aiohttp.ClientSession()

                if name == "send_telegram_message":
                    return await self._send_message(arguments)
                elif name == "get_telegram_updates":
                    return await self._get_updates(arguments)
                elif name == "set_telegram_webhook":
                    return await self._set_webhook(arguments)
                elif name == "get_telegram_bot_info":
                    return await self._get_bot_info(arguments)
                else:
                    raise ValueError(f"Unknown tool: {name}")

            except Exception as e:
                logger.error(f"Error in tool {name}: {e}")
                return [TextContent(
                    type="text",
                    text=f"Error: {str(e)}"
                )]

    async def _send_message(self, args: Dict[str, Any]) -> List[TextContent]:
        """Send a message to Telegram"""
        chat_id = args["chat_id"]
        text = args["text"]
        parse_mode = args.get("parse_mode", "HTML")

        url = f"{self.config.api_base}/bot{self.config.bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode
        }

        async with self.session.post(url, json=payload) as response:
            if response.status == 200:
                result = await response.json()
                return [TextContent(
                    type="text",
                    text=f"✅ Message sent successfully to chat {chat_id}\nMessage ID: {result['result']['message_id']}"
                )]
            else:
                error_data = await response.text()
                return [TextContent(
                    type="text",
                    text=f"❌ Failed to send message: {response.status} - {error_data}"
                )]

    async def _get_updates(self, args: Dict[str, Any]) -> List[TextContent]:
        """Get updates from Telegram"""
        offset = args.get("offset", 0)
        limit = args.get("limit", 10)
        timeout = args.get("timeout", 30)

        url = f"{self.config.api_base}/bot{self.config.bot_token}/getUpdates"
        params = {
            "offset": offset,
            "limit": limit,
            "timeout": timeout
        }

        async with self.session.get(url, params=params) as response:
            if response.status == 200:
                result = await response.json()
                updates = result.get("result", [])

                if not updates:
                    return [TextContent(
                        type="text",
                        text="No new messages found"
                    )]

                messages = []
                for update in updates:
                    if "message" in update:
                        msg = update["message"]
                        chat_info = msg.get("chat", {})
                        from_info = msg.get("from", {})

                        message_text = f"""
📨 New Message:
From: {from_info.get('first_name', '')} {from_info.get('last_name', '')} (@{from_info.get('username', '')})
Chat ID: {chat_info.get('id', '')}
Chat Type: {chat_info.get('type', '')}
Message: {msg.get('text', '')}
Time: {datetime.fromtimestamp(msg.get('date', 0)).strftime('%Y-%m-%d %H:%M:%S')}
Update ID: {update.get('update_id', '')}
                        """
                        messages.append(message_text.strip())

                return [TextContent(
                    type="text",
                    text=f"Found {len(messages)} messages:\n\n" + "\n\n" + "="*50 + "\n\n".join(messages)
                )]
            else:
                error_data = await response.text()
                return [TextContent(
                    type="text",
                    text=f"❌ Failed to get updates: {response.status} - {error_data}"
                )]

    async def _set_webhook(self, args: Dict[str, Any]) -> List[TextContent]:
        """Set webhook for Telegram bot"""
        webhook_url = args["url"]
        secret_token = args.get("secret_token")

        url = f"{self.config.api_base}/bot{self.config.bot_token}/setWebhook"
        payload = {"url": webhook_url}
        if secret_token:
            payload["secret_token"] = secret_token

        async with self.session.post(url, json=payload) as response:
            if response.status == 200:
                result = await response.json()
                if result.get("ok"):
                    return [TextContent(
                        type="text",
                        text=f"✅ Webhook set successfully: {webhook_url}"
                    )]
                else:
                    return [TextContent(
                        type="text",
                        text=f"❌ Failed to set webhook: {result.get('description', 'Unknown error')}"
                    )]
            else:
                error_data = await response.text()
                return [TextContent(
                    type="text",
                    text=f"❌ Failed to set webhook: {response.status} - {error_data}"
                )]

    async def _get_bot_info(self, args: Dict[str, Any]) -> List[TextContent]:
        """Get bot information"""
        url = f"{self.config.api_base}/bot{self.config.bot_token}/getMe"

        async with self.session.get(url) as response:
            if response.status == 200:
                result = await response.json()
                if result.get("ok"):
                    bot = result["result"]
                    info = f"""
🤖 Bot Information:
Username: @{bot['username']}
Name: {bot['first_name']} {bot.get('last_name', '')}
ID: {bot['id']}
Can Read Messages: {bot.get('can_read_all_group_messages', False)}
Supports Inline Queries: {bot.get('supports_inline_queries', False)}
                    """
                    return [TextContent(type="text", text=info.strip())]
                else:
                    return [TextContent(
                        type="text",
                        text=f"❌ Failed to get bot info: {result.get('description', 'Unknown error')}"
                    )]
            else:
                error_data = await response.text()
                return [TextContent(
                    type="text",
                    text=f"❌ Failed to get bot info: {response.status} - {error_data}"
                )]

    async def run(self):
        """Run the MCP server"""
        logger.info("Starting Telegram MCP Server...")

        # Initialize session
        self.session = aiohttp.ClientSession()

        try:
            # Run the MCP server
            from mcp.server.stdio import stdio_server

            async with stdio_server() as (read_stream, write_stream):
                await self.server.run(
                    read_stream,
                    write_stream,
                    InitializationOptions(
                        server_name="telegram-mcp",
                        server_version="1.0.0",
                        capabilities=self.server.get_capabilities(
                            notification_options=NotificationOptions(),
                            experimental_capabilities={},
                        ),
                    ),
                )
        finally:
            if self.session:
                await self.session.close()

async def main():
    """Main entry point"""
    import os
    from dotenv import load_dotenv

    load_dotenv()

    # Get Telegram bot token from environment
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        print("❌ ERROR: TELEGRAM_BOT_TOKEN environment variable is required")
        print("Please create a Telegram bot and set the token in your .env file")
        sys.exit(1)

    config = TelegramConfig(bot_token=bot_token)
    server = TelegramMCPServer(config)
    await server.run()

if __name__ == "__main__":
    asyncio.run(main())