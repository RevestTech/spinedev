export interface Project {
  id: string
  name: string
  description?: string
  repo_url?: string
  default_branch: string
  status: string
  created_at: string
  updated_at: string
  quality_score?: number
  open_findings?: number
  last_audit?: string
  monthly_cost_usd?: number
}

export interface ProjectListResponse {
  items: Project[]
  total: number
  page: number
  page_size: number
}

export interface AuditRun {
  id: string
  project_id: string
  status: string
  progress: number
  findings_total: number
  findings_critical: number
  findings_high: number
  findings_medium: number
  findings_low: number
  started_at: string
  completed_at?: string
  error_message?: string
  created_at: string
}

export interface AuditListResponse {
  items: AuditRun[]
  total: number
  page: number
  page_size: number
}

export interface Finding {
  id: string
  audit_run_id: string
  project_id: string
  fingerprint: string
  rule_id: string
  file_path: string
  line_start?: number
  line_end?: number
  severity: string
  category?: string
  title: string
  description: string
  suggested_fix?: string
  status: string
  code_snippet?: string
  confidence?: number | null
  deterministic_tool_confirmed?: boolean
  layer3_execution?: string | null
  confirming_tools?: string[] | null
  path_role?: string | null
  follow_up_recommended?: boolean
  evidence_source?: string | null
  verification_summary?: string
  created_at: string
  updated_at?: string
}

export interface FindingListResponse {
  items: Finding[]
  total: number
  page: number
  page_size: number
}

export interface HealthResponse {
  status: string
  service: string
  uptime_seconds: number
}

export interface ReadyResponse {
  status: string
  checks: Record<string, string>
}

export interface CostSummary {
  total_cost_usd: number
  total_tokens: number
  total_audits: number
  avg_cost_per_audit: number
  period_start: string
  period_end: string
}

export interface CostByProvider {
  provider: string
  model: string
  cost_usd: number
  tokens: number
  requests: number
}

export interface CostByProject {
  project_id: string
  project_name: string
  cost_usd: number
  audit_count: number
}

export interface DailyCost {
  date: string
  cost_usd: number
  tokens: number
  audits: number
}

export interface CostDashboardData {
  summary: CostSummary
  by_provider: CostByProvider[]
  by_project: CostByProject[]
  daily_trend: DailyCost[]
  budget_limit_usd: number
  budget_used_pct: number
}

export interface WebSocketEvent {
  event_type: string
  workflow_id?: string
  project_id?: string
  timestamp: string
  data: Record<string, unknown>
}
