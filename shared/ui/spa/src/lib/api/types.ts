// Spine Hub SPA — TypeScript types (V3 Wave 3 part 2, Squad SPA3).
//
// THIS FILE IS NOW A RE-EXPORT FAÇADE.
//
// The source of truth is the FastAPI OpenAPI document at /api/v2/spec.
// `shared/ui/spa/scripts/codegen-types.sh` generates `types.generated.ts`
// from that document. This file re-exports the shapes the SPA panels
// import (Citation, DecisionCard, RoleChatRequest, …) so panels never
// had to learn the OpenAPI naming convention.
//
// Why a façade and not a wholesale rename:
//
//   1. Panels written by SPA1/SPA2/SPA3 already import names like
//      `DecisionCard` / `RoleChatResponse` / `Citation` from
//      `$lib/api/types`. Renaming them would touch ~10 files for zero
//      behavioural change.
//   2. The OpenAPI generator emits `components["schemas"]["Foo"]` indexed
//      access types; the façade unwraps those into named exports so DX
//      stays exactly as it was.
//   3. Hand-rolled types stay as a FALLBACK so the SPA still builds on a
//      machine that has never run codegen (no `npm install` here per
//      squad scope). Once codegen runs, the generated file shadows the
//      fallback (uncomment the re-export block below).
//
// Maintenance contract:
//   - When a backend route adds a field, run
//     `bash shared/ui/spa/scripts/codegen-types.sh` against a running
//     Hub. That writes `types.generated.ts`.
//   - The hand-written fallback SHOULD be updated to match (or deleted
//     entirely once Wave 4 lands the build-time codegen step).
//   - Tests import from `$lib/api/types` — they don't care which path
//     populates the names.
//
// Decision drivers: #3 (Hub surfaces), #5 (active push decisions),
// #12 (Cite-or-Refuse — Citation chip), #25 (Keycloak User shape).

// ---------------------------------------------------------------------------
// Generated-types re-export (Wave 4 will make this the only path)
// ---------------------------------------------------------------------------
//
// When `types.generated.ts` exists (after codegen-types.sh runs), the
// following block could be uncommented to mirror named exports from it:
//
//   import type { components } from './types.generated';
//   export type Citation             = components['schemas']['Citation'];
//   export type DecisionCard         = components['schemas']['DecisionCard'];
//   export type DecisionList         = components['schemas']['DecisionList'];
//   export type DecisionActionResponse = components['schemas']['DecisionActionResponse'];
//   export type RoleChatRequest      = components['schemas']['RoleChatRequest'];
//   export type RoleChatResponse     = components['schemas']['RoleChatResponse'];
//   export type KgResult             = components['schemas']['KgResult'];
//   export type KgSearchResponse     = components['schemas']['KgSearchResponse'];
//
// Squad SPA3 keeps it commented until codegen has actually run on a
// developer machine — otherwise svelte-check fails on a missing import.
// Wave 4 CI flips this on as part of the `npm run build` pipeline (run
// codegen BEFORE svelte-check / vite build).

// ---------------------------------------------------------------------------
// Hand-rolled fallback — identical to the pre-codegen contract
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
// Registry (mirrors shared/api/routes/registry.py) — SPA2 added these.
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
