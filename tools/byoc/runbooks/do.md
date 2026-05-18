# DigitalOcean BYOC Runbook

> Operator-facing playbook for provisioning a Spine Hub into a **customer's DigitalOcean team** via project-scoped API token. Pair with [`tools/byoc/clouds/do.sh`](../clouds/do.sh). Drivers: Decision #20 (DO is a 5th-cloud candidate alongside Fly).

---

## 1. What this provisions

| Component | DO resource | Mode `app` (default) | Mode `doks` |
|---|---|---|---|
| Compute | Hub container | App Platform service, basic-xs | DOKS 1.28 (1× s-2vcpu-4gb) |
| Postgres | Managed Postgres | db-s-1vcpu-1gb | same |
| Trusted source | DB firewall locked to App / DOKS only | ✔ | ✔ |
| TLS | `*.ondigitalocean.app` auto-cert | ✔ | cert-manager + Let's Encrypt (DOKS) |

## 2. What the customer must grant Spine

A **project-scoped read+write API token** generated in the customer's team.

1. Customer signs in to DO → Project → Settings → API → Generate New Token.
2. Set: scope = project-scoped, capabilities = read+write, expiry = 90 days (rotate quarterly).
3. Share with vendor via vault-secret-share flow.

## 3. Provisioning

```bash
# 1. Vendor stores token in vault.
spine-vault kv put kv/byoc/<do-team>/do_token value=<token>

# 2. Dry-run.
tools/byoc/provision.sh --non-interactive --dry-run \
    --cloud=do --account=<do-team> \
    --region=nyc3 --mode=app \
    --hub-version=1.0.0 --bundle-id=$(uuidgen) \
    --admin-email=founder@startup.com \
    --credentials-ref=vault://kv/byoc/<do-team>/do_token

# 3. Real run.
```

Wall-clock: ~5–7 min (Postgres provisioning is the slowest step in `app` mode; DOKS adds ~5 min on top).

## 4. Success criteria

- `doctl apps list` (App mode) shows `spine-hub-<bundle>` with phase `ACTIVE`
- `doctl databases list` shows `spine-hub-<bundle>-pg` with status `online`
- `https://<app>.ondigitalocean.app/healthz` returns 200
- Hub Decision Queue shows "Day-0 bootstrap complete" with `cloud=do`

## 5. Rollback / teardown

```bash
tools/byoc/provision.sh --destroy --cloud=do \
    --account=<do-team> \
    --credentials-ref=vault://kv/byoc/<do-team>/do_token --force
```

Order: App / DOKS cluster → Managed Postgres. The Postgres deletion does NOT remove automated backups for 7 days — restore window per DO's default retention. To purge fully, also delete the backups via `doctl databases backups`.

## 6. Exit ramp

1. Customer revokes the API token.
2. Hub keeps running. Customer takes over App Platform / DOKS dashboard.
3. Optional: spine export to another shape.

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `doctl account get` 401 | token expired or scope insufficient | re-issue with read+write project scope |
| App stuck in `BUILDING` | image registry rate-limited | DO retries automatically; wait 5 min, or pin to a specific tag instead of `:latest` |
| Postgres unreachable from App | trusted-source rule not yet propagated | wait 2 min; `doctl databases firewalls list <db-id>` to confirm App ID is present |
| DOKS pods CrashLoopBackOff with "vault unsealed" | OpenBao init container failed | `kubectl logs -n spine deploy/spine-hub -c vault-init`; usually a Workload Identity binding issue if reaching out to GCP/AWS vault adapter — confirm in-cluster OpenBao at this tier |
| `--destroy` complains DB has active connections | App didn't tear down first | re-run with `--force`; orchestrator order is App → DB but parallel races possible if interrupted |

## 8. Cost guardrails

App mode steady-state (nyc3):

- App Platform basic-xs: ~$12/mo
- Managed Postgres db-s-1vcpu-1gb: ~$15/mo
- Bandwidth: 1 TB outbound included
- **Total: ~$27/mo**

DOKS mode: ~$24/mo cluster (1× s-2vcpu-4gb node) + ~$15 Postgres = ~$40/mo + load balancer ~$12 if using ingress = ~$50/mo. Recommend `app` for Founder tier.

## 9. References

- [`tools/byoc/provision.sh`](../provision.sh)
- [`tools/byoc/clouds/do.sh`](../clouds/do.sh)
- [`docs/DEPLOYMENT_SHAPES.md`](../../../docs/DEPLOYMENT_SHAPES.md)
- DO App Platform: <https://docs.digitalocean.com/products/app-platform/>
