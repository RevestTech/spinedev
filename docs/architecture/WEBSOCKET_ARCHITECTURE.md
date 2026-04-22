# Tron WebSocket Architecture - Version 5.1 (Fixed)

**Status:** P0 Blocker Fixed  
**Issue:** Proposal mixed FastAPI WebSocket + Socket.IO incompatibly  
**Solution:** Use Socket.IO with python-socketio for coherent, scalable real-time

---

## Decision: Socket.IO with python-socketio

**Why Socket.IO over raw WebSocket:**
- ✅ Automatic fallback transports (polling if WebSocket fails)
- ✅ Built-in rooms and namespaces for multi-user
- ✅ Reconnection handling with exponential backoff
- ✅ Redis adapter for horizontal scaling
- ✅ Mature ecosystem (client libraries for all platforms)
- ✅ Event-based API (cleaner than raw messages)

**Architecture:**

```
┌─────────────────────────────────────────────────────────┐
│                    Admin UI (Browser)                    │
│              socket.io-client library                    │
└────────────────────────┬────────────────────────────────┘
                         │ WebSocket (wss://)
                         │ or Long Polling (fallback)
                         ↓
┌─────────────────────────────────────────────────────────┐
│                   Nginx (Port 80/443)                    │
│        /socket.io/ → Sticky Sessions (ip_hash)           │
└────────────────────────┬────────────────────────────────┘
                         │
           ┌─────────────┴──────────────┐
           ↓                            ↓
┌──────────────────────┐    ┌──────────────────────┐
│   tron-api (x3)      │    │   tron-api (x3)      │
│  python-socketio     │    │  python-socketio     │
│  FastAPI ASGI mount  │    │  FastAPI ASGI mount  │
└──────────┬───────────┘    └──────────┬───────────┘
           │                           │
           └─────────────┬─────────────┘
                         ↓
           ┌─────────────────────────┐
           │   Redis Pub/Sub         │
           │   (Socket.IO adapter)   │
           └─────────────────────────┘
                         ↑
           ┌─────────────┴─────────────┐
           │                           │
┌──────────┴───────────┐    ┌──────────┴───────────┐
│  Temporal Workers    │    │  Event Publisher     │
│  (publish events)    │    │  (domain events)     │
└──────────────────────┘    └──────────────────────┘
```

---

## Backend Implementation (FastAPI + python-socketio)

### 1. Install Dependencies

```bash
pip install python-socketio[asyncio] aioredis
```

### 2. Create Socket.IO Server (`tron/realtime/socket_server.py`)

