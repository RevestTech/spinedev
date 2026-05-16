import { useEffect, useRef, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  ArrowLeft, Clock, AlertTriangle, Bug, FileCode, Wifi, Shield, ChevronDown, ChevronUp,
} from 'lucide-react'
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer,
} from 'recharts'
import Card, { CardHeader, CardBody } from '../components/Card'
import StatusBadge from '../components/StatusBadge'
import SeverityBadge from '../components/SeverityBadge'
import { usePolling } from '../hooks/usePolling'
import * as api from '../api'

const SEV_COLORS: Record<string, string> = {
  critical: '#ef4444',
  high: '#f97316',
  medium: '#eab308',
  low: '#22c55e',
}

export default function AuditDetail() {
  const { id } = useParams<{ id: string }>()
  const { data: audit } = usePolling(() => api.getAudit(id!), 3000, [id])
  const { data: project } = usePolling(
    () => audit?.project_id ? api.getProject(audit.project_id) : Promise.resolve(null),
    30000,
    [audit?.project_id],
  )
  const [findings, setFindings] = useState<api.Finding[]>([])
  const [wsEvents, setWsEvents] = useState<any[]>([])
  const [wsConnected, setWsConnected] = useState(false)
  const [showErrorStack, setShowErrorStack] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)

  // Load findings when audit completes
  useEffect(() => {
    if (!audit || !id) return
    if (audit.findings_total > 0) {
      api.listFindings(id, { page_size: 50 }).then(r => setFindings(r.items))
    }
  }, [id, audit?.findings_total])

  // WebSocket for live updates (queued + running — server sends snapshot then Redis stream)
  useEffect(() => {
    if (!id || !audit || (audit.status !== 'running' && audit.status !== 'queued')) return
    const ws = api.connectAuditWs(id, (msg) => {
      setWsEvents(prev => [...prev.slice(-50), msg])
    })
    ws.onopen = () => setWsConnected(true)
    ws.onclose = () => setWsConnected(false)
    wsRef.current = ws
    return () => ws.close()
  }, [id, audit?.status])

  if (!audit) {
    return (
      <div className="p-6 flex items-center justify-center h-64 text-tron-500">
        Loading audit...
      </div>
    )
  }

  const duration = audit.completed_at
    ? ((new Date(audit.completed_at).getTime() - new Date(audit.started_at).getTime()) / 1000).toFixed(1)
    : null

  const pieData = [
    { name: 'Critical', value: audit.findings_critical, color: SEV_COLORS.critical },
    { name: 'High', value: audit.findings_high, color: SEV_COLORS.high },
    { name: 'Medium', value: audit.findings_medium, color: SEV_COLORS.medium },
    { name: 'Low', value: audit.findings_low, color: SEV_COLORS.low },
  ].filter(d => d.value > 0)

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link to="/audits" className="p-2 rounded-lg hover:bg-tron-700 text-tron-400 hover:text-white transition-colors">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold text-white font-mono">{audit.id.slice(0, 12)}...</h1>
            <StatusBadge status={audit.status} />
            {wsConnected && (
              <span className="flex items-center gap-1 text-xs text-green-400">
                <Wifi className="w-3 h-3" /> Live
              </span>
            )}
          </div>
          <p className="text-tron-400 text-sm mt-1">
            {project?.name || audit.project_id.slice(0, 8)}
            {duration && <> &middot; {duration}s</>}
          </p>
        </div>
        {audit.findings_total > 0 && (
          <Link
            to={`/audits/${audit.id}/findings`}
            className="flex items-center gap-2 px-4 py-2 bg-accent hover:bg-accent-dark text-white rounded-lg text-sm font-medium transition-colors"
          >
            <Bug className="w-4 h-4" /> View All Findings
          </Link>
        )}
      </div>

      {/* Progress bar (running) */}
      {audit.status === 'running' && (
        <Card>
          <CardBody>
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm text-tron-300">Audit in progress</span>
              <span className="text-sm font-medium text-accent-light">{audit.progress}%</span>
            </div>
            <div className="w-full h-2 bg-tron-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-accent rounded-full transition-all duration-1000"
                style={{ width: `${audit.progress}%` }}
              />
            </div>
          </CardBody>
        </Card>
      )}

      {/* Threat Intel Alerts */}
      {audit.threat_intel_alerts_json && audit.threat_intel_alerts_json.length > 0 && (
        <Card className="border-red-500/50 bg-red-500/5">
          <CardHeader className="flex items-center gap-2">
            <Shield className="w-5 h-5 text-red-500" />
            <span className="text-sm font-bold text-red-400">CRITICAL THREAT INTELLIGENCE ALERTS</span>
          </CardHeader>
          <CardBody className="space-y-2">
            {audit.threat_intel_alerts_json.map((alert, idx) => (
              <div key={idx} className="flex items-start gap-3 p-3 bg-red-500/10 rounded-lg border border-red-500/20">
                <AlertTriangle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
                <span className="text-sm text-red-200 font-medium">{alert}</span>
              </div>
            ))}
            <div className="mt-2 text-xs text-tron-400 italic">
              These alerts were generated by cross-referencing your dependencies with live backdoor and supply-chain threat databases.
            </div>
          </CardBody>
        </Card>
      )}

      {/* Error */}
      {audit.error_message && (
        <Card className="border-red-500/30">
          <CardBody className="space-y-4">
            <div className="flex items-start gap-3">
              <AlertTriangle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
              <div className="flex-1">
                <div className="text-sm font-medium text-red-400">Audit Failed</div>
                <div className="text-sm text-tron-300 mt-1 font-mono break-all">{audit.error_message}</div>
              </div>
              {audit.error_stack && (
                <button
                  onClick={() => setShowErrorStack(!showErrorStack)}
                  className="flex items-center gap-1 text-xs text-tron-500 hover:text-tron-300 transition-colors"
                >
                  {showErrorStack ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                  {showErrorStack ? 'Hide Stack' : 'Show Details'}
                </button>
              )}
            </div>
            
            {showErrorStack && audit.error_stack && (
              <div className="p-4 bg-black/40 rounded-lg border border-tron-800 overflow-x-auto">
                <pre className="text-[11px] font-mono text-tron-400 leading-relaxed">
                  {audit.error_stack}
                </pre>
              </div>
            )}
          </CardBody>
        </Card>
      )}

      {/* Stats + Pie */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <span className="text-sm font-medium text-white">Summary</span>
          </CardHeader>
          <CardBody className="space-y-3">
            <div className="grid grid-cols-2 gap-4">
              {[
                { label: 'Total Findings', value: audit.findings_total, color: 'text-white' },
                { label: 'Critical', value: audit.findings_critical, color: 'text-severity-critical' },
                { label: 'High', value: audit.findings_high, color: 'text-severity-high' },
                { label: 'Medium', value: audit.findings_medium, color: 'text-severity-medium' },
                { label: 'Low', value: audit.findings_low, color: 'text-severity-low' },
                { label: 'Progress', value: `${audit.progress}%`, color: 'text-accent-light' },
              ].map(s => (
                <div key={s.label}>
                  <div className="text-xs text-tron-400">{s.label}</div>
                  <div className={`text-xl font-bold ${s.color}`}>{s.value}</div>
                </div>
              ))}
            </div>
            <div className="pt-3 border-t border-tron-700 space-y-2 text-xs text-tron-400">
              <div className="flex justify-between">
                <span>Started</span>
                <span className="text-tron-300">{new Date(audit.started_at).toLocaleString()}</span>
              </div>
              {audit.completed_at && (
                <div className="flex justify-between">
                  <span>Completed</span>
                  <span className="text-tron-300">{new Date(audit.completed_at).toLocaleString()}</span>
                </div>
              )}
            </div>
          </CardBody>
        </Card>

        {pieData.length > 0 && (
          <Card>
            <CardHeader>
              <span className="text-sm font-medium text-white">Severity Distribution</span>
            </CardHeader>
            <CardBody>
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} innerRadius={40}>
                    {pieData.map((d, i) => (
                      <Cell key={i} fill={d.color} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#e2e8f0' }}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="flex justify-center gap-4 mt-2">
                {pieData.map(d => (
                  <div key={d.name} className="flex items-center gap-1.5 text-xs">
                    <div className="w-2.5 h-2.5 rounded-full" style={{ background: d.color }} />
                    <span className="text-tron-300">{d.name}: {d.value}</span>
                  </div>
                ))}
              </div>
            </CardBody>
          </Card>
        )}
      </div>

      {/* Top findings preview */}
      {findings.length > 0 && (
        <Card>
          <CardHeader className="flex items-center justify-between">
            <span className="text-sm font-medium text-white">Top Findings</span>
            <Link to={`/audits/${audit.id}/findings`} className="text-xs text-accent-light hover:text-accent">
              View all {audit.findings_total}
            </Link>
          </CardHeader>
          <div className="divide-y divide-tron-700/50">
            {findings.slice(0, 10).map(f => (
              <div key={f.id} className="px-5 py-3 hover:bg-tron-700/20">
                <div className="flex items-center gap-3">
                  <SeverityBadge severity={f.severity} />
                  <span className="text-sm text-white font-medium flex-1 truncate">{f.title}</span>
                </div>
                <div className="flex items-center gap-3 mt-1 text-xs text-tron-400">
                  <span className="flex items-center gap-1">
                    <FileCode className="w-3 h-3" />
                    {f.file_path}{f.line_start ? `:${f.line_start}` : ''}
                  </span>
                  {f.category && <span className="text-tron-500">{f.category}</span>}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Live events */}
      {wsEvents.length > 0 && (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Wifi className="w-4 h-4 text-green-400" />
              <span className="text-sm font-medium text-white">Live Events</span>
            </div>
          </CardHeader>
          <CardBody className="max-h-48 overflow-y-auto font-mono text-xs space-y-1">
            {wsEvents.slice().reverse().map((ev, i) => (
              <div key={i} className="text-tron-400">
                <span className="text-tron-500">{ev.timestamp?.slice(11, 19) || ''}</span>{' '}
                <span className="text-accent-light">{ev.event}</span>{' '}
                {ev.data?.message || ev.data?.progress ? (
                  <span className="text-tron-300">{ev.data.message || `${ev.data.progress}%`}</span>
                ) : null}
              </div>
            ))}
          </CardBody>
        </Card>
      )}
    </div>
  )
}
