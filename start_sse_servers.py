#!/usr/bin/env python3
"""
Startup script for all SSE servers
"""

import subprocess
import sys
import time
import requests
from pathlib import Path

def start_server(script_path, port, name):
    """Start an SSE server and verify it's running"""
    print(f"🚀 Starting {name} server on port {port}...")

    # Kill any existing process on this port
    try:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', port)) == 0:
                print(f"⚠️ Port {port} is already in use, you may need to kill existing processes")
    except:
        pass

    # Start the server
    try:
        process = subprocess.Popen([
            sys.executable, script_path, "--port", str(port)
        ], creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0)

        # Wait a moment for server to start
        time.sleep(3)

        # Check if server is healthy
        try:
            response = requests.get(f"http://localhost:{port}/health", timeout=5)
            if response.status_code == 200:
                print(f"✅ {name} server started successfully on port {port}")
                return process
            else:
                print(f"❌ {name} server not responding properly")
                return None
        except requests.exceptions.RequestException:
            print(f"⚠️ {name} server started but health check failed")
            return process  # Still return the process, might be starting up

    except Exception as e:
        print(f"❌ Failed to start {name} server: {e}")
        return None

def main():
    """Start all SSE servers"""
    print("🎯 Starting all SSE servers...")

    base_dir = Path(__file__).parent
    servers = [
        ("mcp_sse_gmail.py", 8081, "Gmail"),
        ("mcp_sse_sheets.py", 8082, "Sheets"),
        ("mcp_sse_gdrive.py", 8083, "GDrive")
    ]

    processes = []

    for script, port, name in servers:
        script_path = base_dir / script
        if script_path.exists():
            process = start_server(str(script_path), port, name)
            if process:
                processes.append((name, process))
        else:
            print(f"❌ Script not found: {script_path}")

    print("\n" + "="*50)
    print("📊 SSE Server Status:")
    for name, process in processes:
        status = "✅ Running" if process.poll() is None else "❌ Stopped"
        print(f"   {name}: {status}")
    print("="*50)

    print("\n🎉 SSE servers startup complete!")
    print("💡 You can now run: uv run main_telegram_agent.py")
    print("💡 Press Ctrl+C to stop all servers")

    try:
        # Keep the script running
        while True:
            time.sleep(1)
            # Check if any process died
            for name, process in processes[:]:
                if process.poll() is not None:
                    print(f"⚠️ {name} server has stopped")
                    processes.remove((name, process))
    except KeyboardInterrupt:
        print("\n🛑 Stopping all servers...")
        for name, process in processes:
            if process.poll() is None:
                process.terminate()
                print(f"✅ {name} server stopped")
        print("✅ All servers stopped")

if __name__ == "__main__":
    main()