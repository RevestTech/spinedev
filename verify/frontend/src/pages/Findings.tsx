import { useState, useEffect, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  ArrowLeft,
  FileCode,
  Filter,
  ChevronDown,
  ChevronRight,
  Lightbulb,
  Download,
  FileText,
  Table,
  Copy,
  FileType,
} from 'lucide-react'
import Card, { CardBody } from '../components/Card'
import SeverityBadge from '../components/SeverityBadge'
import * as api from '../api'
import {
  fetchAllFindingsForExport,
  findingsToMarkdown,
  findingsToCsv,
  findingsToPdf,
  downloadTextFile,
} from '../utils/findingsExport'
import { formatFindingEvidence, formatLayer3Execution } from '../utils/findingEvidence'

const SEVERITIES = ['all', 'critical', 'high', 'medium', 'low', 'info'] as const

export default function Findings() {
  const { id } = useParams<{ id: string }>()
  const [severity, setSeverity] = useState<string>('all')
  const [findings, setFindings] = useState<api.Finding[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [exportBusy, setExportBusy] = useState(false)
  const [exportNote, setExportNote] = useState<string | null>(null)
  const [listRev, setListRev] = useState(0)
  const [sarifBusy, setSarifBusy] = useState(false)

  const severityLabel = severity === 'all' ? 'All severities' : `${severity} only`

  const showExportNote = useCallback((msg: string) => {
    setExportNote(msg)
    window.setTimeout(() => setExportNote(null), 2500)
  }, [])

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
  }, [id, severity, page, listRev])

  async function onSarifFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file || !id) return
    setSarifBusy(true)
    try {
      const text = await file.text()
      const sarif = JSON.parse(text) as Record<string, unknown>
      const r = await api.importSarif(id, sarif)
      showExportNote(`SARIF merged: +${r.inserted} (skipped ${r.skipped_duplicates} duplicates)`)
      setListRev(x => x + 1)
    } catch (err) {
      showExportNote(err instanceof Error ? err.message : 'SARIF import failed')
    } finally {
      setSarifBusy(false)
      e.target.value = ''
    }
  }

  async function onDismiss(findingId: string) {
    const reason = window.prompt(
      'Reason to dismiss (stored; suppresses this fingerprint on the next audit)',
    )
    if (reason == null) return
    const t = reason.trim()
    if (!t) return
    try {
      await api.dismissFinding(findingId, t)
      showExportNote('Finding dismissed; fingerprint suppressed for this project')
      setListRev(x => x + 1)
    } catch (err) {
      showExportNote(err instanceof Error ? err.message : 'Dismiss failed')
    }
  }

  function toggleExpand(fid: string) {
    setExpanded(prev => {
      const next = new Set(prev)
      next.has(fid) ? next.delete(fid) : next.add(fid)
      return next
    })
  }

  async function runExport(
    kind: 'md' | 'csv' | 'pdf' | 'clipboard',
  ): Promise<void> {
    if (!id || total === 0 || exportBusy) return
    setExportBusy(true)
    try {
      const items = await fetchAllFindingsForExport(id, severity)
      const short = id.slice(0, 8)
      if (kind === 'md') {
        downloadTextFile(
          `findings-${short}.md`,
          findingsToMarkdown(items, id, severityLabel),
          'text/markdown;charset=utf-8',
        )
        showExportNote('Downloaded Markdown')
      } else if (kind === 'csv') {
        downloadTextFile(`findings-${short}.csv`, findingsToCsv(items), 'text/csv;charset=utf-8')
        showExportNote('Downloaded CSV')
      } else if (kind === 'pdf') {
        await findingsToPdf(items, id, severityLabel)
        showExportNote('Downloaded PDF')
      } else {
        await navigator.clipboard.writeText(findingsToMarkdown(items, id, severityLabel))
        showExportNote('Copied Markdown to clipboard')
      }
    } catch (e) {
      console.error(e)
      showExportNote(e instanceof Error ? e.message : 'Export failed')
    } finally {
      setExportBusy(false)
    }
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

      <div className="rounded-lg border border-tron-600 bg-tron-800/50 px-4 py-3 text-sm text-tron-200">
        <p className="text-tron-100 font-medium">Candidates for human review</p>
        <p className="text-tron-400 mt-1 leading-relaxed">
          Severity labels are triage priority, not a guarantee of exploitability. Each item includes
          model confidence, whether static tools or execution checks agreed, and Layer 3 status when
          the sandbox ran. Treat these as input to your own validation—not a pentest attestation.
        </p>
      </div>

      {/* Filters + export */}
      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <Filter className="w-4 h-4 text-tron-400 shrink-0" />
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
        <div className="flex flex-wrap items-center gap-2">
          <label className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-tron-800 text-tron-300 border border-tron-700 hover:bg-tron-700 cursor-pointer">
            <input
              type="file"
              accept="application/json,.sarif,application/sarif+json"
              className="hidden"
              disabled={!id || sarifBusy}
              onChange={onSarifFile}
            />
            {sarifBusy ? 'Importing…' : 'Import SARIF'}
          </label>
          <span className="text-xs text-tron-500 mr-1 flex items-center gap-1">
            <Download className="w-3.5 h-3.5" />
            Export
          </span>
          <button
            type="button"
            disabled={total === 0 || exportBusy}
            onClick={() => runExport('md')}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-tron-800 text-tron-300 border border-tron-700 hover:bg-tron-700 hover:text-white disabled:opacity-40 disabled:pointer-events-none"
            title="Download all matching findings as Markdown"
          >
            <FileText className="w-3.5 h-3.5" />
            .md
          </button>
          <button
            type="button"
            disabled={total === 0 || exportBusy}
            onClick={() => runExport('csv')}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-tron-800 text-tron-300 border border-tron-700 hover:bg-tron-700 hover:text-white disabled:opacity-40 disabled:pointer-events-none"
            title="Download all matching findings as CSV"
          >
            <Table className="w-3.5 h-3.5" />
            .csv
          </button>
          <button
            type="button"
            disabled={total === 0 || exportBusy}
            onClick={() => runExport('pdf')}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-tron-800 text-tron-300 border border-tron-700 hover:bg-tron-700 hover:text-white disabled:opacity-40 disabled:pointer-events-none"
            title="Download all matching findings as PDF"
          >
            <FileType className="w-3.5 h-3.5" />
            .pdf
          </button>
          <button
            type="button"
            disabled={total === 0 || exportBusy}
            onClick={() => runExport('clipboard')}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-tron-800 text-tron-300 border border-tron-700 hover:bg-tron-700 hover:text-white disabled:opacity-40 disabled:pointer-events-none"
            title="Copy all matching findings as Markdown"
          >
            <Copy className="w-3.5 h-3.5" />
            Clipboard
          </button>
          {exportBusy && <span className="text-xs text-tron-500">Preparing…</span>}
          {exportNote && !exportBusy && (
            <span className="text-xs text-accent-light">{exportNote}</span>
          )}
        </div>
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
                  <div className="pt-3 space-y-1 text-xs text-tron-300">
                    <div className="text-tron-400 font-medium">Evidence</div>
                    <p className="leading-relaxed">{formatFindingEvidence(f)}</p>
                    {f.status === 'open' && (
                      <button
                        type="button"
                        onClick={ev => { ev.stopPropagation(); void onDismiss(f.id) }}
                        className="mt-2 text-xs text-tron-500 hover:text-amber-400 underline-offset-2 hover:underline"
                      >
                        Dismiss & suppress on re-audit
                      </button>
                    )}
                    {f.layer3_execution && (
                      <p className="text-tron-500">
                        Layer 3: {formatLayer3Execution(f.layer3_execution)}
                      </p>
                    )}
                  </div>
                  {/* Description */}
                  <div>
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
