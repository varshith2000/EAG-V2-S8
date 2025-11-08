#!/usr/bin/env python3
"""
Telegram MCP Server (stdio transport)
Handles Telegram bot operations via stdio
"""

import asyncio
import json
import sys
import os
from typing import Dict, Any, List
import logging

from mcp.server.fastmcp import FastMCP
from models import TelegramSendInput, TelegramSendOutput, TelegramHistoryInput, TelegramHistoryOutput

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("telegram-stdio-server")

mcp = FastMCP("TelegramBot")

@mcp.tool()
def send_telegram_message(input: TelegramSendInput) -> TelegramSendOutput:
    """Send message to Telegram chat. Usage: send_telegram_message|input={"chat_id": 123456789, "message": "Hello!"}"""
    try:
        import requests
        from dotenv import load_dotenv
        load_dotenv()

        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            logger.error("TELEGRAM_BOT_TOKEN not configured")
            return TelegramSendOutput(success=False, error="TELEGRAM_BOT_TOKEN not configured")

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": input.chat_id,
            "text": input.message,
            "parse_mode": "HTML"
        }

        logger.info(f"Sending Telegram message to chat {input.chat_id}")

        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()

        result = response.json()
        if result.get("ok"):
            message_id = result["result"]["message_id"]
            logger.info(f"Message sent successfully, message_id: {message_id}")
            return TelegramSendOutput(success=True, message_id=message_id)
        else:
            error_msg = result.get("description", "Unknown error")
            logger.error(f"Telegram API error: {error_msg}")
            return TelegramSendOutput(success=False, error=error_msg)

    except requests.exceptions.RequestException as e:
        logger.error(f"Request error sending Telegram message: {e}")
        return TelegramSendOutput(success=False, error=f"Request error: {str(e)}")
    except Exception as e:
        logger.error(f"Error sending Telegram message: {e}")
        return TelegramSendOutput(success=False, error=str(e))

@mcp.tool()
def get_telegram_updates(input: TelegramHistoryInput) -> TelegramHistoryOutput:
    """Get recent Telegram messages. Usage: get_telegram_updates|input={"limit": 10}"""
    try:
        import requests
        from dotenv import load_dotenv
        load_dotenv()

        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            logger.error("TELEGRAM_BOT_TOKEN not configured")
            return TelegramHistoryOutput(messages=[], error="TELEGRAM_BOT_TOKEN not configured")

        url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
        params = {"limit": input.limit, "offset": input.offset, "timeout": 0}

        logger.info(f"Getting Telegram updates, limit: {input.limit}, offset: {input.offset}")

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        result = response.json()
        if result.get("ok"):
            updates = result.get("result", [])
            messages = []

            for update in updates:
                if "message" in update:
                    msg = update["message"]
                    messages.append({
                        "message_id": msg["message_id"],
                        "chat_id": msg["chat"]["id"],
                        "text": msg.get("text", ""),
                        "from_user": msg["from"]["first_name"] if "from" in msg else "Unknown",
                        "date": msg["date"],
                        "update_id": update["update_id"]
                    })
                elif "channel_post" in update:
                    post = update["channel_post"]
                    messages.append({
                        "message_id": post["message_id"],
                        "chat_id": post["chat"]["id"],
                        "text": post.get("text", ""),
                        "from_user": "Channel",
                        "date": post["date"],
                        "update_id": update["update_id"]
                    })

            logger.info(f"Retrieved {len(messages)} messages")
            return TelegramHistoryOutput(messages=messages)
        else:
            error_msg = result.get("description", "Unknown error")
            logger.error(f"Telegram API error: {error_msg}")
            return TelegramHistoryOutput(messages=[], error=error_msg)

    except requests.exceptions.RequestException as e:
        logger.error(f"Request error getting Telegram updates: {e}")
        return TelegramHistoryOutput(messages=[], error=f"Request error: {str(e)}")
    except Exception as e:
        logger.error(f"Error getting Telegram updates: {e}")
        return TelegramHistoryOutput(messages=[], error=str(e))

@mcp.tool()
def get_bot_info() -> Dict[str, Any]:
    """Get bot information. Usage: get_bot_info"""
    try:
        import requests
        from dotenv import load_dotenv
        load_dotenv()

        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            return {"success": False, "error": "TELEGRAM_BOT_TOKEN not configured"}

        url = f"https://api.telegram.org/bot{bot_token}/getMe"

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        result = response.json()
        if result.get("ok"):
            bot_info = result["result"]
            return {
                "success": True,
                "bot_info": {
                    "id": bot_info["id"],
                    "username": bot_info["username"],
                    "first_name": bot_info["first_name"],
                    "is_bot": bot_info["is_bot"]
                }
            }
        else:
            error_msg = result.get("description", "Unknown error")
            return {"success": False, "error": error_msg}

    except Exception as e:
        logger.error(f"Error getting bot info: {e}")
        return {"success": False, "error": str(e)}

@mcp.tool()
def set_webhook(webhook_url: str) -> Dict[str, Any]:
    """Set webhook for Telegram bot. Usage: set_webhook|webhook_url="https://your-domain.com/webhook"""
    try:
        import requests
        from dotenv import load_dotenv
        load_dotenv()

        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            return {"success": False, "error": "TELEGRAM_BOT_TOKEN not configured"}

        url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
        payload = {"url": webhook_url}

        logger.info(f"Setting Telegram webhook to: {webhook_url}")

        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()

        result = response.json()
        if result.get("ok"):
            return {"success": True, "webhook_url": webhook_url}
        else:
            error_msg = result.get("description", "Unknown error")
            logger.error(f"Failed to set webhook: {error_msg}")
            return {"success": False, "error": error_msg}

    except Exception as e:
        logger.error(f"Error setting webhook: {e}")
        return {"success": False, "error": str(e)}

@mcp.tool()
def delete_webhook() -> Dict[str, Any]:
    """Delete webhook for Telegram bot. Usage: delete_webhook"""
    try:
        import requests
        from dotenv import load_dotenv
        load_dotenv()

        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            return {"success": False, "error": "TELEGRAM_BOT_TOKEN not configured"}

        url = f"https://api.telegram.org/bot{bot_token}/deleteWebhook"

        logger.info("Deleting Telegram webhook")

        response = requests.post(url, timeout=30)
        response.raise_for_status()

        result = response.json()
        if result.get("ok"):
            return {"success": True, "message": "Webhook deleted"}
        else:
            error_msg = result.get("description", "Unknown error")
            logger.error(f"Failed to delete webhook: {error_msg}")
            return {"success": False, "error": error_msg}

    except Exception as e:
        logger.error(f"Error deleting webhook: {e}")
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    logger.info("Starting Telegram MCP Server (stdio transport)")

    # Test if bot token is available
    from dotenv import load_dotenv
    load_dotenv()

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if bot_token:
        logger.info("✅ TELEGRAM_BOT_TOKEN found")
    else:
        logger.error("❌ TELEGRAM_BOT_TOKEN not configured")

    try:
        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        logger.info("👋 Telegram MCP Server stopped")
    except Exception as e:
        logger.error(f"❌ Telegram MCP Server error: {e}")
        sys.exit(1)