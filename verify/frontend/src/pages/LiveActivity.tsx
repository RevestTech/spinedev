import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, Radio, AlertCircle } from 'lucide-react'
import Card, { CardBody, CardHeader } from '../components/Card'
import StatusBadge from '../components/StatusBadge'
import { usePolling } from '../hooks/usePolling'
import * as api from '../api'

const MAX_WS = 8

type LiveEvent = {
  auditId: string
  receivedAt: string
  event: string
  detail: string
  raw: unknown
}

function summarizeWsMessage(msg: Record<string, unknown>): { event: string; detail: string } {
  const ev = typeof msg.event === 'string' ? msg.event : 'message'
  const data = msg.data as Record<string, unknown> | undefined
  let detail = ''
  if (data && typeof data === 'object') {
    if (typeof data.message === 'string') detail = data.message
    else if (typeof data.progress === 'number') detail = `${data.progress}%`
    else if (typeof data.status === 'string') detail = `status ${data.status}`
    else if (typeof data.reason === 'string') detail = data.reason
    else if (typeof data.agent === 'string') detail = String(data.agent)
    else detail = JSON.stringify(data).slice(0, 120)
  }
  return { event: ev, detail }
}

export default function LiveActivity() {
  const fetchRuns = useCallback(() => api.listWorkflowRuns({ limit: 80, offset: 0 }), [])
  const { data, error, loading } = usePolling(fetchRuns, 2000, [])

  const rows = data?.items ?? []
  const activeRows = useMemo(
    () => rows.filter(r => r.status === 'running' || r.status === 'queued'),
    [rows],
  )
  const activeKey = useMemo(
    () =>
      activeRows
        .map(r => r.audit_run_id)
        .sort()
        .join(','),
    [activeRows],
  )

  const [events, setEvents] = useState<LiveEvent[]>([])
  const socketsRef = useRef<Map<string, WebSocket>>(new Map())

  useEffect(() => {
    return () => {
      socketsRef.current.forEach(ws => ws.close())
      socketsRef.current.clear()
    }
  }, [])

  useEffect(() => {
    const wantIds = activeKey ? activeKey.split(',').filter(Boolean).slice(0, MAX_WS) : []
    const want = new Set(wantIds)

    for (const [id, ws] of socketsRef.current) {
      if (!want.has(id)) {
        ws.close()
        socketsRef.current.delete(id)
      }
    }

    for (const id of wantIds) {
      if (socketsRef.current.has(id)) continue
      const ws = api.connectAuditWs(id, raw => {
        const msg = raw as Record<string, unknown>
        const { event, detail } = summarizeWsMessage(msg)
        setEvents(prev => [
          ...prev.slice(-400),
          {
            auditId: id,
            receivedAt: new Date().toISOString(),
            event,
            detail,
            raw,
          },
        ])
      })
      ws.onerror = () => {
        setEvents(prev => [
          ...prev.slice(-400),
          {
            auditId: id,
            receivedAt: new Date().toISOString(),
            event: 'ws_error',
            detail: 'WebSocket error',
            raw: null,
          },
        ])
      }
      socketsRef.current.set(id, ws)
    }
  }, [activeKey])

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Activity className="w-7 h-7 text-accent" />
          Live activity
        </h1>
        <p className="text-tron-400 text-sm mt-1">
          Active audits (queued or running) with WebSocket events from the worker, refreshed every 2s. Up to{' '}
          {MAX_WS} concurrent streams. Rows stuck in <span className="text-tron-500">queued</span> with no worker
          progress are marked <span className="text-tron-500">failed</span> on API startup when{' '}
          <span className="font-mono text-tron-500">TRON_RECONCILE_STALE_QUEUED_ON_STARTUP</span> is enabled (see{' '}
          <span className="font-mono text-tron-500">TRON_STALE_QUEUED_AUDIT_MINUTES</span> in compose).
        </p>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-amber-400 text-sm">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error.message}
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Radio className="w-4 h-4 text-green-400" />
              <span className="text-sm font-medium text-white">Active work</span>
              {activeRows.length > 0 && (
                <span className="text-xs text-tron-500">({activeRows.length} audits)</span>
              )}
            </div>
          </CardHeader>
          <CardBody className="p-0">
            {loading && !data ? (
              <div className="px-5 py-10 text-tron-500 text-sm text-center">Loading workflow runs…</div>
            ) : activeRows.length === 0 ? (
              <div className="px-5 py-10 text-tron-500 text-sm text-center">
                No queued or running audits. Start an audit from a{' '}
                <Link to="/projects" className="text-accent-light hover:underline">
                  project
                </Link>{' '}
                or{' '}
                <Link to="/audits" className="text-accent-light hover:underline">
                  audits
                </Link>
                .
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-tron-700 text-tron-400 text-xs">
                      <th className="text-left px-4 py-2 font-medium">Audit</th>
                      <th className="text-left px-4 py-2 font-medium">Project</th>
                      <th className="text-left px-4 py-2 font-medium">Status</th>
                      <th className="text-right px-4 py-2 font-medium">Progress</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activeRows.map(r => (
                      <tr key={r.audit_run_id} className="border-b border-tron-700/40 hover:bg-tron-700/20">
                        <td className="px-4 py-2">
                          <Link
                            to={`/audits/${r.audit_run_id}`}
                            className="font-mono text-xs text-accent-light hover:underline"
                          >
                            {r.audit_run_id.slice(0, 8)}…
                          </Link>
                        </td>
                        <td className="px-4 py-2 text-tron-300 text-xs">
                          <Link to={`/projects/${r.project_id}`} className="hover:text-accent-light hover:underline">
                            {r.project_name || r.project_id.slice(0, 8)}
                          </Link>
                        </td>
                        <td className="px-4 py-2">
                          <StatusBadge status={r.status} />
                        </td>
                        <td className="px-4 py-2 text-right text-tron-300">{r.progress}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <span className="text-sm font-medium text-white">Recent events</span>
          </CardHeader>
          <CardBody className="max-h-[480px] overflow-y-auto font-mono text-xs space-y-1.5 p-4 bg-tron-950/50">
            {events.length === 0 ? (
              <p className="text-tron-500">
                Events appear when WebSocket messages arrive for active audits (progress, agents, completion).
              </p>
            ) : (
              events
                .slice()
                .reverse()
                .map((ev, i) => (
                  <div key={`${ev.receivedAt}-${i}`} className="text-tron-400 border-b border-tron-800/80 pb-1.5">
                    <span className="text-tron-600">{ev.receivedAt.slice(11, 23)}</span>{' '}
                    <span className="text-tron-500">{ev.auditId.slice(0, 8)}</span>{' '}
                    <span className="text-accent-light">{ev.event}</span>
                    {ev.detail ? <span className="text-tron-300"> {ev.detail}</span> : null}
                  </div>
                ))
            )}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <span className="text-sm font-medium text-white">All recent workflow runs</span>
        </CardHeader>
        <CardBody className="p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-tron-700 text-tron-400 text-xs">
                <th className="text-left px-4 py-2 font-medium">Audit</th>
                <th className="text-left px-4 py-2 font-medium">Project</th>
                <th className="text-left px-4 py-2 font-medium">Status</th>
                <th className="text-right px-4 py-2 font-medium">Progress</th>
                <th className="text-left px-4 py-2 font-medium">Started</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 25).map(r => (
                <tr key={r.audit_run_id} className="border-b border-tron-700/30 hover:bg-tron-700/15">
                  <td className="px-4 py-2">
                    <Link
                      to={`/audits/${r.audit_run_id}`}
                      className="font-mono text-xs text-accent-light hover:underline"
                    >
                      {r.audit_run_id.slice(0, 8)}…
                    </Link>
                  </td>
                  <td className="px-4 py-2 text-tron-400 text-xs truncate max-w-[140px]">
                    {r.project_name || '—'}
                  </td>
                  <td className="px-4 py-2">
                    <StatusBadge status={r.status} />
                  </td>
                  <td className="px-4 py-2 text-right text-tron-400">{r.progress}%</td>
                  <td className="px-4 py-2 text-tron-500 text-xs whitespace-nowrap">
                    {new Date(r.started_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && !loading && (
            <div className="px-4 py-8 text-center text-tron-500 text-sm">No workflow runs yet.</div>
          )}
        </CardBody>
      </Card>
    </div>
  )
}
