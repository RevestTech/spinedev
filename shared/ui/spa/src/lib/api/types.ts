// Spine Hub SPA — TypeScript types mirroring shared/api Pydantic models.
//
// Hand-maintained subset; the source of truth is the OpenAPI document
// emitted by shared/api/openapi_spec.py at /api/v2/spec. SPA2 will wire
// the openapi-typescript generator in CI so these stay in lock-step.
//
// Decision drivers: #3 (Hub surfaces), #5 (active push decisions),
// #12 (Cite-or-Refuse — Citation chip), #25 (Keycloak User shape).

// ---------------------------------------------------------------------------
// User / identity (mirrors shared/identity/models.py:User)
// ---------------------------------------------------------------------------

export interface SpineUser {
  /** Keycloak `sub` claim — opaque stable ID. */
  sub: string;
  /** Display label; usually `preferred_username` or `email`. */
  username: string;
  /** Verified email if the IdP supplies one. */
  email?: string;
  /** Realm + client roles flattened. */
  roles: string[];
  /** Federation hub the user authenticated against (per #4 / #10). */
  hub_id?: string;
}

// ---------------------------------------------------------------------------
// Cite-or-Refuse — Citation chip (mirrors shared/mcp/schemas/envelopes.py)
// ---------------------------------------------------------------------------

export type CitationType = 'kg_node' | 'file_line' | 'audit_hash';

export interface Citation {
  type: CitationType;
  /** kg_node id, "path:line[:col]", or audit content_hash. */
  ref: string;
  /** Optional short verbatim excerpt for human review. */
  excerpt?: string | null;
}

// ---------------------------------------------------------------------------
// Generic envelope (mirrors ToolResponse)
// ---------------------------------------------------------------------------

export type ToolStatus = 'ok' | 'error' | 'stub_implementation';

export interface ToolError {
  code: string;
  message: string;
  retryable: boolean;
}

export interface ToolResponse<T = Record<string, unknown>> {
  status: ToolStatus;
  data: T;
  error?: ToolError | null;
  audit_id: string;
  timestamp: string;
  citation: Citation[];
}

// ---------------------------------------------------------------------------
// Decision queue (mirrors shared/api/routes/decisions.py)
// ---------------------------------------------------------------------------

export type DecisionStatus = 'pending' | 'acked' | 'rejected' | 'expired';

export type DecisionClass =
  | 'approval'
  | 'incident'
  | 'release'
  | 'briefing'
  | 'budget'
  | 'policy_change';

export type DecisionSeverity = 'info' | 'warning' | 'critical';

export interface DecisionCard {
  decision_id: string;
  decision_class: DecisionClass;
  project_id?: string | null;
  title: string;
  body: string;
  severity: DecisionSeverity;
  actions: string[];
  status: DecisionStatus;
  created_at: number;
  expires_at?: number | null;
  metadata: Record<string, unknown>;
}

export interface DecisionList {
  ok: boolean;
  items: DecisionCard[];
  total: number;
}

export interface DecisionActionResponse {
  ok: boolean;
  decision_id: string;
  status: DecisionStatus;
  actor: string;
  audit_event_uuid: string;
}

// SSE event envelope from POST /api/v2/decisions/subscribe.
export interface DecisionSseEvent {
  type: 'card_created' | 'card_updated' | string;
  card?: DecisionCard;
}

// ---------------------------------------------------------------------------
// Role chat (mirrors shared/api/routes/role_chat.py)
// ---------------------------------------------------------------------------

export interface RoleChatRequest {
  role: string;
  message: string;
  project_id?: string | null;
  correlation_id?: string | null;
}

export interface RoleChatResponse {
  ok: boolean;
  role: string;
  reply: string;
  actor: string;
  audit_event_uuid: string;
  metadata: Record<string, unknown> & { citations?: Citation[]; stub?: boolean };
}

// ---------------------------------------------------------------------------
// Registry (mirrors shared/api/routes/registry.py) — Squad SPA2
// ---------------------------------------------------------------------------

export type RoleTier = 'master' | 'project';

export interface RoleEntry {
  name: string;
  tier: RoleTier;
  description: string;
  charter_ref?: string | null;
  feature_flag?: string | null;
}

export interface RoleList {
  ok: boolean;
  items: RoleEntry[];
}

export type IntegrationKind =
  | 'scm'
  | 'issue_tracker'
  | 'comms'
  | 'incident'
  | 'grc'
  | 'cloud';

export interface RegistryIntegrationEntry {
  name: string;
  kind: IntegrationKind;
  description: string;
  feature_flag?: string | null;
  requires_vault_path?: string | null;
}

export interface RegistryIntegrationList {
  ok: boolean;
  items: RegistryIntegrationEntry[];
}

// ---------------------------------------------------------------------------
// Audit (mirrors shared/api/routes/audit.py) — Squad SPA2
// ---------------------------------------------------------------------------

export interface AuditRow {
  event_id: number | string;
  event_uuid: string;
  ts: string;
  project_id?: string | null;
  phase?: string | null;
  role?: string | null;
  subsystem?: string | null;
  action?: string | null;
  subject_type?: string | null;
  subject_id?: string | null;
  actor?: string | null;
  rationale?: string | null;
  cost_usd?: number | null;
  correlation_id?: string | null;
  pipeline_version?: string | null;
  content_hash?: string | null;
  prev_content_hash?: string | null;
}

export interface AuditListResponse {
  ok: boolean;
  /** Each item is the raw JSON-line from Postgres; parsed client-side. */
  items: (string | AuditRow)[];
  project_id?: string | null;
  correlation_id?: string | null;
  limit: number;
}

// ---------------------------------------------------------------------------
// Vault config (mirrors shared/api/routes/vault_config.py) — Squad SPA2
// ---------------------------------------------------------------------------

export interface VaultStatusResponse {
  ok: boolean;
  adapter_kind: string;
  endpoint?: string | null;
  healthy: boolean;
  last_error?: string | null;
}

export interface VaultSecretList {
  ok: boolean;
  paths: string[];
  prefix: string;
}

export interface RotateRequest {
  path: string;
  reason: string;
}

export interface RotateResponse {
  ok: boolean;
  path: string;
  rotated_at: string;
  actor: string;
  audit_event_uuid: string;
}

// ---------------------------------------------------------------------------
// Integrations (mirrors shared/api/routes/integrations.py) — Squad SPA2
// ---------------------------------------------------------------------------

export type IntegrationStatus = 'configured' | 'unconfigured' | 'error';

export interface IntegrationDetail {
  name: string;
  kind: string;
  status: IntegrationStatus;
  feature_flag?: string | null;
  vault_path?: string | null;
  last_test_at?: string | null;
  last_test_ok?: boolean | null;
}

export interface IntegrationListResponse {
  ok: boolean;
  items: IntegrationDetail[];
}

export interface TestConnectionResponse {
  ok: boolean;
  name: string;
  healthy: boolean;
  detail: string;
  actor: string;
  audit_event_uuid: string;
}

// ---------------------------------------------------------------------------
// Error envelope (FastAPI HTTPException detail)
// ---------------------------------------------------------------------------

export interface ApiErrorDetail {
  error_code?: string;
  message?: string;
  [key: string]: unknown;
}

export class ApiError extends Error {
  status: number;
  detail: ApiErrorDetail | string;
  constructor(status: number, detail: ApiErrorDetail | string, message?: string) {
    super(message ?? (typeof detail === 'string' ? detail : detail.message ?? `HTTP ${status}`));
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}
