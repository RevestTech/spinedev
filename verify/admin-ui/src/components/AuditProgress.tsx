import { AuditRun } from '../api/types'
import { CheckCircle2, AlertCircle, Clock } from 'lucide-react'

interface AuditProgressProps {
  audit: AuditRun
}

export function AuditProgress({ audit }: AuditProgressProps) {
  const isComplete =
    audit.status === 'completed' || audit.status === 'failed'
  const isFailed = audit.status === 'failed'

  return (
    <div className="space-y-4">
      {/* Status indicator */}
      <div className="flex items-center gap-3">
        {isFailed ? (
          <AlertCircle className="w-6 h-6 text-red-600" />
        ) : isComplete ? (
          <CheckCircle2 className="w-6 h-6 text-green-600" />
        ) : (
          <Clock className="w-6 h-6 text-blue-600 animate-spin" />
        )}
        <div>
          <p className="font-medium text-gray-900 capitalize">{audit.status}</p>
          <p className="text-sm text-gray-600">
            {audit.status === 'completed'
              ? 'Audit completed successfully'
              : audit.status === 'failed'
                ? 'Audit failed with error'
                : 'Audit in progress...'}
          </p>
        </div>
      </div>

      {/* Progress bar */}
      {!isComplete && (
        <div className="space-y-2">
          <div className="flex justify-between items-center">
            <p className="text-sm font-medium text-gray-700">Progress</p>
            <p className="text-sm text-gray-600">{audit.progress}%</p>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div
              className="bg-blue-600 h-2 rounded-full transition-all duration-300"
              style={{ width: `${audit.progress}%` }}
            ></div>
          </div>
        </div>
      )}

      {/* Finding summary */}
      <div className="grid grid-cols-5 gap-2 pt-2">
        <div className="bg-gray-50 rounded p-3">
          <p className="text-xs text-gray-600">Total</p>
          <p className="text-lg font-bold text-gray-900">{audit.findings_total}</p>
        </div>
        <div className="bg-red-50 rounded p-3">
          <p className="text-xs text-red-600">Critical</p>
          <p className="text-lg font-bold text-red-900">
            {audit.findings_critical}
          </p>
        </div>
        <div className="bg-orange-50 rounded p-3">
          <p className="text-xs text-orange-600">High</p>
          <p className="text-lg font-bold text-orange-900">{audit.findings_high}</p>
        </div>
        <div className="bg-yellow-50 rounded p-3">
          <p className="text-xs text-yellow-600">Medium</p>
          <p className="text-lg font-bold text-yellow-900">
            {audit.findings_medium}
          </p>
        </div>
        <div className="bg-blue-50 rounded p-3">
          <p className="text-xs text-blue-600">Low</p>
          <p className="text-lg font-bold text-blue-900">{audit.findings_low}</p>
        </div>
      </div>

      {/* Error message if failed */}
      {isFailed && audit.error_message && (
        <div className="bg-red-50 border border-red-200 rounded p-3">
          <p className="text-sm text-red-700">{audit.error_message}</p>
        </div>
      )}
    </div>
  )
}
