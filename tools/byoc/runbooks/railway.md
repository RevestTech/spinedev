# Railway BYOC Runbook

> Operator-facing playbook for provisioning a Spine Hub into a **customer's Railway project** via team-invite delegation. Pair with [`tools/byoc/clouds/railway.sh`](../clouds/railway.sh). Founder-tier highest-priority cloud alongside AWS — Railway is the fastest "sign-up → Hub running" path Day 1.

---

## 1. What this provisions

| Component | Railway resource |
|---|---|
| Service | `spine-hub` service running `spine/hub:<version>` |
| Postgres | Railway-managed Postgres add-on (`pluginCreate { name: postgresql }`) |
| Env vars | `SPINE_HUB_VERSION`, `SPINE_BUNDLE_ID`, `SPINE_DATABASE_URL` (via Railway template `${{Postgres.DATABASE_URL}}`), `SPINE_HUB_ADMIN_EMAIL`, plus secret slots that Hub fills from its in-cluster OpenBao |
| Domain | `serviceDomainCreate` → `spine-hub-<bundle-id>.up.railway.app` (TLS auto-provisioned) |

Vault adapter at this tier defaults to `openbao-bundled` — Railway has no first-class secret manager equivalent to AWS Secrets Manager / Azure Key Vault. Customer can upgrade to OpenBao-in-separate-Railway-service or external HashiCorp Vault if they want Vault-grade audit; default is in-Hub OpenBao with Shamir 3-of-5 shares printed once at Day-0.

## 2. What the customer must grant Spine

A **team invite** to vendor's `spine-ops@<vendor-domain>` Railway account with **Admin** on **one project**.

1. Customer signs in to Railway → Project → Settings → Members → Invite.
2. Customer adds `spine-ops@<vendor-domain>` with role `Admin`.
3. Customer issues a **project-scoped API token** (Project Settings → Tokens) and shares the token (via vendor's vault-secret-share flow — never email/Slack).

## 3. Provisioning

```bash
# 1. Vendor stores token in vault.
spine-vault kv put kv/byoc/<railway-project-id>/railway_token value=<token>

# 2. Dry-run.
tools/byoc/provision.sh --non-interactive --dry-run \
    --cloud=railway --account=<railway-project-id> \
    --hub-version=1.0.0 --bundle-id=$(uuidgen) \
    --admin-email=founder@startup.com \
    --credentials-ref=vault://kv/byoc/<railway-project-id>/railway_token

# 3. Real run (drop --dry-run).
```

Real run time: ~2 minutes (Railway is fast — no IaC apply, just GraphQL mutations).

## 4. Success criteria

- `curl -fsS https://spine-hub-<bundle-id>.up.railway.app/healthz` returns 200 within 3 minutes
- Railway dashboard shows `spine-hub` service and `Postgres` plugin both `Running`
- Customer logs in to Hub with admin email; sees the Day-0 Decision Card

## 5. Rollback / teardown

```bash
tools/byoc/provision.sh --destroy --cloud=railway \
    --account=<railway-project-id> \
    --credentials-ref=vault://kv/byoc/<railway-project-id>/railway_token --force
```

Order: serviceDelete → pluginDelete. The Railway project itself is owned by the customer; the script never deletes the project.

## 6. Exit ramp

1. Customer revokes the `spine-ops` invite from project members.
2. Customer rotates the Railway API token they shared with vendor (or revokes it entirely).
3. Hub keeps running. Customer takes over the env-var management UI in the Railway dashboard.
4. (Optional) `spine export` and migrate to Shape 3 customer-cloud K8s — Railway is intentionally portable.

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| GraphQL `me { id }` returns null | API token scope is too narrow (account-scoped, not project-scoped) | re-issue project-scoped token via Project → Settings → Tokens |
| `pluginCreate` errors with "Postgres unavailable in region" | region not yet enabled for Postgres add-on | switch region (`--region=us-east4`); not all Railway regions have Postgres GA |
| Hub service shows `Crashed` immediately | most often missing required env var | `railway logs --service spine-hub`; confirm `SPINE_DATABASE_URL` references the Postgres plugin name correctly |
| Domain provisioned but 502s | TLS cert pending issuance from Let's Encrypt | wait 60–90 s; Railway TLS is fully managed but propagation can lag |
| Vault unseal shares lost | only displayed once at Day-0 | unrecoverable; provision a new Hub and migrate via `spine export | spine import` (this is the Shamir compromise documented in §32 layer 8) |

## 8. Cost guardrails

Railway billing is usage-based; steady-state for a single Hub:

- Hub service (1× 2 GB RAM / 1 vCPU): ~$10/mo
- Postgres add-on (1 GB RAM, 5 GB disk): ~$5/mo
- Outbound bandwidth: included up to a limit
- **Total: ~$15–25/mo** (cheapest BYOC tier — by design, for Founder evaluation)

## 9. References

- [`tools/byoc/provision.sh`](../provision.sh)
- [`tools/byoc/clouds/railway.sh`](../clouds/railway.sh)
- [`docs/DEPLOYMENT_SHAPES.md`](../../../docs/DEPLOYMENT_SHAPES.md)
- Railway GraphQL docs: <https://docs.railway.app/reference/public-api>
