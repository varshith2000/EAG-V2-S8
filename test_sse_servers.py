#!/usr/bin/env python3
"""
Simple test script to debug SSE server issues
"""

import asyncio
import aiohttp
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test-sse")

async def test_server_health(url: str, server_name: str):
    """Test server health endpoint"""
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{url}/health") as resp:
                status = resp.status
                try:
                    data = await resp.json()
                    logger.info(f"✅ {server_name}: HTTP {status} - {data}")
                    return status == 200
                except Exception as e:
                    text = await resp.text()
                    logger.error(f"❌ {server_name}: HTTP {status} - JSON parse error: {e}")
                    logger.error(f"Response text: {text}")
                    return False
    except Exception as e:
        logger.error(f"❌ {server_name}: Connection error: {e}")
        return False

async def test_server_endpoint(url: str, server_name: str, endpoint: str, payload: dict):
    """Test a specific server endpoint"""
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(f"{url}{endpoint}", json=payload) as resp:
                status = resp.status
                try:
                    data = await resp.json()
                    logger.info(f"✅ {server_name} {endpoint}: HTTP {status} - {data}")
                    return status == 200, data
                except Exception as e:
                    text = await resp.text()
                    logger.error(f"❌ {server_name} {endpoint}: HTTP {status} - JSON parse error: {e}")
                    logger.error(f"Response text: {text}")
                    return status == 200, None
    except Exception as e:
        logger.error(f"❌ {server_name} {endpoint}: Connection error: {e}")
        return False, None

async def main():
    """Test all SSE servers"""
    servers = [
        {"name": "Gmail", "url": "http://localhost:8081"},
        {"name": "Sheets", "url": "http://localhost:8082"},
        {"name": "GDrive", "url": "http://localhost:8083"}
    ]

    logger.info("🔍 Testing SSE Server Health...")
    healthy_servers = []

    for server in servers:
        is_healthy = await test_server_health(server["url"], server["name"])
        if is_healthy:
            healthy_servers.append(server)

    logger.info(f"📊 Health check complete. {len(healthy_servers)}/{len(servers)} servers healthy")

    if healthy_servers:
        logger.info("\n🧪 Testing API endpoints...")

        # Test Sheets create endpoint
        sheets_server = next((s for s in healthy_servers if s["name"] == "Sheets"), None)
        if sheets_server:
            success, result = await test_server_endpoint(
                sheets_server["url"],
                "Sheets",
                "/sheets/create",
                {"title": "Test Sheet"}
            )
            if success:
                logger.info(f"✅ Sheets API working! Sheet URL: {result.get('sheet_url', 'N/A')}")
            else:
                logger.error("❌ Sheets API failed")

        # Test Gmail endpoint
        gmail_server = next((s for s in healthy_servers if s["name"] == "Gmail"), None)
        if gmail_server:
            success, result = await test_server_endpoint(
                gmail_server["url"],
                "Gmail",
                "/gmail/send",
                {
                    "to": "test@example.com",
                    "subject": "Test Email",
                    "body": "This is a test email"
                }
            )
            if success:
                logger.info("✅ Gmail API working!")
            else:
                logger.error("❌ Gmail API failed")

if __name__ == "__main__":
    asyncio.run(main())