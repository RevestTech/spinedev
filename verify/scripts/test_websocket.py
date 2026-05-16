#!/usr/bin/env python3
"""
WebSocket test for Tron audit progress streaming.
"""
import asyncio
import json
import sys

try:
    import websockets
except ImportError:
    print("Installing websockets...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets"])
    import websockets

API_KEY = "master-encryption-key-32-chars!!"
AUDIT_ID = None  # Will be set from command line arg

async def test_ws():
    if not AUDIT_ID:
        print("Usage: python test_websocket.py <AUDIT_ID>")
        sys.exit(1)
    
    uri = f"ws://localhost:13000/ws/audits/{AUDIT_ID}?token={API_KEY}"
    print(f"Connecting to: {uri}\n")
    
    try:
        async with websockets.connect(uri) as ws:
            print("✓ Connected!\n")
            
            event_count = 0
            while True:
                msg = await ws.recv()
                data = json.loads(msg)
                event_count += 1
                
                event_type = data.get('event')
                print(f"[{event_count:3d}] [{event_type}]", end="")
                
                if event_type == "snapshot":
                    print(f" status={data['data']['status']}, progress={data['data']['progress']}%")
                elif event_type == "progress_update":
                    print(f" progress={data['data'].get('progress', '?')}%")
                elif event_type == "finding_discovered":
                    finding = data['data']
                    print(f" {finding.get('severity', '?')} - {finding.get('title', '?')}")
                elif event_type == "agent_started":
                    print(f" agent={data['data'].get('agent_id', '?')}")
                elif event_type in ("audit_completed", "audit_failed"):
                    print(f" {json.dumps(data.get('data', {}), indent=2)}")
                elif event_type == "close":
                    print(f" reason={data['data'].get('reason', 'unknown')}")
                    print("\n✓ Connection closed normally")
                    break
                elif event_type == "heartbeat":
                    print(" (keepalive)")
                else:
                    print(f" {json.dumps(data.get('data', {}), indent=2)}")
                
                if event_type in ("close", "audit_completed", "audit_failed"):
                    break
                    
    except websockets.exceptions.WebSocketException as e:
        print(f"\n✗ WebSocket error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n✗ Interrupted by user")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        AUDIT_ID = sys.argv[1]
    asyncio.run(test_ws())
