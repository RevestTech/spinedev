# Enterprise SDLC directives — Spine non-negotiables

Every Spine role that touches production-bound code MUST follow this
contract. The engineer role builds to it. The security_engineer +
auditor roles review against it. Any violation in the security review
is automatic REVIEW BLOCK. The engineer is allowed (encouraged) to
emit a `BLOCKED:` comment rather than weaken the spec.

## 1. Threat model first, code second
Before any feature: enumerate STRIDE per endpoint. Output a
THREAT_MODEL.md entry per project: actor, asset, attack, mitigation.
Code must cite the mitigation line (e.g. `// THREAT: TM-3 — see
THREAT_MODEL.md`). No threat model = no code.

## 2. Zero-trust input boundary
- All external input (HTTP body / query / headers / env / 3rd-party
  API responses) → schema-validated at the boundary, no exceptions.
- `z.number()` banned. Use `z.number().finite().safe()` with explicit
  min/max.
- Mass-assignment forbidden. Every mutator takes an explicit field
  allowlist as a `const` array, not derived from `Object.keys`.
- No `as` casts past validation. No `!` non-null assertions outside
  tests.

## 3. AuthN / AuthZ as code contract
- Every route file MUST start with a declarative AUTH block, e.g.:
  ```ts
  const AUTH = { role: 'operator', ownership: 'self_or_admin' } as const;
  ```
- Lint rule rejects route handlers without AUTH.
- Middleware does FULL JWT verify + revocation lookup, not
  cookie-presence.
- Authorization decisions logged: actor, action, resource, decision,
  reason.

## 4. Database invariants in the DB
- Every business rule expressible as a constraint → `CHECK` / `UNIQUE`
  / `FK` / `NOT NULL` / partial index.
- No app-level "check then write." Use `ON CONFLICT`, `RETURNING`,
  `FOR UPDATE`, advisory locks.
- All migrations reversible, idempotent, tested up+down in CI.
- pgTAP (or equivalent) tests for constraints.

## 5. Money + external systems = idempotency
Any external side-effect (Stripe, email, webhook) requires:
- Idempotency key persisted **before** the call.
- Outbox pattern: DB row first, worker dispatches.
- Reconciliation job that detects orphans (charge w/o order, order
  w/o charge).
- Never call external API **inside** a DB transaction holding row
  locks.

## 6. Observability mandatory
- Structured JSON logs with `trace_id`, `user_id`, `request_id` on
  every line.
- OpenTelemetry spans on: HTTP in, DB query, external HTTP out, cache
  op.
- SLO defined per endpoint (p99 latency, error rate). Alerts wired.
- No `console.log`. No `catch {}` swallow. Every catch logs and
  rethrows OR returns a typed error.

## 7. Failure modes explicit
Every function ships with a `// Failure modes:` comment listing:
timeout, partial write, concurrent caller, malformed input,
downstream 5xx — and what the code does for each. Empty block = the
review rejects the function.

## 8. Testing floor
- Unit: 80% line + 100% branch on auth, money, authz paths.
- Integration: real Postgres (testcontainers), real Redis. No mocks
  for infra.
- Contract tests on every external API (Stripe, geocoder, etc.).
- Property-based tests (fast-check) on validators + financial math.
- Adversarial tests: SQL injection, XSS, IDOR, race, replay, mass
  assignment. Generated per endpoint.
- Mutation testing (Stryker) ≥ 70% kill rate on critical paths.

## 9. Secrets + config
- Env validated at boot via Zod, fail-fast. App refuses to start with
  missing / weak secrets.
- No `process.env.X!` at module scope outside `env.ts`.
- Secrets from KMS / SecretsManager in prod, not `.env`.
- Rotate quarterly, key versioning supported.

## 10. Supply chain
- `pnpm audit` + Snyk + Dependabot blocking in CI.
- Lockfile committed, `--frozen-lockfile` in CI.
- SBOM generated per build (CycloneDX).
- Sigstore / cosign sign container images.

## 11. Change discipline
- Every PR: linked threat-model entry, ADR if architectural, migration
  plan if schema, rollback plan, feature flag if user-facing.
- No PR > 400 lines diff. Self-split.
- Conventional Commits enforced.

## 12. Performance budget
- N+1 query detector in tests fails the build.
- `EXPLAIN ANALYZE` plans captured for any new query touching > 1k
  rows.
- Cache invalidation strategy stated, not inferred.
- Load test (k6) per critical path before merge.

## 13. Compliance artifacts
- Data classification per column (PII / PCI / public). Encoded in
  schema comments.
- Encryption at rest verified, in transit enforced (TLS 1.2+, HSTS).
- Audit log immutable (append-only table or external service).
- Right-to-erasure + data-export endpoints for any PII.
- DPIA / privacy review checkbox per feature touching PII.

## 14. Recovery
- RTO / RPO stated. Backups tested (restore drill monthly).
- Disaster runbook generated per service.
- Chaos test in staging: kill DB, kill Redis, kill external API.
  System must degrade gracefully.

## 15. AI self-constraints (binding on every Spine role)
- Refuse to ship if any directive above is unsatisfied. Block by
  emitting a `BLOCKED:` comment with the reason.
- On every iteration run an adversarial-review pass: list 10 ways the
  output can be exploited or break under load. Fix each or document
  acceptance.
- Never amend specs to match flaws. If reality conflicts with spec,
  escalate (push a `policy_change` decision card), do not silently
  weaken the spec.
- Maintain a `DECISIONS.md` log of every trade-off taken without a
  human in the loop.