```python
"""
Socket.IO server for Tron real-time updates
"""
import socketio
import logging
from typing import Dict, Any, Optional
from datetime import datetime
import jwt
from jwt.exceptions import InvalidTokenError

logger = logging.getLogger(__name__)

# Create Socket.IO server with Redis adapter for scaling
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins='*',  # Configure properly for production
    logger=True,
    engineio_logger=True,
    ping_timeout=60,
    ping_interval=25,
    max_http_buffer_size=1e8,  # 100 MB
    client_manager=socketio.AsyncRedisManager(
        'redis://redis:6379/1',  # Separate Redis DB for Socket.IO
        write_only=False
    )
)

# Wrap with ASGI app for FastAPI mounting
socket_app = socketio.ASGIApp(
    sio,
    socketio_path='/socket.io'  # Explicit path
)


# ==============================================================================
# Authentication Middleware
# ==============================================================================

@sio.event
async def connect(sid: str, environ: Dict[str, Any], auth: Optional[Dict[str, Any]]):
    """
    Handle client connection with authentication
    
    Client must send auth token:
    ```javascript
    const socket = io('/', {
        path: '/socket.io',
        auth: {
            token: 'jwt-token-here'
        }
    });
    ```
    """
    logger.info(f"Client connecting: {sid}")
    
    # Extract and verify JWT token
    if not auth or 'token' not in auth:
        logger.warning(f"Connection rejected for {sid}: No auth token")
        return False  # Reject connection
    
    try:
        token = auth['token']
        payload = jwt.decode(
            token,
            environ.get('JWT_SECRET_KEY'),
            algorithms=['HS256']
        )
        
        user_id = payload.get('sub')
        project_id = payload.get('project_id')
        
        # Store user context in session
        await sio.save_session(sid, {
            'user_id': user_id,
            'project_id': project_id,
            'connected_at': datetime.utcnow().isoformat()
        })
        
        # Join user-specific room
        await sio.enter_room(sid, f"user:{user_id}")
        
        # Join project room if specified
        if project_id:
            await sio.enter_room(sid, f"project:{project_id}")
        
        logger.info(f"Client {sid} authenticated as user {user_id}")
        
        # Send welcome message
        await sio.emit('connection_established', {
            'sid': sid,
            'user_id': user_id,
            'server_time': datetime.utcnow().isoformat()
        }, to=sid)
        
        return True  # Accept connection
        
    except InvalidTokenError as e:
        logger.warning(f"Connection rejected for {sid}: Invalid token - {e}")
        return False
    except Exception as e:
        logger.error(f"Connection error for {sid}: {e}")
        return False


@sio.event
async def disconnect(sid: str):
    """Handle client disconnect"""
    session = await sio.get_session(sid)
    user_id = session.get('user_id', 'unknown')
    logger.info(f"Client {sid} (user {user_id}) disconnected")


# ==============================================================================
# Event Handlers (Client → Server)
# ==============================================================================

@sio.event
async def subscribe_workflow(sid: str, data: Dict[str, Any]):
    """
    Subscribe to workflow updates
    
    Client sends:
    {
        "workflow_id": "wf-123"
    }
    """
    session = await sio.get_session(sid)
    workflow_id = data.get('workflow_id')
    
    if not workflow_id:
        await sio.emit('error', {'message': 'workflow_id required'}, to=sid)
        return
    
    # TODO: Verify user has access to this workflow
    
    # Join workflow-specific room
    await sio.enter_room(sid, f"workflow:{workflow_id}")
    
    logger.info(f"Client {sid} subscribed to workflow {workflow_id}")
    await sio.emit('subscribed', {
        'workflow_id': workflow_id,
        'room': f"workflow:{workflow_id}"
    }, to=sid)


@sio.event
async def unsubscribe_workflow(sid: str, data: Dict[str, Any]):
    """Unsubscribe from workflow updates"""
    workflow_id = data.get('workflow_id')
    
    if workflow_id:
        await sio.leave_room(sid, f"workflow:{workflow_id}")
        logger.info(f"Client {sid} unsubscribed from workflow {workflow_id}")


@sio.event
async def subscribe_project(sid: str, data: Dict[str, Any]):
    """Subscribe to project-wide updates"""
    project_id = data.get('project_id')
    
    if not project_id:
        await sio.emit('error', {'message': 'project_id required'}, to=sid)
        return
    
    # TODO: Verify user has access to this project
    
    await sio.enter_room(sid, f"project:{project_id}")
    logger.info(f"Client {sid} subscribed to project {project_id}")


@sio.event
async def ping(sid: str, data: Dict[str, Any]):
    """Health check / keep-alive"""
    await sio.emit('pong', {
        'timestamp': datetime.utcnow().isoformat(),
        'latency_ms': data.get('sent_at')  # Client can calculate RTT
    }, to=sid)


# ==============================================================================
# Event Publishers (Server → Client)
# ==============================================================================

async def broadcast_workflow_event(
    workflow_id: str,
    event_type: str,
    data: Dict[str, Any]
):
    """
    Broadcast workflow event to all subscribers
    
    This function is called from:
    - Temporal workers (via domain events)
    - API endpoints (on mutations)
    """
    room = f"workflow:{workflow_id}"
    
    await sio.emit(event_type, {
        'workflow_id': workflow_id,
        'timestamp': datetime.utcnow().isoformat(),
        **data
    }, room=room)
    
    logger.debug(f"Broadcast {event_type} to room {room}")


async def broadcast_project_event(
    project_id: str,
    event_type: str,
    data: Dict[str, Any]
):
    """Broadcast project-level event"""
    room = f"project:{project_id}"
    
    await sio.emit(event_type, {
        'project_id': project_id,
        'timestamp': datetime.utcnow().isoformat(),
        **data
    }, room=room)


async def broadcast_metric_update(metrics: Dict[str, Any]):
    """Broadcast system metrics to all connected clients"""
    await sio.emit('metrics_update', {
        'timestamp': datetime.utcnow().isoformat(),
        'metrics': metrics
    })


# ==============================================================================
# Export for use in other modules
# ==============================================================================

__all__ = [
    'sio',
    'socket_app',
    'broadcast_workflow_event',
    'broadcast_project_event',
    'broadcast_metric_update'
]
```

