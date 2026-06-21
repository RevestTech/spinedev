# Master backlog — remaining work vs proposal

**Purpose:** List **only open items** versus **`docs/archive/PROPOSAL.md`**. Delivered scope lives in **`docs/project/BRD.md`** (business) and **`docs/project/TRD.md`** (technical). Verified evidence index: **`docs/project/REQUIREMENTS_TRACEABILITY.md`**. **Documentation map:** **`docs/BLUEPRINT.md`**.

**Status vocabulary:** **`docs/project/REQUIREMENTS_TRACEABILITY.md`** (**Done** / **Partial** / **Not started** / **Deferred**).

---

## Open backlog (proposal-aligned)

**None.** Proposal-aligned gaps tracked previously (**SEC-5** deep verification second pass) are **Done**:

- **Temporal:** **`deep_verify_follow_up_findings`** activity — **`tron/workflows/activities.py`**, **`tron/workflows/audit_workflow.py`** (between Layer 3 and **`synthesize_findings`**), **`tron/worker.py`** registration.
- **In-process audits:** **`apply_deep_verify_retry_pass_to_outputs`** — **`tron/services/layer3_findings.py`**, invoked from **`tron/services/audit_executor.py`** after suppressions and before **`follow_up_recommended`** flags.
- **Helpers:** **`tron/workflows/finding_merge.py`** (`dedupe_findings_dicts`), Layer 3 dict tagging **`layer3_execution`** in **`verify_findings_with_sandbox`**.

Closing any future row updates **`BRD.md`**, **`TRD.md`**, and **`docs/project/REQUIREMENTS_TRACEABILITY.md`** in the same change.

---

## Deferred (explicit — not backlog debt)

| ID | Decision | Reference |
|----|----------|-----------|
| **Certified attestation packs** | Third-party **certified** compliance vendor packs / subscriptions — **not** a committed deliverable. Reference packs + APIs **Done**. | **`docs/project/ADR-002-compliance-certified-packs.md`** |

---

## Optional polish (does not block proposal closure)

| Item | Notes |
|------|-------|
| **Golden suite scale-up** | ISO prompt/parser regression is **already** gated in CI (**`.github/workflows/prompt-regression.yml`** — daily cron + PR/push on agents/schemas/golden paths). Optional: grow **`tests/golden_suite/`** or add pass-rate policies if the corpus becomes large. |
| **Roadmap enhancements** | Audit prod-profile, issue-tracker sync — **`docs/project/TRD.md`** §9. |

---

## Non-product work (production readiness)

**Infrastructure, TLS/CORS ops, sandbox hardening options, scaling docs, Grafana proof, docs hygiene:** **`docs/project/HARDENING_REVIEW_TODO.md`**.

---

## Process (when adding a future backlog row)

1. Implement with tests and evidence pointers (routes, workflows, migrations).
2. Update **`docs/project/REQUIREMENTS_TRACEABILITY.md`** (verified deliveries + Partial/Deferred sections).
3. Update **`docs/project/BRD.md`** / **`docs/project/TRD.md`** if advertised scope changes.

---

*Historical sprint checklist lived in prior revisions of this file; evidence remains in **`docs/project/REQUIREMENTS_TRACEABILITY.md`** and git history.*
