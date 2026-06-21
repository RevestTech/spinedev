import type { Finding } from '../api'

/** User-facing text for `layer3_execution` from the API. */
export function formatLayer3Execution(v: string | null | undefined): string {
  if (v == null || v === '') return '—'
  const labels: Record<string, string> = {
    not_applicable: 'Not applicable (out of sandbox scope for this severity)',
    verified: 'Execution check: signal strengthened in sandbox',
    unverified: 'Not proven by execution test (inference or no automated test)',
    skipped: 'Sandbox unavailable — not execution-checked (critical/high)',
  }
  return labels[v] ?? v
}

export function formatFindingEvidence(f: Finding): string {
  if (f.verification_summary && f.verification_summary.trim()) {
    return f.verification_summary
  }
  const parts: string[] = []
  if (f.confidence != null) {
    parts.push(`Confidence ${(f.confidence * 100).toFixed(0)}%`)
  } else {
    parts.push('Confidence not recorded (legacy or pre-capture run)')
  }
  if (f.deterministic_tool_confirmed === true) {
    parts.push('static tool or execution corroboration')
  }
  if (f.layer3_execution) {
    parts.push(formatLayer3Execution(f.layer3_execution))
  }
  if (f.confirming_tools?.length) {
    parts.push(`Tools: ${f.confirming_tools.join(', ')}`)
  }
  if (f.path_role === 'test') {
    parts.push('test path')
  }
  if (f.evidence_source) {
    parts.push(`source: ${f.evidence_source}`)
  }
  if (f.follow_up_recommended) {
    parts.push('follow-up recommended')
  }
  return parts.join(' · ')
}
