import * as api from '../api'
import { formatFindingEvidence, formatLayer3Execution } from './findingEvidence'

const EXPORT_PAGE_SIZE = 200

const SEVERITY_ORDER: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  info: 4,
}

export function sortFindingsForExport(list: api.Finding[]): api.Finding[] {
  return [...list].sort((a, b) => {
    const sa = SEVERITY_ORDER[a.severity.toLowerCase()] ?? 99
    const sb = SEVERITY_ORDER[b.severity.toLowerCase()] ?? 99
    if (sa !== sb) return sa - sb
    const pa = a.file_path || ''
    const pb = b.file_path || ''
    if (pa !== pb) return pa.localeCompare(pb)
    return (a.line_start ?? 0) - (b.line_start ?? 0)
  })
}

export async function fetchAllFindingsForExport(
  auditId: string,
  severityFilter: string,
): Promise<api.Finding[]> {
  const all: api.Finding[] = []
  let page = 1
  for (;;) {
    const r = await api.listFindings(auditId, {
      severity: severityFilter === 'all' ? undefined : severityFilter,
      page,
      page_size: EXPORT_PAGE_SIZE,
    })
    all.push(...r.items)
    if (all.length >= r.total || r.items.length === 0) break
    page += 1
  }
  return sortFindingsForExport(all)
}

