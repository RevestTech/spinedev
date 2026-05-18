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
