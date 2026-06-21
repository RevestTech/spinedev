const API_BASE = '/api';

/**
 * One-shot migration helper. Previous builds of this SPA stored the master key
 * in `localStorage['tron-api-key']`, which is readable by any script injected
 * via XSS. Auth now rides entirely on the httpOnly admin session cookie
 * (see tron/api/middleware/auth.py::require_api_key). On load we scrub any
 * stale key so an old tab doesn't keep it alive. X-API-Key is still accepted
 * server-side for CLI/automation consumers — just not from the browser.
 */
function purgeLegacyApiKeyStorage(): void {
  try {
    localStorage.removeItem('tron-api-key');
  } catch {
    /* private-mode / quota errors are fine to ignore */
  }
}
purgeLegacyApiKeyStorage();

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  // Ensure path has leading slash
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  const res = await fetch(`${API_BASE}${normalizedPath}`, {
    credentials: 'include',
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  if (res.status === 204) return null as T;
  return res.json();
}

// ── Health ──
export interface HealthResponse {
  status: string;
  service: string;
  uptime_seconds: number;
}

export interface ReadyResponse {
  status: string;
  checks: Record<string, string>;
}

export const getHealth = () =>
  fetch('/health', { credentials: 'include' }).then(r => r.json()) as Promise<HealthResponse>;
export const getReady = () =>
  fetch('/ready', { credentials: 'include' }).then(r => r.json()) as Promise<ReadyResponse>;

// ── Admin UI session (httpOnly cookie; optional X-API-Key for automation) ──
export const adminMe = () =>
  request<{ ok: boolean }>('/admin/me');

export const adminLogin = (password: string) =>
  request<{ ok: boolean }>('/admin/login', {
    method: 'POST',
    body: JSON.stringify({ password }),
  });

export const adminLogout = () =>
  request<{ ok: boolean }>('/admin/logout', {
    method: 'POST',
  });

// ── Projects ──
export interface Project {
  id: string;
  name: string;
  description: string | null;
  repo_url: string | null;
  /** Absolute path on the audit worker host; Tron writes TRON_POST_SCAN.md + agent files here after each audit. */
  agent_handoff_path?: string | null;
  default_branch: string;
  status: string;
  created_at: string;
  updated_at: string;
}

/** Extended project row from GET /api/projects/{id} */
export interface ProjectDetail extends Project {
  company_quality_gates_json?: Record<string, unknown> | null;
  quality_gates_json?: Record<string, unknown> | null;
  plan_questionnaire_json?: Record<string, unknown> | null;
  plan_artifact_json?: Record<string, unknown> | null;
  last_build_result_json?: Record<string, unknown> | null;
  evolve_artifact_json?: Record<string, unknown> | null;
  compliance_control_pack_ids?: string[] | null;
  /** Globs (fnmatch + **) excluded from clone scan — SEC-3 */
  audit_exclude_globs_json?: string[] | null;
  /** Globs marking test paths (tagged on findings) — SEC-3 */
  audit_test_path_globs_json?: string[] | null;
}

export type PlanQuestionnairePayload = Record<string, unknown>;

export interface ProjectListResponse {
  items: Project[];
  total: number;
  page: number;
  page_size: number;
}

export interface GithubRepo {
  name: string;
  full_name: string;
  html_url: string;
  description: string | null;
  stargazers_count: number;
  language: string | null;
  updated_at: string;
}

export const listGithubRepos = (org?: string) => {
  const o = org?.trim();
  const q = o ? `?org=${encodeURIComponent(o)}` : '';
  return request<GithubRepo[]>(`/integrations/github/repos${q}`);
};

// ─── Saved GitHub orgs (org switcher) ───
//
// Lets the user persist a list of GitHub orgs / user accounts they
// audit, so the GithubRepoBrowser can show them in a dropdown instead
// of forcing a re-type each time. Backed by ``saved_github_orgs``
// (Alembic 012). Single shared PAT in vault still — these rows just
// scope which logins the dropdown lists.

export interface SavedGithubOrg {
  id: string;
  login: string;
  display_name: string | null;
  kind: 'org' | 'user';
  pinned: boolean;
  created_at: string;
}

export const listSavedGithubOrgs = () =>
  request<SavedGithubOrg[]>('/integrations/github/saved-orgs');

export const addSavedGithubOrg = (
  payload: { login: string; display_name?: string | null; pinned?: boolean }
) =>
  request<SavedGithubOrg>('/integrations/github/saved-orgs', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

export const deleteSavedGithubOrg = (id: string) =>
  request<void>(`/integrations/github/saved-orgs/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });

export const listProjects = (page = 1, pageSize = 20) =>

  request<ProjectListResponse>(`/projects?page=${page}&page_size=${pageSize}`);

export const getProject = (id: string) =>
  request<ProjectDetail>(`/projects/${id}`);

export const updateProject = (id: string, patch: Partial<{
  name: string;
  description: string | null;
  repo_url: string | null;
  agent_handoff_path: string | null;
  default_branch: string;
  status: string;
  company_quality_gates_json: Record<string, unknown> | null;
  quality_gates_json: Record<string, unknown> | null;
  plan_questionnaire_json: Record<string, unknown> | null;
  compliance_control_pack_ids: string[] | null;
  audit_exclude_globs_json: string[] | null;
  audit_test_path_globs_json: string[] | null;
}>) =>
  request<ProjectDetail>(`/projects/${id}`, { method: 'PUT', body: JSON.stringify(patch) });

export const createProject = (data: { name: string; description?: string; repo_url?: string; agent_handoff_path?: string; default_branch?: string }) =>
  request<Project>('/projects', { method: 'POST', body: JSON.stringify(data) });

export const deleteProject = (id: string) =>
  request<void>(`/projects/${id}`, { method: 'DELETE' });

/** POST /api/plan/{projectId} — Temporal PLAN workflow */
export const startPlanWorkflow = (
  projectId: string,
  body: {
    goals?: string;
    constraints?: string;
    questionnaire?: PlanQuestionnairePayload;
    write_tron_files?: boolean;
  },
) =>
  request<{ workflow_id: string; status: string }>(`/plan/${projectId}`, {
    method: 'POST',
    body: JSON.stringify({
      goals: body.goals ?? '',
      constraints: body.constraints ?? '',
      questionnaire: body.questionnaire,
      write_tron_files: body.write_tron_files ?? true,
    }),
  });

/** POST /api/build/{projectId} — Temporal BUILD workflow */
export const startBuildWorkflow = (projectId: string, task: string) =>
  request<{ workflow_id: string; status: string }>(`/build/${projectId}`, {
    method: 'POST',
    body: JSON.stringify({ task }),
  });

/** POST /api/evolve/{projectId} — Temporal EVOLVE workflow */
export const startEvolveWorkflow = (projectId: string, directive: string) =>
  request<{ workflow_id: string; status: string }>(`/evolve/${projectId}`, {
    method: 'POST',
    body: JSON.stringify({ directive }),
  });

// ── Audits ──
export interface AuditRun {
  id: string;
  project_id: string;
  status: string;
  progress: number;
  findings_total: number;
  findings_critical: number;
  findings_high: number;
  findings_medium: number;
  findings_low: number;
  started_at: string;
  completed_at: string | null;
  error_message: string | null;
  error_stack: string | null;
  threat_intel_alerts_json: string[] | null;
  created_at: string;
}

export interface AuditListResponse {
  items: AuditRun[];
  total: number;
  page: number;
  page_size: number;
}

export const listAudits = (params?: { project_id?: string; status?: string; page?: number; page_size?: number }) => {
  const q = new URLSearchParams();
  if (params?.project_id) q.set('project_id', params.project_id);
  if (params?.status) q.set('status', params.status);
  q.set('page', String(params?.page || 1));
  q.set('page_size', String(params?.page_size || 50));
  return request<AuditListResponse>(`/audits?${q}`);
};

export const getAudit = (id: string) =>
  request<AuditRun>(`/audits/${id}`);

export const createAudit = (data: { project_id: string; branch?: string; trigger_type?: string }) =>
  request<AuditRun>('/audits', { method: 'POST', body: JSON.stringify(data) });

// ── Per-audit cost (LLM ledger aggregation) ──
export interface AuditCostBreakdownRow {
  provider: string;
  model: string;
  operation_detail: string | null;
  request_count: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
}
export interface AuditCost {
  audit_run_id: string;
  total_cost_usd: number;
  total_tokens: number;
  request_count: number;
  breakdown: AuditCostBreakdownRow[];
}
export const getAuditCost = (id: string) =>
  request<AuditCost>(`/audits/${id}/cost`);

// ── Workflow runs (Temporal IDs on audit_runs) ──
export interface WorkflowRunRow {
  audit_run_id: string;
  project_id: string;
  project_name: string;
  workflow_id: string;
  workflow_run_id: string;
  status: string;
  progress: number;
  trigger_type: string | null;
  branch: string | null;
  started_at: string;
  completed_at: string | null;
  error_message: string | null;
}

export interface WorkflowRunListResponse {
  items: WorkflowRunRow[];
  total: number;
  limit: number;
  offset: number;
}

export const listWorkflowRuns = (params?: { status?: string; limit?: number; offset?: number }) => {
  const q = new URLSearchParams();
  if (params?.status) q.set('status', params.status);
  q.set('limit', String(params?.limit ?? 50));
  q.set('offset', String(params?.offset ?? 0));
  return request<WorkflowRunListResponse>(`/workflow-runs?${q}`);
};

// ── API keys (master key only) ──
export interface ApiKeySummary {
  id: string;
  label: string;
  scopes: string[];
  active: boolean;
  created_at: string;
}

export interface ApiKeyCreated {
  id: string;
  label: string;
  scopes: string[];
  api_key: string;
}

export const listApiKeys = () => request<ApiKeySummary[]>('/api-keys');

export const createApiKey = (body: { label: string; scopes?: string[] }) =>
  request<ApiKeyCreated>('/api-keys', { method: 'POST', body: JSON.stringify(body) });

export const revokeApiKey = (id: string) =>
  // Goes through request() so it rides the httpOnly session cookie like every
  // other admin-UI mutation. No localStorage, no explicit X-API-Key header.
  request<null>(`/api-keys/${id}`, { method: 'DELETE' });

// ── Findings ──
export interface Finding {
  id: string;
  audit_run_id: string;
  project_id: string;
  fingerprint: string;
  rule_id: string;
  file_path: string;
  line_start: number | null;
  line_end: number | null;
  severity: string;
  category: string | null;
  title: string;
  description: string;
  suggested_fix: string | null;
  status: string;
  code_snippet: string | null;
  /** Model confidence 0–1; null for legacy rows */
  confidence?: number | null;
  /** Bandit/Semgrep or Layer-3 match */
  deterministic_tool_confirmed?: boolean;
  /** Sandbox: not_applicable, verified, unverified, skipped */
  layer3_execution?: string | null;
  confirming_tools?: string[] | null;
  path_role?: string | null;
  follow_up_recommended?: boolean;
  evidence_source?: string | null;
  /** API-derived single line for badges */
  verification_summary?: string;
  created_at: string;
  updated_at?: string;
}

export interface FindingListResponse {
  items: Finding[];
  total: number;
  page: number;
  page_size: number;
}

export interface SarifImportResponse {
  inserted: number;
  skipped_duplicates: number;
}

export const importSarif = (auditId: string, sarif: Record<string, unknown>) =>
  request<SarifImportResponse>(`/audits/${auditId}/import-sarif`, {
    method: 'POST',
    body: JSON.stringify({ sarif }),
  });

export const dismissFinding = (findingId: string, reason: string) =>
  request<null>(`/findings/${findingId}/dismiss`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  });

export const restoreFinding = (findingId: string) =>
  request<null>(`/findings/${findingId}/restore`, { method: 'POST' });

export interface FindingSuppression {
  project_id: string;
  fingerprint: string;
  reason: string;
  created_at: string;
}

export const listFindingSuppressions = (projectId: string) =>
  request<FindingSuppression[]>(`/projects/${projectId}/finding-suppressions`);

export const deleteFindingSuppression = (projectId: string, fingerprint: string) =>
  request<null>(`/projects/${projectId}/finding-suppressions/${encodeURIComponent(fingerprint)}`, {
    method: 'DELETE',
  });

export const listFindings = (auditId: string, params?: { severity?: string; status?: string; page?: number; page_size?: number }) => {
  const q = new URLSearchParams();
  if (params?.severity) q.set('severity', params.severity);
  if (params?.status) q.set('status', params.status);
  q.set('page', String(params?.page || 1));
  q.set('page_size', String(params?.page_size || 50));
  return request<FindingListResponse>(`/audits/${auditId}/findings?${q}`);
};

// ── Costs ──
export interface CostDashboard {
  summary: {
    total_cost_usd: number;
    total_tokens: number;
    total_audits: number;
    avg_cost_per_audit: number;
    period_start: string;
    period_end: string;
  };
  by_provider: { provider: string; model: string; cost_usd: number; tokens: number; requests: number }[];
  by_project: { project_id: string; project_name: string; cost_usd: number; audit_count: number }[];
  daily_trend: { date: string; cost_usd: number; tokens: number; audits: number }[];
  budget_limit_usd: number;
  budget_used_pct: number;
}

export const getCostDashboard = (startDate?: string, endDate?: string) => {
  const q = new URLSearchParams();
  if (startDate) q.set('start_date', startDate);
  if (endDate) q.set('end_date', endDate);
  return request<CostDashboard>(`/costs/dashboard?${q}`);
};

// ── WebSocket ──
// The WS upgrade request carries the same httpOnly admin session cookie as any
// other fetch; ws.py::_authenticate_ws verifies that cookie before accept().
// We intentionally DO NOT put the API key in the query string — query strings
// bleed into proxy/access logs, referer headers, and browser history.
export function connectAuditWs(auditId: string, onMessage: (data: unknown) => void): WebSocket {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${window.location.host}/ws/audits/${auditId}`);
  ws.onmessage = (e) => onMessage(JSON.parse(e.data));
  return ws;
}

// ── Standards / quality gates (read + project overrides via projects API) ──
export interface MergedGatesResponse {
  project_id: string | null;
  gates: Record<string, unknown>;
}

export const getStandardsDefaults = () =>
  request<Record<string, unknown>>('/standards/defaults');

export const getMergedStandards = (projectId?: string) => {
  const q = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
  return request<MergedGatesResponse>(`/standards/merged${q}`);
};

export interface ControlPackSummary {
  id: string;
}

export const listControlPacks = () =>
  request<{ items: ControlPackSummary[] }>('/standards/control-packs');

// ── Graph ──
export interface CodeFileNode {
  id: string;
  file_path: string;
  language: string | null;
  lines_of_code: number | null;
  dependency_count: number;
  dependent_count: number;
}

export interface DependencyEdge {
  source_path: string;
  target_path: string;
  dependency_type: string;
  import_statement: string | null;
  is_external: boolean;
  is_circular: boolean;
}

export interface ProjectGraphResponse {
  project_id: string;
  nodes: CodeFileNode[];
  edges: DependencyEdge[];
  total_nodes: number;
  total_edges: number;
}

export const getProjectGraph = (projectId: string, limitNodes = 500) =>
  request<ProjectGraphResponse>(`/projects/${projectId}/graph?limit_nodes=${limitNodes}`);
