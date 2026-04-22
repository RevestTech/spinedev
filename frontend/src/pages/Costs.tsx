import { DollarSign, TrendingUp, Zap, BarChart3 } from 'lucide-react'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  BarChart, Bar, Cell,
} from 'recharts'
import Card, { CardHeader, CardBody } from '../components/Card'
import { usePolling } from '../hooks/usePolling'
import * as api from '../api'

export default function Costs() {
  const { data, loading, error } = usePolling(() => api.getCostDashboard(), 30000, [])

  if (loading && !data) {
    return (
      <div className="p-6 flex items-center justify-center h-64 text-tron-500">
        Loading cost data...
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="p-6">
        <h1 className="text-2xl font-bold text-white mb-4">Costs</h1>
        <Card>
          <CardBody className="text-center py-12 text-tron-500">
            Cost tracking data unavailable. Run some audits to generate cost data.
          </CardBody>
        </Card>
      </div>
    )
  }

  const { summary, by_provider, by_project, daily_trend, budget_limit_usd, budget_used_pct } = data

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Costs</h1>
        <p className="text-tron-400 text-sm mt-1">
          LLM usage and spending &middot; {summary.period_start} to {summary.period_end}
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { icon: DollarSign, label: 'Total Cost', value: `$${summary.total_cost_usd.toFixed(2)}`, color: 'bg-green-600' },
          { icon: Zap, label: 'Total Tokens', value: summary.total_tokens.toLocaleString(), color: 'bg-blue-600' },
          { icon: BarChart3, label: 'Audits', value: summary.total_audits, color: 'bg-accent' },
          { icon: TrendingUp, label: 'Avg per Audit', value: `$${summary.avg_cost_per_audit.toFixed(2)}`, color: 'bg-orange-600' },
        ].map(s => (
          <Card key={s.label}>
            <CardBody className="flex items-center gap-3">
              <div className={`w-9 h-9 rounded-lg ${s.color} flex items-center justify-center shrink-0`}>
                <s.icon className="w-4 h-4 text-white" />
              </div>
              <div>
                <div className="text-lg font-bold text-white">{s.value}</div>
                <div className="text-xs text-tron-400">{s.label}</div>
              </div>
            </CardBody>
          </Card>
        ))}
      </div>

      {/* Budget bar */}
      {budget_limit_usd > 0 && (
        <Card>
          <CardBody>
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm text-tron-300">Budget Usage</span>
              <span className="text-sm font-medium text-white">
                ${summary.total_cost_usd.toFixed(2)} / ${budget_limit_usd.toFixed(2)}
              </span>
            </div>
            <div className="w-full h-2.5 bg-tron-700 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${budget_used_pct > 90 ? 'bg-red-500' : budget_used_pct > 70 ? 'bg-yellow-500' : 'bg-green-500'}`}
                style={{ width: `${Math.min(budget_used_pct, 100)}%` }}
              />
            </div>
            <div className="text-right text-xs text-tron-400 mt-1">{budget_used_pct.toFixed(1)}% used</div>
          </CardBody>
        </Card>
      )}

      {/* Daily trend + By provider */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <span className="text-sm font-medium text-white">Daily Spending</span>
          </CardHeader>
          <CardBody>
            {daily_trend.length > 0 ? (
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={daily_trend}>
                  <defs>
                    <linearGradient id="costGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="date" tick={{ fill: '#94a3b8', fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={v => `$${v}`} />
                  <Tooltip
                    contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#e2e8f0' }}
                    formatter={(v: number) => [`$${v.toFixed(4)}`, 'Cost']}
                  />
                  <Area type="monotone" dataKey="cost_usd" stroke="#6366f1" fill="url(#costGrad)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[200px] flex items-center justify-center text-tron-500 text-sm">No trend data</div>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <span className="text-sm font-medium text-white">By Provider / Model</span>
          </CardHeader>
          <CardBody>
            {by_provider.length > 0 ? (
              <div className="space-y-3">
                {by_provider.map((p, i) => (
                  <div key={i} className="flex items-center justify-between">
                    <div>
                      <div className="text-sm text-white">{p.provider}</div>
                      <div className="text-xs text-tron-400">{p.model} &middot; {p.requests} requests</div>
                    </div>
                    <div className="text-right">
                      <div className="text-sm font-medium text-white">${p.cost_usd.toFixed(4)}</div>
                      <div className="text-xs text-tron-400">{p.tokens.toLocaleString()} tokens</div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="h-[200px] flex items-center justify-center text-tron-500 text-sm">No provider data</div>
            )}
          </CardBody>
        </Card>
      </div>

      {/* By project */}
      {by_project.length > 0 && (
        <Card>
          <CardHeader>
            <span className="text-sm font-medium text-white">Cost by Project</span>
          </CardHeader>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-tron-700 text-tron-400 text-xs">
                  <th className="text-left px-5 py-3 font-medium">Project</th>
                  <th className="text-right px-5 py-3 font-medium">Audits</th>
                  <th className="text-right px-5 py-3 font-medium">Cost</th>
                </tr>
              </thead>
              <tbody>
                {by_project.map(p => (
                  <tr key={p.project_id} className="border-b border-tron-700/50">
                    <td className="px-5 py-3 text-white">{p.project_name}</td>
                    <td className="px-5 py-3 text-right text-tron-300">{p.audit_count}</td>
                    <td className="px-5 py-3 text-right font-medium text-white">${p.cost_usd.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}