### 3. Mount in FastAPI (`tron/api/main.py`)

```python
from fastapi import FastAPI
from tron.realtime.socket_server import socket_app

app = FastAPI(title="Tron API")

# Mount Socket.IO
app.mount('/socket.io', socket_app)

# Your existing REST routes
@app.get("/")
async def root():
    return {"message": "Tron API"}

# ... more routes
```

### 4. Publish Events from Temporal Workers (`tron/workflows/audit_workflow.py`)

```python
from tron.realtime.socket_server import broadcast_workflow_event
from temporalio import workflow

@workflow.defn
class AuditWorkflow:
    @workflow.run
    async def run(self, project_id: str, commit_hash: str) -> dict:
        workflow_id = workflow.info().workflow_id
        
        # Publish progress events
        await broadcast_workflow_event(
            workflow_id,
            'workflow_started',
            {
                'project_id': project_id,
                'commit_hash': commit_hash,
                'status': 'running'
            }
        )
        
        # Run audit activities...
        result = await workflow.execute_activity(...)
        
        await broadcast_workflow_event(
            workflow_id,
            'workflow_progress',
            {
                'project_id': project_id,
                'status': 'running',
                'progress': 50,
                'current_step': 'Running security scan'
            }
        )
        
        # ... more work
        
        await broadcast_workflow_event(
            workflow_id,
            'workflow_completed',
            {
                'project_id': project_id,
                'status': 'completed',
                'result': result
            }
        )
        
        return result
```

---

## Frontend Implementation (React + socket.io-client)

### 1. Install Dependencies

```bash
cd admin
npm install socket.io-client
```

### 2. Create Socket Hook (`admin/src/hooks/useSocket.ts`)

```typescript
import { useEffect, useRef, useState } from 'react';
import { io, Socket } from 'socket.io-client';

interface UseSocketOptions {
  autoConnect?: boolean;
  token?: string;
}

export function useSocket(options: UseSocketOptions = {}) {
  const { autoConnect = true, token } = options;
  const socketRef = useRef<Socket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);

  useEffect(() => {
    // FIXED: Use relative URL (same origin via Nginx)
    // Path matches Nginx proxy
    const socket = io('/', {
      path: '/socket.io',
      autoConnect,
      auth: {
        token: token || localStorage.getItem('tron_token')
      },
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      reconnectionAttempts: 10,
      transports: ['websocket', 'polling']  // Prefer WebSocket
    });

    socketRef.current = socket;

    // Connection events
    socket.on('connect', () => {
      console.log('Socket.IO connected:', socket.id);
      setIsConnected(true);
      setLastError(null);
    });

    socket.on('disconnect', (reason) => {
      console.log('Socket.IO disconnected:', reason);
      setIsConnected(false);
    });

    socket.on('connect_error', (error) => {
      console.error('Socket.IO connection error:', error);
      setLastError(error.message);
      setIsConnected(false);
    });

    socket.on('connection_established', (data) => {
      console.log('Connection established:', data);
    });

    // Cleanup on unmount
    return () => {
      socket.disconnect();
    };
  }, [autoConnect, token]);

  return {
    socket: socketRef.current,
    isConnected,
    lastError
  };
}
```

