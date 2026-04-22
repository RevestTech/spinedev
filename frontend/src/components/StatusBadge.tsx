import { Loader2, CheckCircle2, XCircle, Clock } from 'lucide-react'

const config: Record<string, { bg: string; text: string; icon: typeof Clock }> = {
  running: { bg: 'bg-status-running/15', text: 'text-status-running', icon: Loader2 },
  completed: { bg: 'bg-status-completed/15', text: 'text-status-completed', icon: CheckCircle2 },
  failed: { bg: 'bg-status-failed/15', text: 'text-status-failed', icon: XCircle },
  queued: { bg: 'bg-status-queued/15', text: 'text-status-queued', icon: Clock },
  pending: { bg: 'bg-status-queued/15', text: 'text-status-queued', icon: Clock },
}

export default function StatusBadge({ status }: { status: string }) {
  const c = config[status] || config.queued
  const Icon = c.icon
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${c.bg} ${c.text}`}>
      <Icon className={`w-3 h-3 ${status === 'running' ? 'animate-spin' : ''}`} />
      {status}
    </span>
  )
}
