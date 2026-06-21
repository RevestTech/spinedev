# Business Requirements Document (BRD) — Tron

**Audience:** Product, security governance, enterprise buyers.  
**Companion:** **`docs/project/TRD.md`** (technical design and evidence pointers). **Documentation map:** **`docs/BLUEPRINT.md`**.

## 1. Purpose

Tron is an **enterprise AI QA and assurance platform**: orchestrated specialist agents, deterministic scanners first, schema-validated findings, optional execution verification, objective quality gates, and **handoff into scanned application repos** so downstream IDE agents inherit verified context.

**Core principle:** verify before trust—raw LLM output is never the sole signal for severity.

## 2. Problems addressed

- AI-assisted coding produces plausible output that is expensive to review manually.
- Teams need **repeatable**, **auditable** assurance—not one-off chat reviews.
- Moving code toward production requires **gates**, **evidence**, and **clear limits** on what automation can claim.

## 3. Business outcomes delivered

The proposal-scale capability set is **implemented** unless listed under §6–§7 below. Summary:

| Area | Outcome |
|------|---------|
| **Modes** | AUDIT, PLAN, BUILD, FIX, EVOLVE — orchestrated workflows with persisted artifacts. |
| **Agents** | Six ISO specializations (security, builder, QA, performance, compliance, documentation); parallel dispatch under **`AuditManager`** with merge/dedupe and cross-validation on severe findings. |
| **Trust** | Deterministic tools (e.g. Bandit, Semgrep) → LLM gap analysis → schema validation → optional Layer 3 sandbox → calibrated confidence; SARIF import merge; path filters; dismiss/suppress triage; provenance surfaced in API/UI/export/handoff. |
| **Standards** | Default + merged quality gates; built-in **reference** compliance control packs (not third-party certification). |
| **Interfaces** | REST, CLI, MCP, primary admin SPA (`frontend/`). |
| **Multi-repo handoff** | Managed regions in app-repo files + optional **`tron.md`** activity log when **`agent_handoff_path`** is set. |
| **Operations** | API keys/scopes, budgets, Temporal workflows, observability hooks per compose stack. |

**Detailed requirement-to-evidence mapping:** **`docs/project/REQUIREMENTS_TRACEABILITY.md`** (verified deliveries table).

## 4. Positioning (buyer-facing)

- **Parallel ISO “swarm” breadth:** concurrent specialist agents, supervisor merge—not unconstrained dynamic task spawning.
- **Layered hostile-code assurance:** OSV-backed dependency checks + advisory signals, scanners, SecurityISO patterns for insider/backdoor-style issues **when visible in source**, optional sandbox checks—not a proof of “no malware anywhere.”

(See root **`README.md`** for narrative.)

## 5. Known limitations (honest scope)

- **Security findings** remain partly **inferential** (LLM + patterns); universal exploit proof is **not** guaranteed.
- **Deep verification (SEC-5)** raises assurance with an optional **second sandbox pass** for top‑N critical/high findings still **unverified** after Layer 3 (`TRON_DEEP_VERIFY_TOP_N`)—not a pentest or malware-proof guarantee.
- **Production observability / QA suites** (e.g. SmartBear-class breadth) are **not** Tron’s core SKU—integration via SARIF and gates is the lever.

## 6. Deferred (explicit)

| Topic | Decision |
|-------|----------|
| **Third-party certified attestation / vendor compliance subscriptions** | **Deferred** — **`docs/project/ADR-002-compliance-certified-packs.md`**. Reference packs and APIs are **Done**. |

## 7. Remaining business backlog

**Proposal-aligned:** none — see **`docs/project/MASTER_PROPOSAL_TODO.md`**.

**Non-product production readiness:** **`docs/project/HARDENING_REVIEW_TODO.md`** (CORS prod config, sandbox hardening options, scaling docs, etc.).

## 8. References

- **`docs/archive/PROPOSAL.md`** — original full proposal (historical intent).
- **`docs/project/REQUIREMENTS_TRACEABILITY.md`** — Done / Partial / Deferred vocabulary and evidence index.
- **`docs/project/TRD.md`** — technical requirements and architecture pointers.
