const API_BASE = '/api';

// API key stored in localStorage for convenience
export function getApiKey(): string {
  return localStorage.getItem('tron-api-key') || '';
}

export function setApiKey(key: string) {
  localStorage.setItem('tron-api-key', key);
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const key = getApiKey();
  // Ensure path has leading slash
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  const res = await fetch(`${API_BASE}${normalizedPath}`, {
    credentials: 'include',
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(key ? { 'X-API-Key': key } : {}),
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

export const listGithubRepos = (org?: string) =>
  request<GithubRepo[]>(`/integrations/github/repos${org ? `?org=${org}` : ''}`);

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
  fetch(`${API_BASE}/api-keys/${id}`, {
    method: 'DELETE',
    headers: { 'X-API-Key': getApiKey() },
  }).then(r => {
    if (!r.ok) throw new Error(`${r.status}: ${r.statusText}`);
  });

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
  created_at: string;
}

export interface FindingListResponse {
  items: Finding[];
  total: number;
  page: number;
  page_size: number;
}

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
export function connectAuditWs(auditId: string, onMessage: (data: unknown) => void): WebSocket {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const key = getApiKey().trim();
  const qs = key ? `?token=${encodeURIComponent(key)}` : '';
  const ws = new WebSocket(`${proto}://${window.location.host}/ws/audits/${auditId}${qs}`);
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
