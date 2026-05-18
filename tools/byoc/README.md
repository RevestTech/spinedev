# `tools/byoc/` — Spine BYOC provisioning

> Per-cloud Hub provisioning for **Shape 2 — Vendor-Managed (BYOC)** of `docs/DEPLOYMENT_SHAPES.md`. Implements the BYOC delegated-role primitive (Decision #15: NOT SaaS), the 4-deployment-shapes choice (#17), and the 5+ clouds Day 1 mandate (#20).

This is the **vendor-side** automation that provisions a Spine Hub into a **customer's cloud account** using a **customer-granted delegated role**. The vendor's automation runs this script from vendor infrastructure; every cloud-API call inside it uses the customer's delegated credentials. **Spine vendor never holds customer data**; the deployment lives entirely inside the customer's account.

---

## Layout

```
tools/byoc/
├── README.md                  this file
├── provision.sh               orchestrator / dispatcher (single entry point)
├── lib/
│   └── common.sh              shared bash helpers (logging, vault refs,
│                              idempotency lock, dry-run + stub mode)
├── clouds/
│   ├── aws.sh                 AWS (EC2 single-host OR EKS) — most complete
│   ├── azure.sh               Azure (VM OR AKS) — dry-run plan complete
│   ├── gcp.sh                 GCP (GCE OR GKE Autopilot) — dry-run plan complete
│   ├── railway.sh             Railway (service + Postgres add-on) — Founder-tier priority
│   ├── fly.sh                 Fly Machines + Fly Postgres
│   └── do.sh                  DigitalOcean (App Platform OR DOKS)
└── runbooks/
    ├── aws.md                 per-cloud operator runbooks
    ├── azure.md
    ├── gcp.md
    ├── railway.md
    ├── fly.md
    └── do.md
```

## Dispatcher contract

`provision.sh` parses flags + YAML config, validates inputs, acquires an idempotency lock, then sources `clouds/<cloud>.sh` and invokes one of three functions:

| Function | Caller | When |
|---|---|---|
| `byoc_validate_credentials` | `provision.sh` (always, before either of the below) | Asserts the vendor's delegated role assumes successfully against the customer's account. Returns non-zero → orchestrator aborts. |
| `byoc_provision` | `provision.sh` (default mode) | Provisions VPC/network → compute → DB → secrets → TLS → seeds Hub → registers DNS → emits handoff banner. |
| `byoc_destroy` | `provision.sh --destroy` | Tears down everything `byoc_provision` created, in reverse order. |

Each cloud script reads these env vars (exported by `provision.sh`):

| Env var | Source | Description |
|---|---|---|
| `SPINE_BYOC_CLOUD` | `--cloud=` | Cloud target (aws/azure/gcp/railway/fly/do). |
| `SPINE_BYOC_ACCOUNT` | `--account=` | Customer's account/project ref (cloud-specific format). |
| `SPINE_BYOC_REGION` | `--region=` | Cloud region. Per-cloud default if unset. |
| `SPINE_BYOC_MODE` | `--mode=` | Per-cloud deployment mode (e.g. `ec2`/`eks`). |
| `SPINE_HUB_VERSION` | `--hub-version=` | Hub container semver. |
| `SPINE_BYOC_BUNDLE_ID` | `--bundle-id=` | License bundle UUID (V22 schema). |
| `SPINE_BYOC_ADMIN_EMAIL` | `--admin-email=` | Initial Keycloak admin email. |
| `SPINE_BYOC_PARENT_HUB_URL` | `--parent-hub-url=` | Federation parent (#10), empty=root. |
| `SPINE_BYOC_CREDENTIALS_REF` | `--credentials-ref=` | `vault://<path>` for delegated-role creds (per #9). |
| `BYOC_DRY_RUN` | `--dry-run` | If `1`, cloud APIs are echoed not called. |
| `BYOC_INTERACTIVE` | derived from `--non-interactive` | If `0`, refuse to prompt. |
| `BYOC_STUB_CALLS` | auto-set if cloud CLI not on PATH | If `1`, cloud APIs are echoed not called. |
| `BYOC_FORCE` | `--force` | Bypass idempotency lock + healthy-stack guard. |

## Per-cloud capability matrix

| Capability | AWS | Azure | GCP | Railway | Fly | DO |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Real `--dry-run` (prints full plan, no API calls) | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| Live provision (CLI + real auth on PATH) | ✔ real | ✔ scaffold | ✔ scaffold | ✔ real* | ✔ scaffold | ✔ scaffold |
| `byoc_destroy` teardown | ✔ | ✔ (RG cascade) | ✔ | ✔ | ✔ | ✔ |
| Idempotent (resource describe-then-create) | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| Vault-ref credentials (no plaintext on disk) | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| Tagging for cost attribution + cleanup | ✔ | ✔ | ✔ | n/a Railway | ✔ Fly labels | ✔ |
| Cloud-native vault adapter Day 1 | Secrets Manager | Key Vault | Secret Manager | OpenBao bundled | OpenBao bundled | OpenBao bundled |
| K8s mode available | EKS | AKS | GKE Autopilot | — | — | DOKS |
| Cross-region DR (#32 L7) Day 1 | opt-in | opt-in | opt-in | ✗ | ✗ | ✗ |

`*` Railway is **the** most-complete script besides AWS — single GraphQL endpoint, no IaC scaffolding required. Founder-tier highest priority alongside AWS per the agent brief.

`scaffold` = the script enumerates every step as a wrapped `byoc_run_or_stub` call; under `--dry-run` or when the cloud CLI is not on `PATH` the call is logged and skipped. Lifting to "real" only requires (a) the operator has the CLI installed, (b) the credentials-ref resolves to a real role/SP/SA key.

## Secrets posture (#9)

Per Decision #9 (vault-only, no exceptions), **no script in this directory** ever writes a secret value to disk or env-vars it into the current shell.

The pattern is:

```bash
# WRONG (would land the value in the env):
export AWS_ACCESS_KEY_ID="$(byoc_resolve_vault_ref vault://kv/...)"

# RIGHT (subshell only):
( byoc_resolve_vault_ref vault://kv/... | aws sts assume-role --credential-file=/dev/stdin )
```

Validators in `byoc_validate_credentials()` always invoke `byoc_resolve_vault_ref` inside a `( … )` subshell so the value never leaks into the parent shell's environment.

## AI-driver contract (#21)

Every interactive prompt has a non-interactive flag. The full flag matrix is in `provision.sh --help`. A representative AI-driver invocation:

```bash
tools/byoc/provision.sh \
    --non-interactive --dry-run \
    --cloud=aws --account=arn:aws:iam::123:role/SpineBYOC \
    --region=us-east-1 --mode=ec2 \
    --hub-version=1.0.0 --bundle-id=00000000-0000-0000-0000-000000000000 \
    --admin-email=founder@startup.com \
    --credentials-ref=vault://kv/byoc/acct-123/aws_assume_role
```

YAML config form (same keys):

```yaml
# byoc-config.yaml
cloud: aws
account: arn:aws:iam::123:role/SpineBYOC
region: us-east-1
mode: ec2
hub_version: 1.0.0
bundle_id: 00000000-0000-0000-0000-000000000000
admin_email: founder@startup.com
credentials_ref: vault://kv/byoc/acct-123/aws_assume_role
```

```bash
tools/byoc/provision.sh --config=byoc-config.yaml --non-interactive --dry-run
```

## How this fits into v3

| When | What |
|---|---|
| Wave 5 (this PR) | `tools/byoc/` ships as scripts + runbooks. Vendor operators run them by hand. |
| Wave 5+ post-v1.0 | `devops/planes/infrastructure.py` (control plane) wraps `provision.sh` so the Spine `devops` role can invoke it via MCP. Per #11. |
| v1.1 | Air-gapped shape (#17) lands; Hostinger long-tail cloud (#20) added if demand surfaces. |

The dispatcher contract is intentionally process-boundary-friendly: when the devops control plane wraps it, the only changes are (a) it sets the env vars directly instead of CLI flags, (b) it streams stdout/stderr into the audit-chain writer, (c) it consults `spine_cloud.target` (V31 schema) for per-cloud capability flags.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Provision (or teardown) completed cleanly. |
| 1 | Generic failure. |
| 2 | Bad input (unknown flag, unknown cloud, missing required value). |
| 3 | Delegated-role validation failed — script aborted before any provisioning. |
| 4 | Cloud-API failure mid-flight (script attempted rollback of partially-created state if `--force` set). |
| 5 | Resource already exists, `--force` not given. |
| 6 | Unsupported (cloud / mode / region combination). |

## Validation

```bash
# Static checks the script ships with:
bash -n tools/byoc/provision.sh tools/byoc/clouds/*.sh
shellcheck -S error tools/byoc/provision.sh tools/byoc/clouds/*.sh

# Smoke (dry-run all 6 clouds; AI-driven):
for c in aws azure gcp railway fly do; do
  tools/byoc/provision.sh --non-interactive --dry-run \
    --cloud=$c --account=stub-acct \
    --hub-version=1.0.0 --bundle-id=00000000-0000-0000-0000-000000000000 \
    --admin-email=ops@example.com \
    --credentials-ref=vault://kv/byoc/stub/$c || echo "$c FAILED"
done
```

## References

- [`docs/V3_DESIGN_DECISIONS.md`](../../docs/V3_DESIGN_DECISIONS.md) §9, §11, §15, §17, §20, §21
- [`docs/V3_BUILD_SEQUENCE.md`](../../docs/V3_BUILD_SEQUENCE.md) Wave 5
- [`docs/DEPLOYMENT_SHAPES.md`](../../docs/DEPLOYMENT_SHAPES.md) — operational guide
- [`hub/wizard/init.sh`](../../hub/wizard/init.sh) — Day-0 wizard each cloud script invokes
- [`devops/planes/infrastructure.py`](../../devops/planes/infrastructure.py) — future programmatic caller (post-v1.0)
