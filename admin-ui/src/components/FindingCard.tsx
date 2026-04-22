import { Finding } from '../api/types'
import { SeverityBadge } from './SeverityBadge'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { useState } from 'react'

interface FindingCardProps {
  finding: Finding
}

export function FindingCard({ finding }: FindingCardProps) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden hover:border-gray-300 transition-colors">
      <div
        className="p-4 bg-gray-50 cursor-pointer hover:bg-gray-100 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <div className="flex items-center gap-3 mb-2">
              <SeverityBadge severity={finding.severity} />
              {finding.status === 'fixed' && (
                <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                  Fixed
                </span>
              )}
              {finding.status === 'acknowledged' && (
                <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                  Acknowledged
                </span>
              )}
            </div>
            <h4 className="font-semibold text-gray-900">{finding.title}</h4>
            <p className="text-sm text-gray-600 mt-1">
              {finding.file_path}
              {finding.line_start && `:${finding.line_start}`}
            </p>
          </div>
          <button className="text-gray-400 hover:text-gray-600 flex-shrink-0 ml-4">
            {expanded ? (
              <ChevronUp className="w-5 h-5" />
            ) : (
              <ChevronDown className="w-5 h-5" />
            )}
          </button>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-gray-200 p-4 bg-white">
          <div className="space-y-4">
            <div>
              <h5 className="text-sm font-semibold text-gray-900 mb-2">
                Description
              </h5>
              <p className="text-sm text-gray-600">{finding.description}</p>
            </div>

            {finding.code_snippet && (
              <div>
                <h5 className="text-sm font-semibold text-gray-900 mb-2">
                  Code Snippet
                </h5>
                <pre className="bg-gray-900 text-gray-100 p-3 rounded text-xs overflow-auto">
                  {finding.code_snippet}
                </pre>
              </div>
            )}

            {finding.suggested_fix && (
              <div>
                <h5 className="text-sm font-semibold text-gray-900 mb-2">
                  Suggested Fix
                </h5>
                <div className="bg-green-50 border border-green-200 rounded p-3">
                  <p className="text-sm text-gray-700 whitespace-pre-wrap">
                    {finding.suggested_fix}
                  </p>
                </div>
              </div>
            )}

            <div className="flex gap-2 pt-2">
              <span className="text-xs bg-gray-100 text-gray-700 px-2 py-1 rounded">
                {finding.rule_id}
              </span>
              {finding.category && (
                <span className="text-xs bg-gray-100 text-gray-700 px-2 py-1 rounded">
                  {finding.category}
                </span>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
