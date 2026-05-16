import { Server, CheckCircle2, XCircle, RefreshCw } from 'lucide-react'
import Card, { CardHeader, CardBody } from '../components/Card'
import { usePolling } from '../hooks/usePolling'
import * as api from '../api'

export default function SystemHealth() {
  const { data: health, loading: hLoad } = usePolling(() => api.getHealth(), 5000, [])
  const { data: ready, loading: rLoad } = usePolling(() => api.getReady(), 5000, [])

  const loading = (hLoad && !health) || (rLoad && !ready)
  const uptimeHours = health ? Math.floor(health.uptime_seconds / 3600) : 0
  const uptimeMins = health ? Math.floor((health.uptime_seconds % 3600) / 60) : 0

  return (
    <div className="p-6 space-y-6 max-w-3xl">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">System health</h1>
          <p className="text-tron-400 text-sm mt-1">
            API liveness and dependency checks &middot; polled every 5s
          </p>
        </div>
        <div className="flex items-center gap-2 text-tron-500 text-xs">
          <RefreshCw className="w-3.5 h-3.5" />
          Auto-refresh
        </div>
      </div>

      {loading && (
        <div className="text-tron-500 text-sm">Loading health status...</div>
      )}

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Server className="w-4 h-4 text-tron-400" />
            <span className="text-sm font-medium text-white">API</span>
          </div>
        </CardHeader>
        <CardBody className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm text-tron-300">Status</span>
            <span className={`text-sm font-medium ${health?.status === 'ok' ? 'text-green-400' : 'text-red-400'}`}>
              {health?.status === 'ok' ? 'Healthy' : health?.status ?? 'Unknown'}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-tron-300">Service</span>
            <span className="text-sm font-mono text-white">{health?.service ?? '—'}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-tron-300">Uptime</span>
            <span className="text-sm font-medium text-white">{uptimeHours}h {uptimeMins}m</span>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <span className="text-sm font-medium text-white">Readiness checks</span>
        </CardHeader>
        <CardBody className="space-y-3">
          {ready?.checks && Object.entries(ready.checks).length > 0 ? (
            Object.entries(ready.checks).map(([name, status]) => (
              <div key={name} className="flex items-center justify-between">
                <span className="text-sm text-tron-300 capitalize">{name}</span>
                <div className="flex items-center gap-1.5">
                  {status === 'ok' ? (
                    <CheckCircle2 className="w-3.5 h-3.5 text-green-400" />
                  ) : (
                    <XCircle className="w-3.5 h-3.5 text-red-400" />
                  )}
                  <span className={`text-sm ${status === 'ok' ? 'text-green-400' : 'text-red-400'}`}>
                    {status === 'ok' ? 'OK' : status}
                  </span>
                </div>
              </div>
            ))
          ) : (
            <div className="text-tron-500 text-sm">No readiness payload yet.</div>
          )}
          {ready?.status && (
            <div className="pt-2 border-t border-tron-700 text-xs text-tron-500">
              Overall: <span className="text-tron-300">{ready.status}</span>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  )
}
