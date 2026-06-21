#!/usr/bin/env python3
"""
Tron Audit Monitor - Real-time WebSocket monitoring

Usage:
    scripts/monitor_audit.py <audit_id> <api_key>

Example:
    scripts/monitor_audit.py a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d sk-ant-...
"""

import asyncio
import websockets
import json
import sys
from datetime import datetime

# Color codes for terminal
class Colors:
    BLUE = '\033[0;34m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    RED = '\033[0;31m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'  # No Color

async def monitor_audit(audit_id: str, api_key: str):
    """Monitor audit progress via WebSocket connection."""
    uri = f"ws://localhost:13000/ws/audits/{audit_id}?token={api_key}"
    
    print(f"{Colors.BLUE}╔════════════════════════════════════════════════════════╗{Colors.NC}")
    print(f"{Colors.BLUE}║       Tron Audit Monitor - Real-time Stream          ║{Colors.NC}")
    print(f"{Colors.BLUE}╚════════════════════════════════════════════════════════╝{Colors.NC}")
    print()
    print(f"📡 Connecting to audit: {Colors.CYAN}{audit_id}{Colors.NC}")
    print(f"⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    try:
        async with websockets.connect(uri) as ws:
            print(f"{Colors.GREEN}✅ Connected! Listening for events...{Colors.NC}")
            print()
            
            findings_count = 0
            agents_started = []
            
            while True:
                try:
                    message = await ws.recv()
                    data = json.loads(message)
                    event = data.get('event')
                    payload = data.get('data', {})
                    timestamp = datetime.now().strftime('%H:%M:%S')
                    
                    if event == 'snapshot':
                        status = payload.get('status', 'unknown')
                        progress = payload.get('progress', 0)
                        findings = payload.get('findings_total', 0)
                        print(f"[{timestamp}] 📸 Initial Snapshot")
                        print(f"           Status: {status.upper()}")
                        print(f"           Progress: {progress}%")
                        print(f"           Findings: {findings}")
                        print()
                        
                    elif event == 'progress_update':
                        progress = payload.get('progress', 0)
                        stage = payload.get('stage', '')
                        print(f"[{timestamp}] ⏳ Progress: {progress}%", end='')
                        if stage:
                            print(f" ({stage})", end='')
                        print()
                        
                    elif event == 'agent_started':
                        agent = payload.get('agent_id', 'unknown')
                        agents_started.append(agent)
                        print(f"[{timestamp}] {Colors.BLUE}🤖 Agent Started: {agent}{Colors.NC}")
                        
                    elif event == 'finding_discovered':
                        findings_count += 1
                        severity = payload.get('severity', 'unknown').upper()
                        title = payload.get('title', 'Unknown')
                        file_path = payload.get('file_path', '')
                        category = payload.get('category', '')
                        
                        # Color code severity
                        if severity == 'CRITICAL':
                            severity_color = Colors.RED
                        elif severity == 'HIGH':
                            severity_color = Colors.YELLOW
                        elif severity == 'MEDIUM':
                            severity_color = Colors.CYAN
                        else:
                            severity_color = Colors.GREEN
                        
                        print(f"[{timestamp}] 🔍 Finding #{findings_count}")
                        print(f"           {severity_color}[{severity}]{Colors.NC} {title}")
                        print(f"           File: {file_path}")
                        if category:
                            print(f"           Category: {category}")
                        print()
                        
                    elif event == 'audit_completed':
                        total = payload.get('findings_total', 0)
                        critical = payload.get('findings_critical', 0)
                        high = payload.get('findings_high', 0)
                        medium = payload.get('findings_medium', 0)
                        low = payload.get('findings_low', 0)
                        
                        print()
                        print(f"{Colors.GREEN}╔════════════════════════════════════════════════════════╗{Colors.NC}")
                        print(f"{Colors.GREEN}║              Audit Completed Successfully             ║{Colors.NC}")
                        print(f"{Colors.GREEN}╚════════════════════════════════════════════════════════╝{Colors.NC}")
                        print()
                        print(f"⏰ Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                        print()
                        print("Summary:")
                        print(f"  Agents Executed: {len(agents_started)}")
                        for agent in agents_started:
                            print(f"    • {agent}")
                        print()
                        print("Findings by Severity:")
                        print(f"  🔴 Critical: {Colors.RED}{critical}{Colors.NC}")
                        print(f"  🟠 High:     {Colors.YELLOW}{high}{Colors.NC}")
                        print(f"  🟡 Medium:   {medium}")
                        print(f"  🟢 Low:      {low}")
                        print("  ═══════════")
                        print(f"  📊 Total:    {Colors.GREEN}{total}{Colors.NC}")
                        print()
                        break
                        
                    elif event == 'audit_failed':
                        error = payload.get('error_message', 'Unknown error')
                        print()
                        print(f"{Colors.RED}╔════════════════════════════════════════════════════════╗{Colors.NC}")
                        print(f"{Colors.RED}║                  Audit Failed                         ║{Colors.NC}")
                        print(f"{Colors.RED}╚════════════════════════════════════════════════════════╝{Colors.NC}")
                        print()
                        print(f"❌ Error: {error}")
                        print()
                        break
                        
                    elif event == 'close':
                        print()
                        print(f"{Colors.YELLOW}👋 Connection closed by server{Colors.NC}")
                        break
                        
                except websockets.ConnectionClosed:
                    print()
                    print(f"{Colors.YELLOW}⚠️  Connection closed unexpectedly{Colors.NC}")
                    break
                except json.JSONDecodeError as e:
                    print(f"{Colors.RED}❌ Failed to parse message: {e}{Colors.NC}")
                    continue
                    
    except websockets.exceptions.InvalidStatusCode as e:
        print(f"{Colors.RED}❌ Connection failed: {e}{Colors.NC}")
        print()
        print("Possible causes:")
        print("  • Audit ID is invalid")
        print("  • API key is incorrect")
        print("  • Tron API is not running")
        print()
        sys.exit(1)
    except Exception as e:
        print(f"{Colors.RED}❌ Unexpected error: {e}{Colors.NC}")
        sys.exit(1)

def main():
    """Main entry point."""
    if len(sys.argv) != 3:
        print("Tron Audit Monitor - Real-time WebSocket monitoring")
        print()
        print("Usage:")
        print(f"  {sys.argv[0]} <audit_id> <api_key>")
        print()
        print("Example:")
        print(f"  {sys.argv[0]} a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d sk-ant-...")
        print()
        print("To get API key:")
        print("  export API_KEY=$(curl -s -H \"Authorization: Bearer $(cat ~/.config/kmac/docker-vault-token)\" \\")
        print("    http://127.0.0.1:9999/get/tron:auth_master_key | jq -r '.value')")
        print()
        sys.exit(1)
    
    audit_id = sys.argv[1]
    api_key = sys.argv[2]
    
    try:
        asyncio.run(monitor_audit(audit_id, api_key))
    except KeyboardInterrupt:
        print()
        print(f"{Colors.YELLOW}⚠️  Monitoring interrupted by user{Colors.NC}")
        sys.exit(0)

if __name__ == "__main__":
    main()
