# Install Spine

> **Audience:** anyone standing up a Spine Hub for the first time.
>
> Drivers: [`docs/V3_DESIGN_DECISIONS.md`](docs/V3_DESIGN_DECISIONS.md) — **#3** (Hub-as-product), **#9** (Vault-only), **#15** (NOT SaaS), **#17** (4 deployment shapes), **#20** (5+ clouds), **#21** (ALL AI ALL THE TIME — every prompt is flaggable), **#25** (Keycloak embedded).

Spine ships a single containerized **Hub** that you run in one of four shapes (#17): laptop, vendor-managed BYOC, self-hosted customer-cloud, or self-hosted on-prem. Air-gapped lands in v1.1.

This guide walks all four. The Day-0 wizard is identical across shapes — only the infrastructure target changes.

---

## TL;DR — laptop in 60 seconds

```bash
bash install.sh ~/spine
cd ~/spine
make hub-up                 # docker compose up -d
open $(cat _state/hub_url)  # browser to your Hub
```

That brings up Vault (OpenBao) + Keycloak + Postgres + Hub on your machine. Login with the admin email + password the wizard wrote to vault.

---

## Prerequisites

| Shape | What you need |
|---|---|
| **Laptop** | Docker Desktop (or Docker Engine) ≥ 24, 8 GB RAM free, 20 GB disk, macOS / Linux / Windows-WSL2 |
| **BYOC** | A cloud account (AWS / Azure / GCP / Railway / Fly.io / DigitalOcean / Hostinger) with billing enabled. Spine vendor provisions the rest. |
| **Customer-cloud** | A Kubernetes cluster (EKS / AKS / GKE / on-prem K8s) with `kubectl` access, ≥ 3 worker nodes, persistent volume support, ingress controller. |
| **On-prem** | Vanilla K8s / OpenShift / Rancher, ≥ 3 worker nodes, persistent storage, internal CA for TLS, optional Shamir 3-of-5 quorum for vault unseal (#32 layer 8). |

All shapes require **outbound HTTPS** to at least one LLM provider (Anthropic / OpenAI / Bedrock / Vertex / Ollama-self-host / Qwen / vLLM-self-host — pick one as primary; #2). Air-gapped requires a self-hosted provider (Ollama or in-house vLLM).

---

## Shape 1 — Laptop

For: solo founder evaluation, individual developer, internal demo. Free tier license auto-generated (`hub/config/free_tier_flags.yaml`).

### Run

```bash
bash install.sh ~/spine
```

The installer:

1. Verifies Docker is on PATH and reachable
2. Clones / copies the Hub bundle into `~/spine`
3. Runs `vault/init-wizard.sh` (Day-0 OpenBao init — Shamir 3-of-5 or local KMS, your choice)
4. Runs `keycloak/init-bootstrap.sh` (Keycloak realm + spine-hub OIDC client + groups; auto-generates 32-char admin password and writes it into vault, never to disk)
5. Runs `hub/wizard/init.sh` (Hub bootstrap — see steps below)
6. Writes `~/spine/.env.local` (gitignored) with vault AppRole credentials for the Hub container
7. Writes `~/spine/_state/hub_id.txt` (UUIDv4) and `_state/wizard_manifest.json` (non-secret choices for audit)

Then:

```bash
cd ~/spine
make hub-up                      # docker compose -f hub/docker-compose.yml --env-file .env.local up -d
make hub-status                  # vault + keycloak + postgres + hub all healthy?
open $(cat _state/hub_url)       # default http://localhost:8090
```

To stop: `make hub-down`. State persists in Docker volumes (`vault_data`, `keycloak_db_data`, `spine_db_data`).

### What the wizard asks

`hub/wizard/init.sh` runs 7 steps (#3 + #21 — every step has a flag for AI-driven non-interactive runs):

| Step | Prompt | Flag | Default |
|---|---|---|---|
| 1 | Deployment shape | `--shape laptop\|byoc\|customer_cloud\|on_prem` | laptop |
| 2 | Vault adapter | `--vault openbao\|external-vault\|aws\|azure\|gcp` | openbao |
| 3 | Keycloak deployment | `--keycloak bundled\|external` | bundled |
| 4 | LLM provider | `--llm anthropic\|openai\|bedrock\|vertex\|ollama\|qwen\|vllm` | anthropic |
| 5 | Initial admin | `--admin-email <e> --admin-username <u>` (password generated, written to vault) | prompt |
| 6 | License bundle | `--license-bundle <path>` | free-tier auto-generated for laptop |
| 7 | Parent Hub | `--parent-hub <url>` | none (standalone) |

Output: `.env.local` + `_state/` + a banner with the Hub URL + admin email + first-login instructions. **No secret value is ever printed or logged.**

---

## Shape 2 — Vendor-Managed (BYOC)

For: solo founders and early mid-market who want to focus on product instead of ops. Spine vendor operates the Hub inside YOUR cloud account.

### Why BYOC is different (#17)

- The Hub runs in YOUR account — your billing, your data, your subpoena posture
- A scoped IAM role (provision-and-manage-Spine, nothing more) grants Spine vendor enough access to operate it
- You pay your cloud bill directly + a Spine management fee (~$50–200/mo, pricing deferred per #23)
- **Exit ramp:** revoke the role. The Hub keeps running. You take over ops self-hosted. No data migration. No lock-in.

### Run

1. Sign up at `https://spine.dev/byoc` (vendor portal — not a SaaS Hub, just the order form)
2. Pick your cloud:

| Cloud | Delegation mechanism |
|---|---|
| AWS | IAM role for cross-account assume (Spine vendor account `<vendor-aws-account-id>`) |
| Azure | Delegated Admin Privileges (DAP) via Microsoft Partner Center |
| GCP | Service account with `iam.serviceAccountAdmin` scoped to a single project |
| Railway | Team-invite the vendor's `spine-ops@` Railway account |
| Fly.io | Org-invite the vendor's `spine-ops@` Fly org |
| DigitalOcean | API token with project-scoped `read+write` |
| Hostinger | API key with project-scoped access (v1.1 long-tail support) |

3. The vendor runs `tools/byoc-provision.sh --cloud <cloud> --account <id> --region <region>` against YOUR account
4. Spine provisions: Hub container (on the cloud's managed compute) + OpenBao + Postgres + Keycloak + ingress + DNS + TLS
5. You receive a Hub URL + a Keycloak admin email invite

After provisioning, you operate the Hub via the Hub web UI exactly like the laptop shape. Vendor ops sees nothing inside your Hub — only infra-level metrics (CPU, memory, disk) needed to keep the lights on.

### To exit

```text
1. Vendor: detach the management role (`tools/byoc-detach.sh --account <id>`)
2. You: revoke the IAM role / DAP / service account / team invite
3. The Hub keeps running. You assume ops responsibility.
4. Optionally migrate to customer-cloud shape with `migration/export.py` + `migration/import_.py` (#33 B)
```

---

## Shape 3 — Self-hosted customer-cloud

For: mid-market and enterprise teams running on their own EKS / AKS / GKE.

### Run

```bash
# 1. Pull the Hub Helm chart (signed by vendor — verify with `cosign verify`)
helm repo add spine https://charts.spine.dev
helm repo update
cosign verify $(helm pull spine/hub --version 1.0.0 --untar=false)

# 2. Generate values.yaml from a template
helm show values spine/hub > values.yaml
# edit: ingress hostname, TLS cert source, storage class, license-bundle path, parent-hub URL

# 3. Install
helm install spine-hub spine/hub --namespace spine --create-namespace -f values.yaml

# 4. Run the Day-0 wizard inside the Hub pod
kubectl exec -n spine deploy/spine-hub -it -- /spine/hub/wizard/init.sh \
    --shape customer_cloud \
    --vault aws \
    --keycloak bundled \
    --llm anthropic \
    --admin-email admin@acme.com \
    --license-bundle /etc/spine/license.json
```

### Cloud-specific notes (#20)

| Cloud | K8s | Vault adapter | Storage | TLS |
|---|---|---|---|---|
| AWS EKS | EKS 1.28+ | `aws` (Secrets Manager) | gp3 EBS | ACM via ALB |
| Azure AKS | AKS 1.28+ | `azure` (Key Vault) | managed-csi | App Gateway + Key Vault cert |
| GCP GKE | GKE 1.28+ | `gcp` (Secret Manager) | pd-balanced | GCLB-managed cert |
| Self-managed | vanilla K8s 1.28+ | `external-vault` (HashiCorp Vault) | any CSI | cert-manager + Let's Encrypt or internal CA |

---

## Shape 4 — Self-hosted on-prem

For: regulated enterprise — banks, defense suppliers, healthcare, government.

### Run

```bash
# 1. Mirror the signed bundle into your internal artifact registry
oras pull ghcr.io/spine/hub:1.0.0
docker tag ghcr.io/spine/hub:1.0.0 internal-registry.acme.bank/spine/hub:1.0.0
docker push internal-registry.acme.bank/spine/hub:1.0.0

# 2. Verify the signed bundle against the published vendor fingerprint (#16 + #18)
cosign verify --certificate-identity-regexp '.*@spine.dev' \
              --certificate-oidc-issuer https://accounts.google.com \
              internal-registry.acme.bank/spine/hub:1.0.0

# 3. Run the wizard with on-prem flags
bash hub/wizard/init.sh \
    --shape on_prem \
    --vault external-vault \
    --vault-addr https://vault.internal.acme.bank \
    --keycloak external \
    --keycloak-url https://sso.acme.bank \
    --llm vllm \
    --llm-url https://llm-internal.acme.bank \
    --admin-email admin@acme.bank \
    --license-bundle /etc/spine/license.json \
    --shamir-quorum 3 \
    --shamir-shares 5
```

### Day-0 differences for on-prem

- **Vault unseal:** Shamir 3-of-5 (#32 layer 8) — 5 named humans receive shards offline; quorum-of-3 needed to unseal after any restart
- **Keycloak:** federate to existing Active Directory / LDAP / SAML IdP; embedded Keycloak runs as the OIDC broker
- **LLM:** in-house vLLM or Ollama serving local weights (no outbound calls)
- **Updates:** subscribe to vendor advisories via federation `update_cascade` (#16); approve each update through the Hub decision queue — auto-push is never an option
- **DR:** see `docs/DR_RUNBOOK.md` — 12-layer architecture, runbook auto-generated per deployment (#31, #32)

---

## After install — verify the Hub

Every shape exposes the same surfaces. After bring-up:

```bash
# Smoke
curl -k $(cat _state/hub_url)/healthz                    # green
curl -k $(cat _state/hub_url)/api/v2/spec                # OpenAPI 3.x JSON
curl -k -H "Authorization: Bearer $(spine token)" \
     $(cat _state/hub_url)/api/v2/projects               # [] initially

# Smoke via included helper
bash hub/tests/test-hub-up.sh --run                      # validation pass + actual probes

# Hub UI
open $(cat _state/hub_url)
# Login → Keycloak redirects → enter admin email + password from wizard
# Land on Decision Queue (empty Day 1) → click "New Project" → walks intake
```

If `healthz` is red: `make hub-logs` to inspect; `vault/init-wizard.sh --diagnose` and `keycloak/init-bootstrap.sh --diagnose` to surface what's wrong.

---

## Federation (optional — #4, #10, #16)

If you have multiple Hubs (per team / division / enterprise / corporate), register children under their parent:

```bash
# On the parent Hub (e.g., enterprise Hub)
spine federation invite --child-name "marketing-team" --output /tmp/marketing-invite.json

# On the child Hub
bash hub/wizard/init.sh --parent-hub https://hub.acme.com --invite /tmp/marketing-invite.json
```

After registration the parent pushes signed bundle updates (policy, role charters, integrations, license updates) down the tree; each tier requires admin approval (#16). The child sees aggregated reads pulled up; the parent never sees raw child data unless bundle policy explicitly mandates it.

Full federation guide: [`docs/FEDERATION_GUIDE.md`](docs/FEDERATION_GUIDE.md).

---

## Update path (#16)

Vendor publishes signed Hub releases via signed OCI artifact registry. Each Hub subscribes to either:

- **Direct vendor** (standalone / leaf Hub) — `update.upstream = vendor`
- **Parent Hub** (federated) — `update.upstream = <parent-hub-url>`

When a new release lands, the Hub decision queue surfaces a card with changelog + risk notes + rollout cadence. **Auto-push is never an option** — admin approves, defers, or rejects. Bundle policy may declare `auto_approve_security_patches: true` if you trust the vendor for sec-only patches.

Update process:

```bash
spine hub update --check                  # see what's pending
spine hub update --approve <release-id>   # roll forward; backup taken automatically
spine hub update --rollback               # revert to previous version (V20+ migrations are reversible)
```

---

## Uninstall

```bash
# Laptop
make hub-down
docker volume rm spine_vault_data spine_keycloak_db_data spine_db_data

# BYOC — revoke the IAM role; Spine vendor tears down on detach
# Customer-cloud — helm uninstall spine-hub --namespace spine
# On-prem — same as customer-cloud
```

**Before you nuke:** export your state for portability (#33 B) so you can re-import elsewhere or keep the audit trail:

```bash
spine export --output spine-backup-$(date +%Y%m%d).tar.zst
# Tarball is integrity-verified; round-trippable via `spine import` on any new Hub
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `docker compose` fails on `${FOO:?msg}` | `.env.local` missing — re-run `hub/wizard/init.sh`. Per #9 we refuse to start without vault credentials. |
| Vault unseal hangs | Shamir quorum not met — check `vault/dr-runbook.md` § "Unseal stuck"; KMS mode: verify cloud KMS key ID is correct |
| Keycloak admin login fails | Password is in vault — `vault kv get spine/keycloak/admin_password`. Don't reset; rotate via `keycloak/init-bootstrap.sh --rotate-admin` |
| Hub UI shows "License not verified" | Bundle expired or signature mismatch — see [`docs/LICENSING_GUIDE.md`](docs/LICENSING_GUIDE.md) § "Bundle verification failures" |
| Federation registration fails | Mutual TLS — verify both Hubs trust each other's CA; check `federation/upstream_client.py` logs in Hub |
| Decision-card notifications not arriving | Slack / email / SMS creds in vault correct? See [`docs/HUB_OPERATIONS_GUIDE.md`](docs/HUB_OPERATIONS_GUIDE.md) § "Comm channels" |
| `spine` CLI command not found | The CLI is a power-user tool. `pip install spine-cli` OR run via `docker run --rm spine/cli <cmd>` |

For everything else: `docs/HUB_OPERATIONS_GUIDE.md` covers day-2 ops, `docs/SECURITY_GUIDE.md` covers posture review, `docs/DR_RUNBOOK.md` covers recovery, `docs/FEDERATION_GUIDE.md` covers multi-Hub setup, `docs/LICENSING_GUIDE.md` covers feature flags + quotas.

---

## What's NOT supported on Day 1

Per #17 + the deferred-items table in `docs/V3_DESIGN_DECISIONS.md`:

- **Air-gapped deployment** — v1.1
- **Native mobile apps** — v1.1 (mobile-responsive Hub UI works today; #28)
- **Voice/phone flows** — v1.1 (Twilio scaffold present; #29)
- **Long-tail clouds** beyond AWS / Azure / GCP / Railway / Fly — v1.1+ on demand (#20)
- **Active-active multi-cloud failover** — v1.1+ (active-passive cross-region works today; #32 layer 7)

These are scaffolded so their absence isn't structural rework — only deferred surface.
