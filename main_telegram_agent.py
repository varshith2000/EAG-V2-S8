#!/usr/bin/env python3
"""
Main Telegram Agent Server
Listens for Telegram messages and orchestrates the F1 workflow
"""

import asyncio
import json
import logging
import os
import sys
import time
from typing import Dict, Any, List
from datetime import datetime

import requests
from dotenv import load_dotenv

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.hybrid_session import create_hybrid_mcp
from workflows.f1_automation import F1Workflow

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("telegram-agent")

class TelegramAgentServer:
    """Main Telegram Agent Server"""

    def __init__(self):
        self.bot_token = None
        self.mcp = None
        self.f1_workflow = None
        self.running = False
        self.last_update_id = 0

    async def initialize(self):
        """Initialize the agent"""
        logger.info("🚀 Initializing Telegram Agent Server...")

        # Load environment variables
        load_dotenv()
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")

        if not self.bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN not configured")

        # Initialize MCP servers
        try:
            self.mcp = create_hybrid_mcp()
            await self.mcp.initialize()
            logger.info("✅ MCP servers initialized")

            # Initialize F1 workflow
            self.f1_workflow = F1Workflow(self.mcp)
            logger.info("✅ F1 workflow initialized")

        except Exception as e:
            logger.error(f"❌ Failed to initialize MCP: {e}")
            # Continue anyway - we'll use basic functionality

        # Test bot connection
        await self.test_bot_connection()
        logger.info("✅ Telegram Agent Server initialized successfully")

    async def test_bot_connection(self):
        """Test bot connection"""
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/getMe"
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            result = response.json()
            if result.get("ok"):
                bot_info = result["result"]
                logger.info(f"✅ Connected to bot: @{bot_info['username']} ({bot_info['first_name']})")
            else:
                raise RuntimeError(f"Bot API error: {result.get('description')}")

        except Exception as e:
            logger.error(f"❌ Failed to connect to bot: {e}")
            raise

    async def start_polling(self):
        """Start polling for Telegram messages"""
        logger.info("📡 Starting Telegram message polling...")
        self.running = True

        while self.running:
            try:
                await self.get_updates()
                await asyncio.sleep(1)  # Poll every second

            except Exception as e:
                logger.error(f"Error in polling loop: {e}")
                await asyncio.sleep(5)  # Wait before retrying

    async def get_updates(self):
        """Get updates from Telegram"""
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
            params = {
                "timeout": 0,  # No timeout for short polling
                "offset": self.last_update_id + 1 if self.last_update_id else None,
                "limit": 10
            }

            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()

            result = response.json()
            if result.get("ok"):
                updates = result.get("result", [])
                for update in updates:
                    await self.process_update(update)
                    self.last_update_id = update["update_id"]

        except requests.exceptions.RequestException as e:
            # Don't log network errors too frequently
            if "timeout" not in str(e).lower():
                logger.warning(f"Network error getting updates: {e}")
        except Exception as e:
            logger.error(f"Error getting updates: {e}")

    async def process_update(self, update: Dict[str, Any]):
        """Process a single update"""
        try:
            # Handle messages
            if "message" in update:
                await self.process_message(update["message"])

            # Handle channel posts
            elif "channel_post" in update:
                await self.process_message(update["channel_post"], is_channel=True)

        except Exception as e:
            logger.error(f"Error processing update: {e}")

    async def process_message(self, message: Dict[str, Any], is_channel: bool = False):
        """Process a message"""
        try:
            message_id = message.get("message_id")
            chat = message.get("chat", {})
            user = message.get("from", {})
            text = message.get("text", "")

            chat_id = chat.get("id")
            chat_type = chat.get("type", "private")

            # Skip empty messages or commands (except /start)
            if not text:
                return

            # Log message
            sender_name = user.get("first_name", "Unknown")
            if is_channel:
                logger.info(f"📢 Channel message from {chat.get('title', 'Unknown')}: {text}")
            else:
                logger.info(f"💬 Message from {sender_name} (chat_id: {chat_id}): {text}")

            # Handle /start command
            if text.startswith("/start"):
                await self.send_welcome_message(chat_id, sender_name)
                return

            # Check if it's an F1 standings request
            if self.f1_workflow and self.f1_workflow.is_f1_request(text):
                logger.info(f"🏁 F1 standings request detected from {sender_name}")
                await self.send_typing_indicator(chat_id)

                # Execute F1 workflow
                result = await self.f1_workflow.execute_f1_standings_workflow(chat_id, text)

                if result.get("success"):
                    logger.info(f"✅ F1 workflow completed successfully for {sender_name}")
                else:
                    logger.error(f"❌ F1 workflow failed for {sender_name}: {result.get('error')}")
                return

            # Handle other messages with basic response
            await self.send_basic_response(chat_id, text, sender_name)

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            await self.send_error_message(chat_id, "Sorry, I encountered an error processing your message.")

    async def send_welcome_message(self, chat_id: int, user_name: str):
        """Send welcome message"""
        message = f"""
👋 Hello {user_name}!

I'm the **Cortex-R F1 Agent** 🏁

I can help you with:
• Current F1 driver standings
• Create Google Sheets with F1 data
• Email you F1 reports

Just ask me: *"Find the Current Point Standings of F1 Racers"*

🤖 Powered by Google APIs & Telegram
        """
        await self.send_telegram_message(chat_id, message)

    async def send_basic_response(self, chat_id: int, text: str, user_name: str):
        """Send basic response for non-F1 messages"""
        message = f"""
Hi {user_name}! 👋

I'm specialized in F1 standings automation.

To get current F1 driver standings, try:
*"Find the Current Point Standings of F1 Racers"*

I'll create a Google Sheet with the data and email it to you! 🏁

📊 What I do:
• Fetch current F1 standings
• Create Google Sheets automatically
• Send reports via email
• Share sheet links on Telegram

Type the F1 request above to get started! 🚀
        """
        await self.send_telegram_message(chat_id, message)

    async def send_error_message(self, chat_id: int, error: str):
        """Send error message"""
        message = f"""
❌ **Oops! Something went wrong**

{error}

Please try again in a moment. If the problem persists, check:
• Internet connection
• Server status

🤖 Cortex-R Agent
        """
        await self.send_telegram_message(chat_id, message)

    async def send_typing_indicator(self, chat_id: int):
        """Send typing indicator"""
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendChatAction"
            payload = {
                "chat_id": chat_id,
                "action": "typing"
            }
            requests.post(url, json=payload, timeout=5)
        except Exception:
            pass  # Ignore typing indicator errors

    async def send_telegram_message(self, chat_id: int, message: str):
        """Send message to Telegram"""
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML"
            }

            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()

            result = response.json()
            if result.get("ok"):
                logger.debug(f"Message sent to chat {chat_id}")
            else:
                logger.error(f"Failed to send message: {result.get('description')}")

        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")

    async def shutdown(self):
        """Shutdown the server"""
        logger.info("🛑 Shutting down Telegram Agent Server...")
        self.running = False

        if self.mcp:
            await self.mcp.shutdown()

        logger.info("✅ Telegram Agent Server shutdown complete")

    async def show_status(self):
        """Show current status"""
        logger.info("\n" + "=" * 60)
        logger.info("📊 Telegram Agent Server Status:")
        logger.info("=" * 60)

        if self.mcp:
            status = await self.mcp.get_server_status()
            logger.info(f"🤖 MCP Status: {'✅ Running' if status['running'] else '❌ Stopped'}")

            # Show stdio servers
            for server_id, info in status["stdio_servers"].items():
                state = "🟢 Running" if info["running"] else "🔴 Stopped"
                logger.info(f"   {server_id}: {state}")

            # Show SSE servers
            for server_id, info in status["sse_servers"].items():
                state = "🟢 Connected" if info["connected"] else "🔴 Disconnected"
                logger.info(f"   {server_id}: {state}")

        else:
            logger.info("🤖 MCP Status: ❌ Not initialized")

        logger.info("📱 Telegram Bot: ✅ Connected")
        logger.info("🏁 F1 Workflow: ✅ Ready")
        logger.info("=" * 60)

async def main():
    """Main entry point"""
    agent = TelegramAgentServer()

    try:
        # Initialize
        await agent.initialize()

        # Show status
        await agent.show_status()

        # Start polling
        await agent.start_polling()

    except KeyboardInterrupt:
        logger.info("👋 Received keyboard interrupt")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
    finally:
        await agent.shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Telegram Agent Server stopped. Goodbye!")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)