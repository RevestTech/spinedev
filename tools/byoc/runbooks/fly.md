# Fly.io BYOC Runbook

> Operator-facing playbook for provisioning a Spine Hub into a **customer's Fly org**. Pair with [`tools/byoc/clouds/fly.sh`](../clouds/fly.sh). Drivers: Decision #20 (Fly is a 5th-cloud candidate alongside DigitalOcean).

---

## 1. What this provisions

| Component | Fly resource |
|---|---|
| App | `spine-hub-<bundle-id>` (Fly Machines V2) |
| Postgres | `<app>-pg` Fly Postgres cluster (single-node `shared-cpu-1x` Day 1) |
| Attachment | `flyctl postgres attach` → injects `DATABASE_URL` into app secrets |
| Secrets | `flyctl secrets set` for Hub bootstrap (per #9 — values piped from vault subshell, never on disk) |
| Domain | `<app>.fly.dev` with auto-TLS |

Vault adapter at this tier defaults to `openbao-bundled` (same rationale as Railway — Fly has no first-class secret-manager analog). Customer can run OpenBao as a separate Fly app and point Hub at it via `--vault-adapter=external-vault`.

## 2. What the customer must grant Spine

A **Fly org invite** to vendor's `spine-ops@<vendor-domain>` Fly account with Admin role on **one dedicated org** (not their personal org).

```bash
# Customer runs:
flyctl orgs invite --org <customer-spine-byoc-org> spine-ops@<vendor-domain>
```

Vendor also needs a **personal access token** scoped to that org, stored in vendor vault.

## 3. Provisioning

```bash
# 1. Vendor stores token in vault.
spine-vault kv put kv/byoc/<fly-org>/fly_token value=<token>

# 2. Dry-run.
tools/byoc/provision.sh --non-interactive --dry-run \
    --cloud=fly --account=<fly-org-slug> \
    --region=iad --mode=machines \
    --hub-version=1.0.0 --bundle-id=$(uuidgen) \
    --admin-email=founder@startup.com \
    --credentials-ref=vault://kv/byoc/<fly-org>/fly_token

# 3. Real run.
```

Wall-clock: ~3–5 min (Postgres cluster bootstrap is the slowest step).

## 4. Success criteria

- `flyctl apps list --org <fly-org>` shows `spine-hub-<bundle>` with status `running`
- `flyctl postgres list --org <fly-org>` shows `<app>-pg` as `attached`
- `curl -fsS https://<app>.fly.dev/healthz` returns 200
- `flyctl secrets list --app <app>` shows `DATABASE_URL`, `SPINE_HUB_VERSION`, `SPINE_BUNDLE_ID`, `SPINE_HUB_ADMIN_EMAIL`, `KEYCLOAK_ADMIN_PASSWORD`, `SPINE_VAULT_ROOT_TOKEN` (values redacted, as expected)

## 5. Rollback / teardown

```bash
tools/byoc/provision.sh --destroy --cloud=fly \
    --account=<fly-org> \
    --credentials-ref=vault://kv/byoc/<fly-org>/fly_token --force
```

Order: `flyctl apps destroy <app>` → `flyctl apps destroy <app>-pg`. The org itself is owned by the customer; we never destroy the org.

## 6. Exit ramp

1. Customer revokes `spine-ops` from the Fly org.
2. Customer rotates the Fly token they shared.
3. Hub keeps running. Customer takes over `flyctl secrets set` for any rotations going forward.
4. Optional: `spine export` and migrate to another shape — Fly's images are standard OCI so they port cleanly.

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `flyctl deploy` errors with "image pull denied" | private Hub image not yet shared with the Fly Machines puller | confirm `spine/hub:<version>` is on the public spine docker-hub namespace or set `FLY_REGISTRY_AUTH` |
| Postgres attach succeeds but Hub still says "no DATABASE_URL" | propagation lag | wait 30 s; `flyctl machine restart <id>` to force secret re-read |
| App scales to zero unexpectedly | Hub does not yet implement Fly's `auto_stop_machines` opt-out | set `fly.toml: [http_service] auto_stop_machines = false` (post-v1.0 fix: bake into image's default fly.toml) |
| Vault unseal shares stored as Fly secret but Hub still sealed | Hub container did not run unseal-on-start hook | exec into machine: `flyctl ssh console -a <app>` then `/spine/hub/bin/unseal-from-secret.sh` |

## 8. Cost guardrails

Fly steady-state for a single Hub:

- Hub Machine (shared-cpu-2x, 2 GB RAM): ~$10/mo
- Fly Postgres (shared-cpu-1x, 1 GB RAM, 10 GB volume): ~$8/mo
- Bandwidth: 160 GB outbound free per app
- **Total: ~$20/mo** (comparable to Railway)

## 9. References

- [`tools/byoc/provision.sh`](../provision.sh)
- [`tools/byoc/clouds/fly.sh`](../clouds/fly.sh)
- [`docs/DEPLOYMENT_SHAPES.md`](../../../docs/DEPLOYMENT_SHAPES.md)
- Fly Machines: <https://fly.io/docs/machines/>
