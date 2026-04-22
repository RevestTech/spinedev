const colors: Record<string, string> = {
  critical: 'bg-severity-critical/15 text-severity-critical',
  high: 'bg-severity-high/15 text-severity-high',
  medium: 'bg-severity-medium/15 text-severity-medium',
  low: 'bg-severity-low/15 text-severity-low',
  info: 'bg-severity-info/15 text-severity-info',
}

export default function SeverityBadge({ severity }: { severity: string }) {
  const c = colors[severity] || colors.info
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold uppercase tracking-wider ${c}`}>
      {severity}
    </span>
  )
}
