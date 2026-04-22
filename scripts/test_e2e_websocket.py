#!/usr/bin/env python3
"""
End-to-end WebSocket test: Create audit and stream events.
"""
import asyncio
import json
import sys
import httpx

try:
    import websockets
except ImportError:
    print("Installing websockets...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets"])
    import websockets

API_KEY = "master-encryption-key-32-chars!!"
PROJECT_ID = "45cd6739-6c2b-41a2-b599-b74ff47ee7b6"
API_BASE = "http://localhost:13000"


async def create_audit():
    """Create a new audit via POST."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{API_BASE}/api/audits",
            headers={
                "X-API-Key": API_KEY,
                "Content-Type": "application/json",
            },
            json={"project_id": PROJECT_ID},
        )
        response.raise_for_status()
        return response.json()["id"]


async def stream_audit_events(audit_id: str):
    """Connect to WebSocket and stream events."""
    uri = f"ws://localhost:13000/ws/audits/{audit_id}?token={API_KEY}"
    print(f"Connecting to WebSocket: {uri}\n")
    
    event_count = 0
    try:
        async with websockets.connect(uri) as ws:
            print("✓ Connected!\n")
            print("-" * 80)
            
            while True:
                msg = await ws.recv()
                data = json.loads(msg)
                event_count += 1
                
                event_type = data.get('event')
                timestamp = data.get('timestamp', '')
                
                print(f"[{event_count:3d}] {timestamp[:19]} | {event_type:20s}", end="")
                
                if event_type == "snapshot":
                    d = data['data']
                    print(f"| status={d['status']:10s} progress={d['progress']:3d}%")
                elif event_type == "progress_update":
                    d = data['data']
                    print(f"| progress={d.get('progress', '?'):3}% - {d.get('message', '')}")
                elif event_type == "finding_discovered":
                    f = data['data']
                    print(f"| {f.get('severity', '?'):8s} - {f.get('vulnerability_type', '?')}")
                elif event_type == "agent_started":
                    print(f"| agent={data['data'].get('agent_id', '?')}")
                elif event_type in ("audit_completed", "audit_failed"):
                    d = data['data']
                    print(f"| findings={d.get('findings_total', 0)}")
                elif event_type == "close":
                    print(f"| reason={data['data'].get('reason', 'unknown')}")
                elif event_type == "heartbeat":
                    print("| (keepalive)")
                else:
                    print(f"| {data.get('data', {})}")
                
                if event_type in ("close", "error"):
                    break
                    
            print("-" * 80)
            print(f"\n✓ Received {event_count} events")
            
    except Exception as e:
        print(f"\n✗ WebSocket error: {e}")
        raise


async def main():
    print("=" * 80)
    print("Tron End-to-End WebSocket Test")
    print("=" * 80)
    print()
    
    # Step 1: Create audit
    print("Step 1: Creating new audit...")
    audit_id = await create_audit()
    print(f"✓ Audit created: {audit_id}\n")
    
    # Step 2: Stream events (with small delay to ensure audit starts)
    print("Step 2: Connecting to WebSocket and streaming events...")
    await asyncio.sleep(0.5)
    await stream_audit_events(audit_id)
    
    print("\n" + "=" * 80)
    print("Test completed successfully!")
    print("=" * 80)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n✗ Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
