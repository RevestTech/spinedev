# `approval.py` — phase-gate HMAC tokens

Implements `STORY-9.3.1` (gate check) and `STORY-9.3.2` (HMAC tokens) per
`docs/PRD.md#req-init-9` FR-4. Called by `orchestrator/lib/transition.sh`
via subprocess; standard library only (no `pip install` needed).

## First-run setup

```bash
# Generate the per-install 256-bit HMAC key (refuses to overwrite).
python3 orchestrator/lib/approval.py genkey
# -> writes ~/.spine/secrets/hmac.key, mode 0600
```

The script also creates `~/.spine/secrets/` with mode `0700` if missing.
A custom path may be passed: `genkey --path /path/to/key`.

## Filesystem permissions

| Path                       | Mode  | Why                                            |
|----------------------------|-------|------------------------------------------------|
| `~/.spine/secrets/`        | `0700`| Only the owning user can list secret material. |
| `~/.spine/secrets/hmac.key`| `0600`| HMAC key — refuses to load if perms looser.    |

`approval.py` refuses to use a key file with any group/other bits set
(`mode & 0o077 != 0`). Don't `chmod 644`.

## Token lifecycle

1. **Grant** — operator approves a gate: `approval.py grant --project-id 42 --phase plan_approved --approver khash`. This signs a token and inserts a row into `spine_lifecycle.approval` (decision `approved`, `expires_at` = now + TTL). Returns `{approval_id, token, expires_at}` as JSON.
2. **Store** — token is persisted in the `approval.token` column; the orchestrator never re-derives it from scratch.
3. **Present** — the transition engine reads the row for `(project_id, phase)` and passes `token` to verify on every `phase_advance`.
4. **Verify** — `approval.py verify --token "$tok" --project-id 42 --phase plan_approved`. Exits 0 if valid; non-zero with a stderr error message otherwise. `stdout` is always parseable JSON: `{valid, payload, errors}`.
5. **Expire / revoke** — `expires_at` is enforced at verify time. Manual early revocation: `approval.py revoke --approval-id 17` sets `expires_at = NOW()`.

## Token format

`base64url(payload_json) + "." + base64url(HMAC-SHA256(payload_b64, key))`
where the payload is `{project_id, phase, approver, issued_at, expires_at}`
(ISO-8601 UTC timestamps). HMAC is taken over the base64 form, so JSON
canonicalization is irrelevant to verification.

## Multi-approver gates (STORY-9.3.3)

`spine_lifecycle.approval` allows multiple rows per `(project_id, phase)`.
For multi-approver gates, the transition engine queries:

```sql
SELECT approver, token FROM spine_lifecycle.approval
 WHERE project_id = $1 AND phase = $2 AND decision = 'approved'
   AND (expires_at IS NULL OR expires_at > NOW());
```

…verifies each `token` via `approval.py verify`, and counts distinct
`approver` values. Manifest declares the threshold (e.g. `min_approvers: 2`
in `phases.yaml`'s `gate_policy`). `approval.py` itself is single-token;
counting is the engine's job.

## Why per-install symmetric key

V1 ships one symmetric key per install. Pros: zero key-distribution
infrastructure, hermetic verification, debuggable. Cons: no rotation, no
per-approver identity. Deferred per **OQ-2** in
`docs/PRD.md#req-init-9` to v1.1, which will introduce rotation and
optionally per-approver Ed25519 keypairs.

## Calling from `transition.sh`

```bash
result=$(python3 orchestrator/lib/approval.py verify \
    --token "$tok" --project-id "$pid" --phase "$ph") || {
  log_audit "gate_check_failed" "$ph" "$result"; exit 2;
}
# `result` is JSON: { "valid": true, "payload": {...}, "errors": [] }
```

`SPINE_DB_URL` env var overrides the default `postgresql://spine:spine@localhost:33000/spine` used by `grant`/`revoke`.
