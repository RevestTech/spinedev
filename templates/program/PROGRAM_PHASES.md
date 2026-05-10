# Program phase ledger — project name here

Update this table when a lifecycle gate changes. Conductor and memory roles should cite row states instead of rewriting history silently.

| Phase | Artifact path | Owner roles | Gate status (`draft/block/approved/live`) | Sign-off snapshot |
|-------|----------------|-------------|----------------------------------------------|-------------------|
| Intake | `program/POLICY.stub.md` | Legal / Compliance | draft | |
| Requirements | `program/REQ-0001.md` | product + humans | draft | |
| Architecture | DECISIONS.md / ADRs | architect | draft | |
| Build coordination | conductor directives | conductor | blocked until REQ approved | |
| Verification | `program/qa/*` | qa | draft | |

Status vocabulary:

- `draft` — work in flight; implementation directives MUST NOT run.
- `blocked` — dependency missing; escalate in reports.
- `approved` — human sign-off logged in REQ or policy artifact.
- `live` — release train active; coordinate with operator.