function csvEscape(value: string | null | undefined): string {
  if (value == null || value === '') return ''
  const t = String(value)
  if (/[",\n\r]/.test(t)) return `"${t.replace(/"/g, '""')}"`
  return t
}

export function findingsToMarkdown(
  findings: api.Finding[],
  auditId: string,
  severityLabel: string,
): string {
  const shortId = auditId.slice(0, 8)
  const when = new Date().toISOString()
  const lines: string[] = [
    '# Audit findings',
    '',
    '**Tron shows candidates for review. Severity is not a proof of exploitability unless execution verification says otherwise.**',
    '',
    `- **Audit:** \`${shortId}\` (${auditId})`,
    `- **Filter:** ${severityLabel}`,
    `- **Exported:** ${when}`,
    `- **Count:** ${findings.length}`,
    '',
  ]
  findings.forEach((f, i) => {
    const loc = `${f.file_path}${f.line_start != null ? `:${f.line_start}` : ''}`
    lines.push(
      `## ${i + 1}. [${f.severity.toUpperCase()}] ${f.title}`,
      '',
      `- **Location:** \`${loc}\``,
    )
    if (f.category) lines.push(`- **Category:** ${f.category}`)
    if (f.rule_id) lines.push(`- **Rule:** ${f.rule_id}`)
    lines.push(`- **Status:** ${f.status}`)
    lines.push(`- **Evidence:** ${formatFindingEvidence(f)}`)
    if (f.layer3_execution) {
      lines.push(`- **Execution check (Layer 3):** ${formatLayer3Execution(f.layer3_execution)}`)
    }
    lines.push('', f.description || '_No description._', '')
    if (f.code_snippet) {
      lines.push('```', f.code_snippet, '```', '')
    }
    if (f.suggested_fix) {
      lines.push('### Suggested fix', '', f.suggested_fix, '')
    }
    lines.push('---', '')
  })
  return lines.join('\n').trimEnd() + '\n'
}

export function findingsToPlainText(
  findings: api.Finding[],
  auditId: string,
  severityLabel: string,
): string {
  const shortId = auditId.slice(0, 8)
  const when = new Date().toISOString()
  const parts: string[] = [
    'Audit findings',
    'Candidates for review; severity is not proof of exploitability.',
    `Audit: ${shortId} (${auditId})`,
    `Filter: ${severityLabel}`,
    `Exported: ${when}`,
    `Count: ${findings.length}`,
    '',
  ]
  findings.forEach((f, i) => {
    const loc = `${f.file_path}${f.line_start != null ? `:${f.line_start}` : ''}`
    parts.push(
      `${i + 1}. [${f.severity.toUpperCase()}] ${f.title}`,
      `   Location: ${loc}`,
    )
    if (f.category) parts.push(`   Category: ${f.category}`)
    if (f.rule_id) parts.push(`   Rule: ${f.rule_id}`)
    parts.push(`   Status: ${f.status}`)
    parts.push(`   Evidence: ${formatFindingEvidence(f)}`, '', `   ${(f.description || '').replace(/\n/g, '\n   ')}`, '')
    if (f.code_snippet) {
      parts.push('   Code:', ...f.code_snippet.split('\n').map((line) => `   ${line}`), '')
    }
    if (f.suggested_fix) {
      parts.push('   Suggested fix:', ...f.suggested_fix.split('\n').map((line) => `   ${line}`), '')
    }
    parts.push('---', '')
  })
  return parts.join('\n').trimEnd() + '\n'
}

export function findingsToCsv(findings: api.Finding[]): string {
  const headers = [
    'severity',
    'title',
    'file_path',
    'line_start',
    'line_end',
    'category',
    'rule_id',
    'status',
    'confidence',
    'deterministic_tool_confirmed',
    'layer3_execution',
    'confirming_tools',
    'description',
    'suggested_fix',
    'code_snippet',
    'fingerprint',
    'id',
  ]
  const rows = findings.map((f) =>
    [
      f.severity,
      f.title,
      f.file_path,
      f.line_start ?? '',
      f.line_end ?? '',
      f.category ?? '',
      f.rule_id ?? '',
      f.status,
      f.confidence != null && f.confidence !== undefined ? String(f.confidence) : '',
      f.deterministic_tool_confirmed ? 'true' : 'false',
      f.layer3_execution ?? '',
      (f.confirming_tools || []).join(';'),
      f.description,
      f.suggested_fix ?? '',
      f.code_snippet ?? '',
      f.fingerprint,
      f.id,
    ].map(csvEscape),
  )
  return [headers.join(','), ...rows.map((r) => r.join(','))].join('\n') + '\n'
}

export function downloadTextFile(filename: string, content: string, mime: string): void {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export async function findingsToPdf(
  findings: api.Finding[],
  auditId: string,
  severityLabel: string,
): Promise<void> {
  const { jsPDF } = await import('jspdf')
  const doc = new jsPDF({ unit: 'mm', format: 'a4' })
  const pageW = doc.internal.pageSize.getWidth()
  const margin = 14
  const maxW = pageW - margin * 2
  let y = 16
  const lineH = 5
  const titleH = 6

  const ensureSpace = (needed: number) => {
    const pageH = doc.internal.pageSize.getHeight()
    if (y + needed > pageH - margin) {
      doc.addPage()
      y = margin
    }
  }

  doc.setFontSize(14)
  doc.setFont('helvetica', 'bold')
  doc.text('Audit findings', margin, y)
  y += titleH + 2

  doc.setFontSize(9)
  doc.setFont('helvetica', 'normal')
  const meta = [
    'Candidates for review; severity is not proof of exploitability.',
    `Audit: ${auditId.slice(0, 8)} (${auditId})`,
    `Filter: ${severityLabel}`,
    `Exported: ${new Date().toISOString()}`,
    `Count: ${findings.length}`,
  ]
  for (const line of meta) {
    ensureSpace(lineH)
    const wrapped = doc.splitTextToSize(line, maxW) as string[]
    for (const w of wrapped) {
      ensureSpace(lineH)
      doc.text(w, margin, y)
      y += lineH
    }
  }
  y += 3

  findings.forEach((f, i) => {
    const loc = `${f.file_path}${f.line_start != null ? `:${f.line_start}` : ''}`
    const head = `${i + 1}. [${f.severity.toUpperCase()}] ${f.title}`
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(10)
    ensureSpace(titleH + lineH)
    const headLines = doc.splitTextToSize(head, maxW) as string[]
    for (const hl of headLines) {
      ensureSpace(lineH)
      doc.text(hl, margin, y)
      y += lineH
    }

    doc.setFont('helvetica', 'normal')
    doc.setFontSize(9)
    const bodyParts = [
      `Location: ${loc}`,
      f.category ? `Category: ${f.category}` : '',
      f.rule_id ? `Rule: ${f.rule_id}` : '',
      `Status: ${f.status}`,
      `Evidence: ${formatFindingEvidence(f)}`,
      '',
      f.description || '',
      f.code_snippet ? `\nCode:\n${f.code_snippet}` : '',
      f.suggested_fix ? `\nSuggested fix:\n${f.suggested_fix}` : '',
    ].filter(Boolean)
    const body = bodyParts.join('\n')
    const bodyLines = doc.splitTextToSize(body, maxW) as string[]
    for (const bl of bodyLines) {
      ensureSpace(lineH)
      doc.text(bl, margin, y)
      y += lineH
    }
    y += 4
  })

  doc.save(`findings-${auditId.slice(0, 8)}.pdf`)
}
