import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ScanSearch, Filter } from 'lucide-react'
import Card, { CardHeader } from '../components/Card'
import StatusBadge from '../components/StatusBadge'
import { usePolling } from '../hooks/usePolling'
import * as api from '../api'

const STATUS_FILTERS = ['all', 'running', 'completed', 'failed', 'queued'] as const

export default function Audits() {
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const { data: projects } = usePolling(() => api.listProjects(1, 200), 30000, [])
  const { data } = usePolling(
    () => api.listAudits({
      status: statusFilter === 'all' ? undefined : statusFilter,
      page_size: 100,
    }),
    3000,
    [statusFilter],
  )

  const audits = data?.items ?? []
  const projectMap = new Map((projects?.items ?? []).map(p => [p.id, p.name]))

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Audit Runs</h1>
          <p className="text-tron-400 text-sm mt-1">{data?.total ?? 0} total audit{(data?.total ?? 0) !== 1 ? 's' : ''}</p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2">
        <Filter className="w-4 h-4 text-tron-400" />
        {STATUS_FILTERS.map(s => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors capitalize ${
              statusFilter === s
                ? 'bg-accent text-white'
                : 'bg-tron-800 text-tron-400 hover:bg-tron-700 hover:text-white border border-tron-700'
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      {/* Table */}
      <Card>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-tron-700 text-tron-400 text-xs">
                <th className="text-left px-5 py-3 font-medium">Audit</th>
                <th className="text-left px-5 py-3 font-medium">Project</th>
                <th className="text-left px-5 py-3 font-medium">Status</th>
                <th className="text-left px-5 py-3 font-medium">Progress</th>
                <th className="text-right px-5 py-3 font-medium">Critical</th>
                <th className="text-right px-5 py-3 font-medium">High</th>
                <th className="text-right px-5 py-3 font-medium">Medium</th>
                <th className="text-right px-5 py-3 font-medium">Low</th>
                <th className="text-right px-5 py-3 font-medium">Total</th>
                <th className="text-right px-5 py-3 font-medium">Started</th>
              </tr>
            </thead>
            <tbody>
              {audits.map(a => (
                <tr key={a.id} className="border-b border-tron-700/50 hover:bg-tron-700/30 transition-colors">
                  <td className="px-5 py-3">
                    <Link to={`/audits/${a.id}`} className="text-accent-light hover:underline font-mono text-xs">
                      {a.id.slice(0, 8)}
                    </Link>
                  </td>
                  <td className="px-5 py-3 text-tron-300 text-xs">
                    {projectMap.get(a.project_id) || a.project_id.slice(0, 8)}
                  </td>
                  <td className="px-5 py-3"><StatusBadge status={a.status} /></td>
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-2">
                      <div className="w-24 h-1.5 bg-tron-700 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all duration-500 ${
                            a.status === 'failed' ? 'bg-red-500' : 'bg-accent'
                          }`}
                          style={{ width: `${a.progress}%` }}
                        />
                      </div>
                      <span className="text-xs text-tron-400 w-8">{a.progress}%</span>
                    </div>
                  </td>
                  <td className="px-5 py-3 text-right">
                    <span className={a.findings_critical > 0 ? 'text-severity-critical font-medium' : 'text-tron-500'}>
                      {a.findings_critical}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-right">
                    <span className={a.findings_high > 0 ? 'text-severity-high font-medium' : 'text-tron-500'}>
                      {a.findings_high}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-right">
                    <span className={a.findings_medium > 0 ? 'text-severity-medium font-medium' : 'text-tron-500'}>
                      {a.findings_medium}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-right">
                    <span className={a.findings_low > 0 ? 'text-severity-low font-medium' : 'text-tron-500'}>
                      {a.findings_low}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-right text-white font-medium">{a.findings_total}</td>
                  <td className="px-5 py-3 text-right text-tron-400 text-xs whitespace-nowrap">
                    {new Date(a.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
              {audits.length === 0 && (
                <tr>
                  <td colSpan={10} className="px-5 py-12 text-center text-tron-500">
                    {statusFilter !== 'all' ? `No ${statusFilter} audits.` : 'No audits yet.'}
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
