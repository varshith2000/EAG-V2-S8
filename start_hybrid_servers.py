#!/usr/bin/env python3
"""
Startup script for hybrid MCP server architecture
Starts all SSE servers and provides monitoring
"""

import asyncio
import logging
import subprocess
import sys
import os
import signal
from pathlib import Path
from typing import Dict, List, Any

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("startup")

class HybridServerManager:
    """Manager for hybrid MCP server architecture"""

    def __init__(self):
        self.processes = {}
        self.servers = [
            {
                "name": "Gmail SSE",
                "script": "mcp_sse_gmail.py",
                "port": 8091,
                "description": "Gmail API server"
            },
            {
                "name": "Sheets SSE",
                "script": "mcp_sse_sheets.py",
                "port": 8092,
                "description": "Google Sheets API server"
            },
            {
                "name": "GDrive SSE",
                "script": "mcp_sse_gdrive.py",
                "port": 8093,
                "description": "Google Drive API server"
            }
        ]
        self.running = False
        self.shutdown_requested = False

    async def start_servers(self) -> bool:
        """Start all SSE servers"""
        logger.info("🚀 Starting Hybrid MCP Server Architecture...")
        logger.info("=" * 60)

        # Check if required files exist
        await self._check_prerequisites()

        # Start each SSE server
        success_count = 0
        for server in self.servers:
            if await self._start_server(server):
                success_count += 1

        if success_count == len(self.servers):
            logger.info("=" * 60)
            logger.info("🎉 All SSE servers started successfully!")
            logger.info("\n📡 Server Endpoints:")
            for server in self.servers:
                status = "✅" if server["name"] in self.processes else "❌"
                logger.info(f"   {status} {server['name']}: http://localhost:{server['port']}")

            logger.info(f"\n🔗 Health Checks:")
            for server in self.servers:
                logger.info(f"   http://localhost:{server['port']}/health")

            logger.info("\n🏁 Telegram Bot will connect to these servers automatically!")
            logger.info("💡 Send 'F1 standings' to your Telegram bot to test the workflow")

            self.running = True
            return True
        else:
            logger.error(f"❌ Only {success_count}/{len(self.servers)} servers started successfully")
            await self.shutdown()
            return False

    async def _check_prerequisites(self):
        """Check if required files and dependencies exist"""
        logger.info("🔍 Checking prerequisites...")

        # Check .env file
        env_file = Path(".env")
        if not env_file.exists():
            logger.warning("⚠️ .env file not found")
        else:
            logger.info("✅ .env file found")

        # Check service account file
        service_account_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH", "credentials.json")
        service_account_file = Path(service_account_path)
        if not service_account_file.exists():
            logger.error(f"❌ Service account file not found: {service_account_path}")
            logger.error("   Please download the JSON service account key from Google Cloud Console")
        else:
            logger.info(f"✅ Service account file found: {service_account_path}")

        # Check server scripts
        for server in self.servers:
            script_file = Path(server["script"])
            if not script_file.exists():
                logger.error(f"❌ Server script not found: {server['script']}")
            else:
                logger.info(f"✅ Server script found: {server['script']}")

        # Check required Python packages
        try:
            import aiohttp
            import aiohttp_cors
            import google.auth
            import googleapiclient
            logger.info("✅ Required Python packages installed")
        except ImportError as e:
            logger.error(f"❌ Missing required package: {e}")
            logger.error("   Run: pip install aiohttp aiohttp-cors google-api-python-client google-auth google-auth-oauthlib")

        logger.info("✅ Prerequisite check complete\n")

    async def _start_server(self, server: Dict[str, Any]) -> bool:
        """Start a single server"""
        name = server["name"]
        script = server["script"]
        port = server["port"]

        logger.info(f"🚀 Starting {name} on port {port}...")

        try:
            # Create process
            process = subprocess.Popen(
                [sys.executable, script, "--port", str(port)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )

            # Store process info
            self.processes[name] = {
                "process": process,
                "script": script,
                "port": port,
                "description": server["description"]
            }

            # Give server time to start
            await asyncio.sleep(3)

            # Check if process is still running
            if process.poll() is None:
                logger.info(f"✅ {name} started successfully (PID: {process.pid})")
                return True
            else:
                # Process died, check stderr
                stderr_output = process.stderr.read()
                logger.error(f"❌ {name} failed to start:")
                logger.error(f"   {stderr_output}")
                del self.processes[name]
                return False

        except Exception as e:
            logger.error(f"❌ Failed to start {name}: {e}")
            return False

    async def monitor_servers(self):
        """Monitor server health and restart if needed"""
        logger.info("👁️ Starting server health monitoring...")

        while self.running and not self.shutdown_requested:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds

                for name, info in list(self.processes.items()):
                    process = info["process"]

                    if process.poll() is not None:
                        logger.warning(f"⚠️ {name} has stopped (exit code: {process.returncode})")

                        # Try to restart
                        logger.info(f"🔄 Attempting to restart {name}...")
                        server_config = next(
                            (s for s in self.servers if s["name"] == name),
                            None
                        )

                        if server_config:
                            if await self._start_server(server_config):
                                logger.info(f"✅ {name} restarted successfully")
                            else:
                                logger.error(f"❌ Failed to restart {name}")
                                del self.processes[name]

            except Exception as e:
                logger.error(f"Error in server monitoring: {e}")

    async def health_check_loop(self):
        """Periodic health check of all servers"""
        import aiohttp

        while self.running and not self.shutdown_requested:
            try:
                await asyncio.sleep(60)  # Check every minute

                async with aiohttp.ClientSession() as session:
                    for name, info in self.processes.items():
                        port = info["port"]
                        health_url = f"http://localhost:{port}/health"

                        try:
                            async with session.get(health_url, timeout=5) as resp:
                                if resp.status == 200:
                                    logger.debug(f"✅ {name} health check passed")
                                else:
                                    logger.warning(f"⚠️ {name} health check failed: HTTP {resp.status}")
                        except Exception as e:
                            logger.warning(f"⚠️ {name} health check failed: {e}")

            except Exception as e:
                logger.error(f"Health check loop error: {e}")

    async def shutdown(self):
        """Gracefully shutdown all servers"""
        logger.info("🛑 Shutting down servers...")
        self.running = False
        self.shutdown_requested = True

        for name, info in self.processes.items():
            process = info["process"]
            logger.info(f"Stopping {name} (PID: {process.pid})...")

            try:
                # Try graceful shutdown
                process.terminate()
                try:
                    process.wait(timeout=10)
                    logger.info(f"✅ {name} stopped gracefully")
                except subprocess.TimeoutExpired:
                    # Force kill if graceful shutdown fails
                    process.kill()
                    process.wait()
                    logger.info(f"🔥 {name} force killed")
            except Exception as e:
                logger.error(f"Error stopping {name}: {e}")

        self.processes.clear()
        logger.info("✅ All servers stopped")

    def _handle_signal(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"\n📡 Received signal {signum}, initiating shutdown...")
        self.shutdown_requested = True

    async def show_status(self):
        """Show current server status"""
        logger.info("\n" + "=" * 60)
        logger.info("📊 Server Status:")
        logger.info("=" * 60)

        for name, info in self.processes.items():
            process = info["process"]
            status = "🟢 Running" if process.poll() is None else "🔴 Stopped"
            pid = process.pid if process.poll() is None else "N/A"
            port = info["port"]
            description = info["description"]

            logger.info(f"   {name}:")
            logger.info(f"     Status: {status}")
            logger.info(f"     PID: {pid}")
            logger.info(f"     Port: {port}")
            logger.info(f"     Description: {description}")
            logger.info("")

async def main():
    """Main entry point"""
    # Setup signal handlers
    manager = HybridServerManager()

    # Register signal handlers
    if hasattr(signal, 'SIGINT'):
        signal.signal(signal.SIGINT, manager._handle_signal)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, manager._handle_signal)

    try:
        # Start servers
        if await manager.start_servers():
            # Show initial status
            await manager.show_status()

            # Start monitoring tasks
            monitor_task = asyncio.create_task(manager.monitor_servers())
            health_task = asyncio.create_task(manager.health_check_loop())

            # Wait for shutdown signal
            while manager.running and not manager.shutdown_requested:
                await asyncio.sleep(1)

            # Cancel monitoring tasks
            monitor_task.cancel()
            health_task.cancel()

            # Shutdown servers
            await manager.shutdown()

    except KeyboardInterrupt:
        logger.info("👋 Received keyboard interrupt")
    except Exception as e:
        logger.error(f"❌ Startup error: {e}")
    finally:
        await manager.shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Server startup interrupted. Goodbye!")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)