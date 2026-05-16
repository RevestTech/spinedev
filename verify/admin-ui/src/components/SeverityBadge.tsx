import clsx from 'clsx'

interface SeverityBadgeProps {
  severity: string
  className?: string
}

const severityConfig = {
  critical: { bg: 'bg-red-100', text: 'text-red-800', dot: 'bg-red-600' },
  high: { bg: 'bg-orange-100', text: 'text-orange-800', dot: 'bg-orange-600' },
  medium: { bg: 'bg-yellow-100', text: 'text-yellow-800', dot: 'bg-yellow-600' },
  low: { bg: 'bg-blue-100', text: 'text-blue-800', dot: 'bg-blue-600' },
  info: { bg: 'bg-gray-100', text: 'text-gray-800', dot: 'bg-gray-600' },
} as const

export function SeverityBadge({ severity, className }: SeverityBadgeProps) {
  const config =
    severityConfig[severity.toLowerCase() as keyof typeof severityConfig] ||
    severityConfig.info

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-2 px-3 py-1 rounded-full text-sm font-medium',
        config.bg,
        config.text,
        className
      )}
    >
      <span className={clsx('w-2 h-2 rounded-full', config.dot)}></span>
      {severity.charAt(0).toUpperCase() + severity.slice(1)}
    </span>
  )
}
