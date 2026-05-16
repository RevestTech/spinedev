import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Activity, FolderGit2, ScanSearch, Bug, AlertTriangle,
  CheckCircle2, XCircle, Server, ChevronRight, Shield,
} from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import Card, { CardHeader, CardBody } from '../components/Card'
import StatusBadge from '../components/StatusBadge'
import SeverityBadge from '../components/SeverityBadge'
import { usePolling } from '../hooks/usePolling'
import * as api from '../api'

function StatCard({ icon: Icon, label, value, color }: { icon: any; label: string; value: string | number; color: string }) {
  return (
    <Card>
      <CardBody className="flex items-center gap-4">
        <div className={`w-10 h-10 rounded-lg ${color} flex items-center justify-center shrink-0`}>
          <Icon className="w-5 h-5 text-white" />
        </div>
        <div>
          <div className="text-2xl font-bold text-white">{value}</div>
          <div className="text-xs text-tron-400 mt-0.5">{label}</div>
        </div>
      </CardBody>
    </Card>
  )
}

export default function Overview() {
  const { data: projects } = usePolling(() => api.listProjects(1, 50), 10000, [])
  const { data: audits } = usePolling(() => api.listAudits({ page_size: 50 }), 5000, [])
  const { data: health } = usePolling(() => api.getHealth(), 10000, [])
  const { data: ready } = usePolling(() => api.getReady(), 10000, [])

  const projectList = projects?.items ?? []
  const totalProjects = projects?.total ?? 0
  const auditItems = audits?.items ?? []
  const totalAudits = audits?.total ?? 0
  const runningAudits = auditItems.filter(a => a.status === 'running').length
  const queuedAudits = auditItems.filter(a => a.status === 'queued').length
  const totalFindings = auditItems.reduce((s, a) => s + (a.findings_total || 0), 0)
  const criticalFindings = auditItems.reduce((s, a) => s + (a.findings_critical || 0), 0)

  // Build project name lookup
  const projectNames: Record<string, string> = {}
  for (const p of projectList) {
    projectNames[p.id] = p.name
  }

  const recentAudits = [...auditItems]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 8)

  // Severity distribution for chart
  const sevData = [
    { name: 'Critical', value: auditItems.reduce((s, a) => s + (a.findings_critical || 0), 0), fill: '#ef4444' },
    { name: 'High', value: auditItems.reduce((s, a) => s + (a.findings_high || 0), 0), fill: '#f97316' },
    { name: 'Medium', value: auditItems.reduce((s, a) => s + (a.findings_medium || 0), 0), fill: '#eab308' },
    { name: 'Low', value: auditItems.reduce((s, a) => s + (a.findings_low || 0), 0), fill: '#22c55e' },
  ]

  const uptimeHours = health ? Math.floor(health.uptime_seconds / 3600) : 0
  const uptimeMins = health ? Math.floor((health.uptime_seconds % 3600) / 60) : 0

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Dashboard</h1>
        <p className="text-tron-400 text-sm mt-1">Real-time overview of your Tron security platform</p>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard icon={FolderGit2} label="Projects" value={totalProjects} color="bg-accent" />
        <StatCard icon={ScanSearch} label="Total Audits" value={totalAudits} color="bg-blue-600" />
        <StatCard icon={Bug} label="Total Findings" value={totalFindings} color="bg-orange-600" />
        <StatCard icon={AlertTriangle} label="Critical" value={criticalFindings} color="bg-red-600" />
      </div>

      {/* System Health + Severity Chart */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Health */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Server className="w-4 h-4 text-tron-400" />
              <span className="text-sm font-medium text-white">System Health</span>
            </div>
          </CardHeader>
          <CardBody className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-tron-300">API Status</span>
              <span className={`text-sm font-medium ${health?.status === 'ok' ? 'text-green-400' : 'text-red-400'}`}>
                {health?.status === 'ok' ? 'Healthy' : 'Unknown'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-tron-300">Uptime</span>
              <span className="text-sm font-medium text-white">{uptimeHours}h {uptimeMins}m</span>
            </div>
            {ready?.checks && Object.entries(ready.checks).map(([name, status]) => (
              <div key={name} className="flex items-center justify-between">
                <span className="text-sm text-tron-300 capitalize">{name}</span>
                <div className="flex items-center gap-1.5">
                  {status === 'ok' ? (
                    <CheckCircle2 className="w-3.5 h-3.5 text-green-400" />
                  ) : (
                    <XCircle className="w-3.5 h-3.5 text-red-400" />
                  )}
                  <span className={`text-sm ${status === 'ok' ? 'text-green-400' : 'text-red-400'}`}>
                    {status === 'ok' ? 'Connected' : status}
                  </span>
                </div>
              </div>
            ))}
            {(runningAudits > 0 || queuedAudits > 0) && (
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <span className="text-sm text-tron-300">
                  Active audits:{' '}
                  <span className="text-white font-medium">{runningAudits}</span> running,{' '}
                  <span className="text-white font-medium">{queuedAudits}</span> queued
                </span>
                <Link
                  to="/live"
                  className="text-sm font-medium text-accent-light hover:text-accent flex items-center gap-1"
                >
                  <Activity className="w-3.5 h-3.5" />
                  Live view
                </Link>
              </div>
            )}
          </CardBody>
        </Card>

        {/* Severity Chart */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Bug className="w-4 h-4 text-tron-400" />
              <span className="text-sm font-medium text-white">Findings by Severity</span>
            </div>
          </CardHeader>
          <CardBody>
            {totalFindings > 0 ? (
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={sevData}>
                  <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 12 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: '#94a3b8', fontSize: 12 }} axisLine={false} tickLine={false} />
                  <Tooltip
                    contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#e2e8f0' }}
                  />
                  <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                    {sevData.map((entry, i) => (
                      <Cell key={i} fill={entry.fill} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[180px] flex items-center justify-center text-tron-500 text-sm">
                No findings yet. Run an audit to see results.
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      {/* Cybersecurity & Threat Monitoring */}
      <Card className="border-accent/30 bg-accent/5">
        <CardHeader>
          <div className="flex items-center gap-2">
            <Shield className="w-4 h-4 text-accent-light" />
            <span className="text-sm font-medium text-white">Cybersecurity & Threat Monitoring</span>
          </div>
        </CardHeader>
        <CardBody className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-6">
            <div className="flex flex-col">
              <span className="text-xs text-tron-400">Live Threat Feed</span>
              <div className="flex items-center gap-1.5 mt-1">
                <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
                <span className="text-sm font-medium text-green-400 uppercase tracking-wider">Active (OSV.dev)</span>
              </div>
            </div>
            <div className="flex flex-col">
              <span className="text-xs text-tron-400">Deep Dependency Scan</span>
              <div className="flex items-center gap-1.5 mt-1 text-white text-sm font-medium">
                <CheckCircle2 className="w-3.5 h-3.5 text-accent-light" />
                Recursive Resolution
              </div>
            </div>
            <div className="flex flex-col border-l border-tron-700 pl-6">
              <span className="text-xs text-tron-400">Backdoor Protection</span>
              <div className="flex items-center gap-1.5 mt-1 text-white text-sm font-medium">
                <Shield className="w-3.5 h-3.5 text-accent-light" />
                Hack-Proof Logic
              </div>
            </div>
          </div>
          <div className="text-xs text-tron-400 max-w-sm text-right">
            Tron proactively monitors for malicious backdoors and supply-chain threats by resolving deep dependencies in real-time.
          </div>
        </CardBody>
      </Card>

      {/* Recent Audits */}
      <Card>
        <CardHeader className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-tron-400" />
            <span className="text-sm font-medium text-white">Recent Audits</span>
          </div>
          <Link to="/audits" className="text-xs text-accent-light hover:text-accent">View all</Link>
        </CardHeader>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-tron-700 text-tron-400 text-xs">
                <th className="text-left px-5 py-3 font-medium">Project</th>
                <th className="text-left px-5 py-3 font-medium">Status</th>
                <th className="text-left px-5 py-3 font-medium">Progress</th>
                <th className="text-right px-5 py-3 font-medium">Findings</th>
                <th className="text-right px-5 py-3 font-medium">Critical</th>
                <th className="text-right px-5 py-3 font-medium">High</th>
                <th className="text-right px-5 py-3 font-medium">Started</th>
                <th className="w-8"></th>
              </tr>
            </thead>
            <tbody>
              {recentAudits.map(a => (
                <tr key={a.id} className="border-b border-tron-700/50 hover:bg-tron-700/30 transition-colors group">
                  <td className="px-5 py-3">
                    <div>
                      <Link to={`/audits/${a.id}`} className="text-white hover:text-accent-light font-medium text-sm transition-colors">
                        {projectNames[a.project_id] || 'Unknown Project'}
                      </Link>
                      <div className="text-tron-500 font-mono text-xs mt-0.5">{a.id.slice(0, 12)}</div>
                    </div>
                  </td>
                  <td className="px-5 py-3"><StatusBadge status={a.status} /></td>
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-2">
                      <div className="w-20 h-1.5 bg-tron-700 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all duration-500 ${
                            a.status === 'failed' ? 'bg-red-500' : a.findings_total === 0 && a.status === 'completed' ? 'bg-green-500' : 'bg-accent'
                          }`}
                          style={{ width: `${a.progress}%` }}
                        />
                      </div>
                      <span className="text-xs text-tron-400">{a.progress}%</span>
                    </div>
                  </td>
                  <td className="px-5 py-3 text-right">
                    {a.findings_total === 0 && a.status === 'completed' ? (
                      <span className="text-green-400 font-medium">Clean</span>
                    ) : (
                      <span className="text-white font-medium">{a.findings_total}</span>
                    )}
                  </td>
                  <td className="px-5 py-3 text-right">
                    {a.findings_critical > 0 ? (
                      <span className="text-severity-critical font-medium">{a.findings_critical}</span>
                    ) : (
                      <span className="text-tron-500">0</span>
                    )}
                  </td>
                  <td className="px-5 py-3 text-right">
                    {a.findings_high > 0 ? (
                      <span className="text-severity-high font-medium">{a.findings_high}</span>
                    ) : (
                      <span className="text-tron-500">0</span>
                    )}
                  </td>
                  <td className="px-5 py-3 text-right text-tron-400 text-xs whitespace-nowrap">
                    {new Date(a.created_at).toLocaleString()}
                  </td>
                  <td className="px-5 py-3 text-right">
                    <Link to={`/audits/${a.id}`} className="text-tron-600 group-hover:text-accent-light transition-colors">
                      <ChevronRight className="w-4 h-4" />
                    </Link>
                  </td>
                </tr>
              ))}
              {recentAudits.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-5 py-8 text-center text-tron-500">
                    No audits yet. Create a project and start scanning.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}
