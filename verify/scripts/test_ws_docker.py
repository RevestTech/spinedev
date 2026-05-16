#!/usr/bin/env python3
"""WebSocket test to run inside Docker container."""
import asyncio
import json
import sys
import os

# Check if running inside container
if not os.path.exists('/app/tron'):
    print("This script must be run inside the tron-api container")
    print("Run: docker compose exec tron-api python3 /app/test_ws_docker.py <AUDIT_ID>")
    sys.exit(1)

try:
    import websockets
    import httpx
except ImportError:
    print("Installing required packages...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets", "httpx"])
    import websockets
    import httpx

API_KEY = "master-encryption-key-32-chars!!"
PROJECT_ID = "45cd6739-6c2b-41a2-b599-b74ff47ee7b6"


async def create_and_stream():
    # Create audit
    print("Creating audit...")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/api/audits",
            headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
            json={"project_id": PROJECT_ID},
        )
        audit_id = response.json()["id"]
    
    print(f"Audit created: {audit_id}")
    print(f"Connecting to WebSocket...\n")
    
    # Connect to WebSocket
    uri = f"ws://localhost:8000/ws/audits/{audit_id}?token={API_KEY}"
    
    event_count = 0
    async with websockets.connect(uri) as ws:
        print("✓ Connected!\n" + "-" * 70)
        
        while True:
            msg = await ws.recv()
            data = json.loads(msg)
            event_count += 1
            
            event = data.get('event')
            print(f"[{event_count:2d}] {event:20s}", end="")
            
            if event == "snapshot":
                d = data['data']
                print(f" | status={d['status']:10s} progress={d['progress']:3d}%")
            elif event == "progress_update":
                d = data['data']
                print(f" | {d.get('progress', '?'):3}% - {d.get('message', '')}")
            elif event == "finding_discovered":
                f = data['data']
                print(f" | {f.get('severity'):8s} - {f.get('vulnerability_type')}")
            elif event in ("audit_completed", "audit_failed"):
                print(f" | findings={data['data'].get('findings_total', 0)}")
            elif event == "close":
                print(f" | {data['data'].get('reason')}")
                break
            else:
                print()
            
            if event in ("close", "error"):
                break
        
        print("-" * 70)
        print(f"\n✓ Test completed - received {event_count} events")


if __name__ == "__main__":
    asyncio.run(create_and_stream())
