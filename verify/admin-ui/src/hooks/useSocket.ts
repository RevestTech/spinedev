/**
 * Socket.IO hook for real-time updates.
 *
 * Connects to the Tron Socket.IO server, handles auth,
 * room subscriptions, and reconnection.
 */
import { useEffect, useRef, useState, useCallback } from 'react'
import { io, Socket } from 'socket.io-client'

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error'

interface UseSocketOptions {
  /** JWT token for authentication */
  token: string
  /** Auto-connect on mount (default: true) */
  autoConnect?: boolean
  /** Socket.IO path (default: /socket.io) */
  path?: string
}

interface UseSocketReturn {
  /** Current connection status */
  status: ConnectionStatus
  /** Subscribe to a workflow's real-time updates */
  subscribeWorkflow: (workflowId: string) => void
  /** Unsubscribe from a workflow */
  unsubscribeWorkflow: (workflowId: string) => void
  /** Subscribe to project-wide updates */
  subscribeProject: (projectId: string) => void
  /** Unsubscribe from a project */
  unsubscribeProject: (projectId: string) => void
  /** Register an event listener */
  on: (event: string, callback: (data: unknown) => void) => void
  /** Remove an event listener */
  off: (event: string, callback: (data: unknown) => void) => void
  /** Manually disconnect */
  disconnect: () => void
  /** Manually reconnect */
  reconnect: () => void
}

export function useSocket({ token, autoConnect = true, path = '/socket.io' }: UseSocketOptions): UseSocketReturn {
  const socketRef = useRef<Socket | null>(null)
  const [status, setStatus] = useState<ConnectionStatus>('disconnected')

  // Create socket connection
  useEffect(() => {
    if (!autoConnect || !token) return

    const socket = io('/', {
      path,
      auth: { token },
      transports: ['websocket', 'polling'],
      reconnection: true,
      reconnectionAttempts: 10,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 30000,
    })

    socketRef.current = socket
    setStatus('connecting')

    socket.on('connect', () => {
      setStatus('connected')
    })

    socket.on('disconnect', () => {
      setStatus('disconnected')
    })

    socket.on('connect_error', () => {
      setStatus('error')
    })

    return () => {
      socket.disconnect()
      socketRef.current = null
    }
  }, [token, autoConnect, path])

  const subscribeWorkflow = useCallback((workflowId: string) => {
    socketRef.current?.emit('subscribe_workflow', { workflow_id: workflowId })
  }, [])

  const unsubscribeWorkflow = useCallback((workflowId: string) => {
    socketRef.current?.emit('unsubscribe_workflow', { workflow_id: workflowId })
  }, [])

  const subscribeProject = useCallback((projectId: string) => {
    socketRef.current?.emit('subscribe_project', { project_id: projectId })
  }, [])

  const unsubscribeProject = useCallback((projectId: string) => {
    socketRef.current?.emit('unsubscribe_project', { project_id: projectId })
  }, [])

  const on = useCallback((event: string, callback: (data: unknown) => void) => {
    socketRef.current?.on(event, callback)
  }, [])

  const off = useCallback((event: string, callback: (data: unknown) => void) => {
    socketRef.current?.off(event, callback)
  }, [])

  const disconnect = useCallback(() => {
    socketRef.current?.disconnect()
  }, [])

  const reconnect = useCallback(() => {
    socketRef.current?.connect()
  }, [])

  return {
    status,
    subscribeWorkflow,
    unsubscribeWorkflow,
    subscribeProject,
    unsubscribeProject,
    on,
    off,
    disconnect,
    reconnect,
  }
}
