# PII / Secret Redactor — `shared/audit/redactor.py`

Implements **STORY-3.1.4** (REQ-INIT-3 EPIC-3.1 NFR-3): optional payload
redaction applied before any `AuditRecord` is persisted to
`spine_audit.audit_event`.

## Why redact

The audit log is append-only and immutable — once a secret lands in
`prev_event_hash` chain order it cannot be removed without breaking the
chain. Catching secrets at the write boundary is the only safe option.
Beyond pure operational hygiene, GDPR, HIPAA and SOC-2 all treat
plaintext PII inside log stores as a reportable incident.

## Default rule set

| Rule | Severity | Pattern (abridged) |
| --- | --- | --- |
| `aws_access_key`   | default | `AKIA[0-9A-Z]{16}` |
| `aws_secret_key`   | default | 40-char base64-ish blob with non-secret boundaries |
| `jwt`              | default | `eyJ...eyJ...sig` three-segment JWT |
| `github_pat`       | default | `gh[pousr]_[A-Za-z0-9]{36,}` |
| `anthropic_key`    | default | `sk-ant-...` |
| `openai_key`       | default | `sk-[A-Za-z0-9]{32,}` |
| `bearer_token`     | default | `Bearer <token>` headers |
| `credit_card`      | default | 13–16 digit grouped sequences |
| `private_key_pem`  | default | `-----BEGIN ... PRIVATE KEY-----` blocks |
| `email`            | opt_in  | RFC-ish address |
| `us_ssn`           | opt_in  | `NNN-NN-NNNN` |
| `us_phone`         | opt_in  | NANP layout |

Replacement string is `[REDACTED]` (override per-rule via `replacement`).

## Severity tiers

- `always` — runs even when the caller asks for the most permissive
  policy. Reserve for unambiguously secret patterns.
- `default` — production setting; ~zero false-positive risk.
- `opt_in` — high false-positive surface (e.g. emails); off unless an
  org bundle promotes the rule.

`redact(record, severity_floor="opt_in")` enables everything; the
default floor is `"default"`.

## Org bundle customisation

`load_org_rules(bundle_id)` looks at
`$SPINE_HOME/bundles/<bundle_id>/redaction_rules.json` and merges custom
rules with the defaults. Rules with the same `name` override the
default of that name. Example:

```json
[
  {"name": "acme_employee_id",
   "pattern": "ACME-\\d{6}",
   "severity": "always"}
]
```

## Performance

Patterns are compiled once per process; the second call onward is a
pure regex sweep. Empirical: ~3–8 µs per record for the default rule
set on the rationale + metadata payload typical of Spine actions.

## Anti-patterns

- **Do not** redact `prompt_hash` / `output_hash`. They are SHA-256
  digests — no recoverable content — and are the only join key for
  prompt-cache analyses.
- **Do not** mutate the input record. `redact()` returns a copy so the
  caller can keep the raw object in process-local diagnostics without
  leaking it to the audit chain.
- **Do not** disable redaction globally to "debug a missing field".
  Use `skip_redaction=True` per-call (see `write_via_psql`).

## Cross-references

- Backlog: `STORY-3.1.4`
- Schema: `db/flyway/sql/V15__spine_audit_schema.sql`
- Pydantic model: `shared/audit/audit_record.py`
- Exporter integration: `shared/audit/exporter.py` (re-runs redaction
  on the way out, in case rules tightened post-write).