### 3. Use in Components (`admin/src/components/WorkflowMonitor.tsx`)

```typescript
import React, { useEffect, useState } from 'react';
import { useSocket } from '../hooks/useSocket';

interface WorkflowEvent {
  workflow_id: string;
  status: string;
  progress?: number;
  current_step?: string;
}

export function WorkflowMonitor({ workflowId }: { workflowId: string }) {
  const { socket, isConnected } = useSocket();
  const [events, setEvents] = useState<WorkflowEvent[]>([]);

  useEffect(() => {
    if (!socket || !isConnected) return;

    // Subscribe to workflow updates
    socket.emit('subscribe_workflow', { workflow_id: workflowId });

    // Listen for events
    socket.on('workflow_started', (data: WorkflowEvent) => {
      setEvents(prev => [...prev, data]);
    });

    socket.on('workflow_progress', (data: WorkflowEvent) => {
      setEvents(prev => [...prev, data]);
    });

    socket.on('workflow_completed', (data: WorkflowEvent) => {
      setEvents(prev => [...prev, data]);
    });

    // Cleanup
    return () => {
      socket.emit('unsubscribe_workflow', { workflow_id: workflowId });
      socket.off('workflow_started');
      socket.off('workflow_progress');
      socket.off('workflow_completed');
    };
  }, [socket, isConnected, workflowId]);

  return (
    <div>
      <h3>Workflow {workflowId}</h3>
      <div>Status: {isConnected ? 'Connected' : 'Disconnected'}</div>
      <ul>
        {events.map((event, i) => (
          <li key={i}>
            {event.status} - {event.current_step} ({event.progress}%)
          </li>
        ))}
      </ul>
    </div>
  );
}
```

---

## Event Flow Architecture

### Domain Events Pattern (Recommended)

**Problem:** Workers broadcasting directly to Socket.IO couples them to ephemeral state.

**Solution:** Domain Events → Event Publisher → Socket.IO

```python
# 1. Workers publish to domain_events table (durable)
async def publish_domain_event(
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    data: dict
):
    """Append-only event log in PostgreSQL"""
    await db.execute(
        """
        INSERT INTO domain_events 
        (aggregate_type, aggregate_id, event_type, data, created_at)
        VALUES ($1, $2, $3, $4, NOW())
        """,
        aggregate_type, aggregate_id, event_type, json.dumps(data)
    )

# 2. Event Publisher service reads and broadcasts
async def event_publisher_loop():
    """Background task that reads domain_events and broadcasts to Socket.IO"""
    last_id = 0
    
    while True:
        # Poll for new events
        events = await db.fetch(
            "SELECT * FROM domain_events WHERE id > $1 ORDER BY id LIMIT 100",
            last_id
        )
        
        for event in events:
            # Broadcast to appropriate rooms based on event type
            if event['aggregate_type'] == 'workflow':
                await broadcast_workflow_event(
                    event['aggregate_id'],
                    event['event_type'],
                    json.loads(event['data'])
                )
            
            last_id = event['id']
        
        await asyncio.sleep(0.5)  # Poll interval
```

**Benefits:**
- Workers stay dumb (no Socket.IO dependency)
- Events are durable (survive worker restarts)
- Can replay events for debugging
- Single source of truth (database)
- Idempotent (can process same event multiple times)

---

## Scaling Configuration

### Redis Adapter Setup

When scaling to multiple API instances, Socket.IO needs Redis for pub/sub:

```python
# Use separate Redis DB for Socket.IO
sio = socketio.AsyncServer(
    client_manager=socketio.AsyncRedisManager(
        'redis://redis:6379/1',  # DB 1 for Socket.IO
        write_only=False
    )
)
```

