import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft, FileCode, Filter, ChevronDown, ChevronRight, Lightbulb } from 'lucide-react'
import Card, { CardHeader, CardBody } from '../components/Card'
import SeverityBadge from '../components/SeverityBadge'
import * as api from '../api'

const SEVERITIES = ['all', 'critical', 'high', 'medium', 'low', 'info'] as const

export default function Findings() {
  const { id } = useParams<{ id: string }>()
  const [severity, setSeverity] = useState<string>('all')
  const [findings, setFindings] = useState<api.Finding[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  useEffect(() => {
    if (!id) return
    api.listFindings(id, {
      severity: severity === 'all' ? undefined : severity,
      page,
      page_size: 50,
    }).then(r => {
      setFindings(r.items)
      setTotal(r.total)
    })
  }, [id, severity, page])

  function toggleExpand(fid: string) {
    setExpanded(prev => {
      const next = new Set(prev)
      next.has(fid) ? next.delete(fid) : next.add(fid)
      return next
    })
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-4">
        <Link to={`/audits/${id}`} className="p-2 rounded-lg hover:bg-tron-700 text-tron-400 hover:text-white transition-colors">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div>
          <h1 className="text-xl font-bold text-white">Findings</h1>
          <p className="text-tron-400 text-sm mt-0.5">
            {total} finding{total !== 1 ? 's' : ''} &middot; Audit {id?.slice(0, 8)}
          </p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2">
        <Filter className="w-4 h-4 text-tron-400" />
        {SEVERITIES.map(s => (
          <button
            key={s}
            onClick={() => { setSeverity(s); setPage(1) }}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors capitalize ${
              severity === s
                ? 'bg-accent text-white'
                : 'bg-tron-800 text-tron-400 hover:bg-tron-700 hover:text-white border border-tron-700'
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      {/* Findings list */}
      <div className="space-y-2">
        {findings.map(f => {
          const isOpen = expanded.has(f.id)
          return (
            <Card key={f.id}>
              <button
                onClick={() => toggleExpand(f.id)}
                className="w-full px-5 py-3 flex items-center gap-3 text-left hover:bg-tron-700/20 transition-colors"
              >
                {isOpen ? (
                  <ChevronDown className="w-4 h-4 text-tron-400 shrink-0" />
                ) : (
                  <ChevronRight className="w-4 h-4 text-tron-400 shrink-0" />
                )}
                <SeverityBadge severity={f.severity} />
                <span className="text-sm text-white font-medium flex-1 truncate">{f.title}</span>
                <span className="flex items-center gap-1 text-xs text-tron-400 shrink-0">
                  <FileCode className="w-3 h-3" />
                  {f.file_path}{f.line_start ? `:${f.line_start}` : ''}
                </span>
              </button>

              {isOpen && (
                <div className="px-5 pb-4 space-y-3 border-t border-tron-700/50">
                  {/* Description */}
                  <div className="pt-3">
                    <div className="text-xs text-tron-400 mb-1">Description</div>
                    <div className="text-sm text-tron-200 leading-relaxed">{f.description}</div>
                  </div>

                  {/* Code snippet */}
                  {f.code_snippet && (
                    <div>
                      <div className="text-xs text-tron-400 mb-1">Code</div>
                      <pre className="bg-tron-900 border border-tron-700 rounded-lg px-4 py-3 text-xs text-tron-200 overflow-x-auto font-mono leading-relaxed">
                        {f.code_snippet}
                      </pre>
                    </div>
                  )}

                  {/* Suggested fix */}
                  {f.suggested_fix && (
                    <div className="flex items-start gap-2 bg-accent/5 border border-accent/20 rounded-lg px-4 py-3">
                      <Lightbulb className="w-4 h-4 text-accent-light shrink-0 mt-0.5" />
                      <div>
                        <div className="text-xs text-accent-light font-medium mb-1">Suggested Fix</div>
                        <div className="text-sm text-tron-200 leading-relaxed">{f.suggested_fix}</div>
                      </div>
                    </div>
                  )}

                  {/* Metadata */}
                  <div className="flex gap-4 text-xs text-tron-500 pt-2 border-t border-tron-700/50">
                    {f.rule_id && <span>Rule: {f.rule_id}</span>}
                    {f.category && <span>Category: {f.category}</span>}
                    <span>Status: {f.status}</span>
                    {f.fingerprint && <span className="font-mono">{f.fingerprint.slice(0, 12)}</span>}
                  </div>
                </div>
              )}
            </Card>
          )
        })}

        {findings.length === 0 && (
          <Card>
            <CardBody className="text-center py-12 text-tron-500">
              {severity !== 'all' ? `No ${severity} findings.` : 'No findings for this audit.'}
            </CardBody>
          </Card>
        )}
      </div>

      {/* Pagination */}
      {total > 50 && (
        <div className="flex items-center justify-center gap-2">
          <button
            disabled={page <= 1}
            onClick={() => setPage(p => p - 1)}
            className="px-3 py-1.5 bg-tron-800 text-tron-400 rounded-lg text-xs border border-tron-700 hover:bg-tron-700 disabled:opacity-50"
          >
            Previous
          </button>
          <span className="text-xs text-tron-400">
            Page {page} of {Math.ceil(total / 50)}
          </span>
          <button
            disabled={page >= Math.ceil(total / 50)}
            onClick={() => setPage(p => p + 1)}
            className="px-3 py-1.5 bg-tron-800 text-tron-400 rounded-lg text-xs border border-tron-700 hover:bg-tron-700 disabled:opacity-50"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
