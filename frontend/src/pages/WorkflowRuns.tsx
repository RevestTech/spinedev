import { useState } from 'react'
import { Link } from 'react-router-dom'
import { GitBranch, Filter } from 'lucide-react'
import Card from '../components/Card'
import StatusBadge from '../components/StatusBadge'
import { usePolling } from '../hooks/usePolling'
import * as api from '../api'

const STATUS_FILTERS = ['all', 'running', 'completed', 'failed', 'queued'] as const

export default function WorkflowRuns() {
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const { data } = usePolling(
    () =>
      api.listWorkflowRuns({
        status: statusFilter === 'all' ? undefined : statusFilter,
        limit: 100,
        offset: 0,
      }),
    4000,
    [statusFilter],
  )

  const rows = data?.items ?? []

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <GitBranch className="w-7 h-7 text-accent" />
            Workflow runs
          </h1>
          <p className="text-tron-400 text-sm mt-1">
            Temporal workflow IDs mapped to audit runs ({data?.total ?? 0} total)
          </p>
        </div>
      </div>

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

      <Card>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-tron-700 text-tron-400 text-xs">
                <th className="text-left px-5 py-3 font-medium">Audit</th>
                <th className="text-left px-5 py-3 font-medium">Project</th>
                <th className="text-left px-5 py-3 font-medium">Temporal workflow</th>
                <th className="text-left px-5 py-3 font-medium">Run ID</th>
                <th className="text-left px-5 py-3 font-medium">Status</th>
                <th className="text-right px-5 py-3 font-medium">Progress</th>
                <th className="text-left px-5 py-3 font-medium">Started</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <tr
                  key={r.audit_run_id}
                  className="border-b border-tron-700/50 hover:bg-tron-700/30 transition-colors"
                >
                  <td className="px-5 py-3">
                    <Link
                      to={`/audits/${r.audit_run_id}`}
                      className="text-accent-light hover:underline font-mono text-xs"
                    >
                      {r.audit_run_id.slice(0, 8)}
                    </Link>
                  </td>
                  <td className="px-5 py-3 text-tron-300 text-xs">
                    <Link
                      to={`/projects/${r.project_id}`}
                      className="hover:text-accent-light hover:underline"
                    >
                      {r.project_name || r.project_id.slice(0, 8)}
                    </Link>
                  </td>
                  <td className="px-5 py-3 font-mono text-xs text-tron-200 max-w-[200px] truncate" title={r.workflow_id}>
                    {r.workflow_id}
                  </td>
                  <td className="px-5 py-3 font-mono text-xs text-tron-400 max-w-[160px] truncate" title={r.workflow_run_id}>
                    {r.workflow_run_id}
                  </td>
                  <td className="px-5 py-3">
                    <StatusBadge status={r.status} />
                  </td>
                  <td className="px-5 py-3 text-right text-tron-300">{r.progress}%</td>
                  <td className="px-5 py-3 text-tron-400 text-xs whitespace-nowrap">
                    {new Date(r.started_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && (
            <div className="px-5 py-12 text-center text-tron-500 text-sm">No workflow runs match this filter.</div>
          )}
        </div>
      </Card>
    </div>
  )
}