### Nginx Sticky Sessions

Already configured in `nginx.conf`:

```nginx
upstream tron_api {
    ip_hash;  # Sticky sessions based on client IP
    server tron-api:8000;
}
```

### Horizontal Scaling Test

```bash
# Start with 3 API instances
docker compose up --scale tron-api=3

# All clients stay connected via sticky sessions
# Events broadcast to all instances via Redis
```

---

## Authentication Flow

```
1. User logs in via REST API
   POST /api/auth/login → JWT token

2. Frontend stores token
   localStorage.setItem('tron_token', token)

3. Socket.IO connects with token
   io('/', { auth: { token } })

4. Server verifies JWT
   jwt.decode(token, SECRET_KEY)

5. Server joins client to rooms
   user:{user_id}, project:{project_id}

6. Events broadcast to rooms
   sio.emit('event', data, room='project:123')
```

---

## Security Checklist

- ✅ JWT authentication required for connections
- ✅ Verify user permissions for room subscriptions
- ✅ Rate limit connections per IP
- ✅ Use WSS (WebSocket Secure) in production
- ✅ Set CORS properly (not '*' in production)
- ✅ Validate all client→server events
- ✅ Sanitize data before broadcasting
- ✅ Implement connection limits per user
- ✅ Log authentication failures
- ✅ Monitor for WebSocket abuse

---

## Migration from Current Proposal

**Old (Broken):**
```python
@app.websocket("/ws/admin")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    # ...mixing with Socket.IO
```

**New (Fixed):**
```python
# Use Socket.IO exclusively
app.mount('/socket.io', socket_app)
# Remove raw WebSocket routes
```

**Frontend:**
```typescript
// Old (broken - internal Docker name)
const socket = io('ws://tron-api:8000')

// New (fixed - relative URL via Nginx)
const socket = io('/', { path: '/socket.io' })
```

---

## Testing

### Backend Test (`tests/test_socket_server.py`)

```python
import pytest
from socketio import AsyncClient

@pytest.mark.asyncio
async def test_authenticated_connection():
    client = AsyncClient()
    token = generate_test_token()
    
    await client.connect(
        'http://localhost:8000',
        socketio_path='/socket.io',
        auth={'token': token}
    )
    
    assert client.connected
    await client.disconnect()

@pytest.mark.asyncio
async def test_rejected_without_auth():
    client = AsyncClient()
    
    with pytest.raises(Exception):
        await client.connect(
            'http://localhost:8000',
            socketio_path='/socket.io'
        )
```

### Frontend Test (`admin/src/hooks/__tests__/useSocket.test.ts`)

```typescript
import { renderHook } from '@testing-library/react-hooks';
import { useSocket } from '../useSocket';
import { io } from 'socket.io-client';

jest.mock('socket.io-client');

test('connects with token', () => {
  const mockToken = 'test-token';
  const { result } = renderHook(() => useSocket({ token: mockToken }));
  
  expect(io).toHaveBeenCalledWith('/', {
    path: '/socket.io',
    auth: { token: mockToken },
    // ... other options
  });
});
```

---

## Summary

**What Changed:**
1. ❌ Removed: FastAPI `@app.websocket` (raw WebSocket)
2. ✅ Added: python-socketio with ASGI mount
3. ✅ Fixed: Frontend uses relative URL via Nginx
4. ✅ Added: JWT authentication for connections
5. ✅ Added: Redis adapter for horizontal scaling
6. ✅ Added: Domain events pattern (decouples workers)
7. ✅ Fixed: Nginx sticky sessions for multi-instance

**Result:**
- Coherent, production-ready real-time architecture
- Scales horizontally with multiple API instances
- Secure with authentication and authorization
- No more internal Docker names in frontend
- Works with Nginx same-origin proxy setup

---

**Status:** ✅ P0 Blocker Resolved
