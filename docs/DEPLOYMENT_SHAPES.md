# Deployment Shapes

> Spine runs in **4 deployment shapes Day 1** (#17) across **5+ cloud providers Day 1** (#20). This doc is the per-shape × per-cloud operational matrix. Drivers: [`V3_DESIGN_DECISIONS.md`](V3_DESIGN_DECISIONS.md) — **#15** (NOT SaaS), **#17** (4 shapes), **#20** (5+ clouds Day 1), **#32 layer 8** (vault unseal recovery), **#33 B** (Spine portability).

---

## TL;DR

| Shape | Operator | Where it runs | Tier | Day 1? |
|---|---|---|---|---|
| **Laptop** | You | Your machine (Docker Desktop / Engine) | Free | ✅ |
| **Vendor-Managed (BYOC)** | Spine vendor via delegated IAM role | Your cloud account | Founder | ✅ |
| **Self-hosted customer-cloud** | You | Your EKS / AKS / GKE / vanilla K8s | Team / Enterprise | ✅ |
| **Self-hosted on-prem** | You | Your datacenter (K8s / OpenShift / Rancher) | Enterprise | ✅ |
| **Air-gapped** | You | Your air-gapped infra | Defense / classified | ⏸ v1.1 |

Same Hub container in every shape. Different infrastructure target. Different operational model. Same audit trail. **Spine is NOT SaaS at any tier** (#15).

---

## Shape 1 — Laptop

### Who it's for
Solo founder evaluating Spine. Individual developer on a personal project. Internal demos. Free tier (`hub/config/free_tier_flags.yaml`).

### What runs where
Docker Desktop (or Docker Engine) on macOS / Linux / Windows-WSL2. Single host runs Vault (OpenBao) + Keycloak (+ its own Postgres) + Spine Postgres + Hub via `hub/docker-compose.yml`.

### Bring up
```bash
bash install.sh ~/spine
cd ~/spine && make hub-up
open $(cat _state/hub_url)            # default http://localhost:8090
```

### Operational characteristics
- **Vault:** OpenBao bundled. Unseal mode = local file (laptop convenience; KMS not needed). Recovery keys printed once at Day-0 — save offline immediately.
- **Identity:** Keycloak Free tier — single realm, username+password only, no MFA enforced. Per `keycloak/tier-config.md`.
- **LLM:** outbound to your chosen provider (`shared/llm/`); your API key in vault.
- **DR:** local backups to `~/spine/backups/` by default; weekly DR test runs via `tools/dr-test.sh` if cron is enabled.
- **No federation** (Hub is standalone unless you `--parent-hub <url>`).
- **Updates:** subscribes direct to vendor; admin (you) approves each release in Decision Queue.

### Resource footprint
~8 GB RAM at idle; ~20 GB disk. Add ~4 GB headroom for any LLM you run locally (Ollama).

### Wind down
```bash
make hub-down                         # stops containers; state persists in Docker volumes
docker volume rm spine_vault_data spine_keycloak_db_data spine_db_data  # nuke
```

---

## Shape 2 — Vendor-Managed (BYOC)

### Who it's for
Solo founders and early mid-market who want to **focus on product**, not ops. Spine vendor operates the Hub **inside your cloud account**. You pay your cloud bill directly plus a Spine management fee (~$50–200/mo, pricing deferred per #23).

### What runs where
Your AWS / Azure / GCP / Railway / Fly.io / DigitalOcean / Hostinger account. Spine vendor's automation provisions Hub + OpenBao + Postgres + Keycloak + ingress + DNS + TLS. Vendor ops sees infra-level metrics (CPU / memory / disk) needed to keep lights on; **vendor never sees Hub contents** (your code, your decisions, your audit chain).

### BYOC delegation mechanism (per cloud)

| Cloud | Mechanism | What you grant |
|---|---|---|
| **AWS** | Cross-account IAM role | `sts:AssumeRole` from vendor account `<vendor-aws-account-id>`. Role permissions scoped to: provision EC2 / EKS / RDS / Secrets Manager / Route 53 / ACM. Read-only on costs. |
| **Azure** | Delegated Admin Privileges (DAP) via Microsoft Partner Center | Vendor's CSP partner ID gets scoped admin on a single subscription. |
| **GCP** | Service account + IAM | Service account `spine-ops@vendor.iam.gserviceaccount.com` granted `iam.serviceAccountAdmin` scoped to a single project. |
| **Railway** | Team invite | Vendor's `spine-ops@` Railway account invited to your team with `Admin` on a single project. |
| **Fly.io** | Org invite | Vendor's `spine-ops@` Fly org granted access to a single org. |
| **DigitalOcean** | API token | Project-scoped read+write API token. |
| **Hostinger** | API key | Project-scoped access (long-tail; v1.1 stabilizing). |

### Bring up
1. Sign up at `https://spine.dev/byoc` (vendor portal — order form, NOT a SaaS Hub).
2. Pick cloud + region.
3. Grant the delegation mechanism above.
4. Vendor runs `tools/byoc-provision.sh --cloud <c> --account <id> --region <r>` against your account.
5. You receive: Hub URL + Keycloak admin email invite + signed bundle for your tier.

### Exit ramp (key feature for "no lock-in")
```text
1. Vendor: tools/byoc-detach.sh --account <id>   (vendor detaches management role)
2. You: revoke IAM role / DAP / service account / team invite / API token
3. The Hub keeps running. You assume ops responsibility.
4. Optionally migrate to customer-cloud shape:
   spine export --output spine-state.tar.zst
   # Provision K8s yourself; helm install spine/hub; spine import spine-state.tar.zst
```

**The deployment doesn't move.** No data migration. No lock-in. This is the operational proof of the "Spine doesn't hold your data" claim (#15).

### Operational characteristics
- **Vault:** cloud-native by default (AWS Secrets Manager / Azure Key Vault / GCP Secret Manager); operator can pick OpenBao bundled instead.
- **Identity:** Keycloak Founder tier — MFA optional, single IdP federation allowed, social login on.
- **LLM:** vendor configures whichever provider you specify; key lives in your vault.
- **DR:** cross-region active-passive optional per bundle (off by default at Founder tier; pay-to-add).
- **Federation:** standalone by default; you can register under a parent Hub if you have one.
- **Updates:** vendor handles infra-level patches; product updates surface as Decision Queue cards (you still approve).

---

## Shape 3 — Self-hosted customer-cloud

### Who it's for
Mid-market and enterprise teams running on their own K8s.

### Supported K8s targets

| Cloud | K8s | Vault adapter (#9) | Storage | TLS |
|---|---|---|---|---|
| **AWS EKS** | EKS 1.28+ | `aws` (Secrets Manager) | gp3 EBS | ACM via ALB |
| **Azure AKS** | AKS 1.28+ | `azure` (Key Vault) | `managed-csi` | App Gateway + Key Vault cert |
| **GCP GKE** | GKE 1.28+ | `gcp` (Secret Manager) | `pd-balanced` | GCLB-managed cert |
| **Self-managed K8s** | vanilla K8s 1.28+ | `external-vault` (HashiCorp Vault) | any CSI | cert-manager + Let's Encrypt or internal CA |

### Bring up
```bash
# 1. Add the signed Helm repo + verify
helm repo add spine https://charts.spine.dev
helm repo update
cosign verify $(helm pull spine/hub --version 1.0.0 --untar=false)

# 2. Template values.yaml
helm show values spine/hub > values.yaml
# edit: ingress hostname, TLS cert source, storage class, license-bundle path, parent-hub URL

# 3. Install
helm install spine-hub spine/hub \
    --namespace spine --create-namespace \
    -f values.yaml

# 4. Run Day-0 wizard inside the Hub pod
kubectl exec -n spine deploy/spine-hub -it -- /spine/hub/wizard/init.sh \
    --shape customer_cloud \
    --vault aws \
    --keycloak bundled \
    --llm anthropic \
    --admin-email admin@acme.com \
    --license-bundle /etc/spine/license.json
```

### Operational characteristics
- **Vault:** cloud-native adapter by default; HashiCorp Vault for hybrid.
- **Identity:** Keycloak Team tier — MFA required, multi-IdP federation, basic SCIM.
- **LLM:** any of 7 providers (#2); rate-limit + cost ledger enforce per-team budgets.
- **DR:** cross-region active-passive optional; recommended for Team+ workloads.
- **Federation:** typical — register child Hubs for sub-teams under a single Team Hub.
- **Updates:** Decision Queue + per-tier approval cascade (#16).

---

## Shape 4 — Self-hosted on-prem

### Who it's for
Regulated enterprise — banks, defense suppliers, healthcare, government.

### Supported targets
- Vanilla Kubernetes ≥ 1.28
- Red Hat OpenShift ≥ 4.14
- SUSE Rancher
- Air-gapped (v1.1; see § Air-gapped below)

### Bring up
```bash
# 1. Mirror signed image into internal artifact registry
oras pull ghcr.io/spine/hub:1.0.0
docker tag ghcr.io/spine/hub:1.0.0 internal-registry.acme.bank/spine/hub:1.0.0
docker push internal-registry.acme.bank/spine/hub:1.0.0

# 2. Verify signature (#16 + #18 — must trust the bundle before deploying)
cosign verify \
    --certificate-identity-regexp '.*@spine.dev' \
    --certificate-oidc-issuer https://accounts.google.com \
    internal-registry.acme.bank/spine/hub:1.0.0

# 3. Wizard with on-prem flags
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

### Operational characteristics
- **Vault:** customer's existing HashiCorp Vault. Shamir 3-of-5 unseal (#32 layer 8) across 5 named human officers.
- **Identity:** Keycloak Enterprise tier — full SCIM 2.0, multi-realm, advanced password policy, custom themes, admin event export, WebAuthn / passkey, step-up auth.
- **LLM:** in-house vLLM or Ollama serving local weights (no outbound calls).
- **DR:** cross-region active-passive (mandatory at this tier in most bundles); weekly DR test enforced; per-release backup verification (DR layer 12).
- **Federation:** typical — corporate Hub at root, division Hubs under, team Hubs under. Bounded mandatory upward flows for compliance (#10).
- **Updates:** subscribed to vendor advisories via federation `update_cascade`; per-tier admin approval (#16); auto-push forbidden by bundle policy.
- **Cite-or-Refuse (#12):** strict tier enforced on all verify-class roles. Refusal is itself an audit event.

---

## Air-gapped — v1.1 (deferred)

Per #17, air-gapped lands in v1.1. When it ships:

- Hub image + Helm chart + signed bundle imported via media (USB / tape) into the air-gapped network
- All LLM calls go to in-house vLLM or Ollama serving local weights
- No outbound network calls of any kind — vendor advisories pulled in via the same media import channel
- Updates: vendor publishes signed bundle to a public mirror; customer's secure courier imports

Until v1.1: customers with air-gapped requirements should engage Spine vendor design-partner program (see [`positioning.md`](positioning.md) on enterprise tier).

---

## Cloud breadth Day 1 (#20)

5+ providers Day 1:

| Cloud | BYOC | Customer-cloud | Provider catalog (V31) |
|---|:---:|:---:|---|
| **AWS** | ✅ | ✅ EKS | `cloud:aws` |
| **Azure** | ✅ | ✅ AKS | `cloud:azure` |
| **GCP** | ✅ | ✅ GKE | `cloud:gcp` |
| **Railway** | ✅ | — | `cloud:railway` |
| **Fly.io** | ✅ (Part 4.2 — chosen as 5th) | — | `cloud:fly` |
| **DigitalOcean** | ✅ (alt to Fly per Part 4.2) | — | `cloud:do` |
| **Hostinger** | ⚠️ stabilizing | — | `cloud:hostinger` (long-tail) |

Long-tail providers (Linode, Vercel, etc.) → v1.1+ on customer demand per #20.

Each cloud target is recorded in `spine_cloud.target` (V31) with per-cloud capability flags — does this cloud support managed K8s? managed Postgres? KMS for vault auto-unseal? cross-region replication? — so the Hub UI can offer the right options for the right cloud.

---

## Per-shape × per-cloud capability matrix

| Capability | Laptop | BYOC-AWS | BYOC-Azure | BYOC-GCP | BYOC-Railway | BYOC-Fly | BYOC-DO | Cust-cloud-EKS | Cust-cloud-AKS | Cust-cloud-GKE | On-prem |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Vault auto-unseal (#32 L8) | local | KMS | KV | KMS | local | local | local | KMS | KV | KMS | Shamir or KMS |
| Keycloak federation | ❌ free tier | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ✅ | ✅ | ✅ | ✅ full SCIM |
| Cross-region DR (#32 L7) | ❌ | opt-in | opt-in | opt-in | ❌ | ❌ | ❌ | opt-in | opt-in | opt-in | recommended |
| In-house LLM | ✅ Ollama | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ✅ | ✅ | ✅ | required |
| MFA enforced | optional | optional | optional | optional | optional | optional | optional | required | required | required | required + WebAuthn |
| Federation parent/child | optional | optional | optional | optional | optional | optional | optional | typical | typical | typical | mandatory at tier |
| Workspace hygiene Conductor gate (#34) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Audit-chain push to Vanta/Drata (#24) | manual | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ✅ | ✅ | ✅ | ✅ + GRC integration |
| OpenAPI v2 (#30) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

`⚠️` = supported but with caveats (typically: cloud doesn't offer a managed equivalent so the Hub provisions its own).

---

## Switching shapes (migration B per #33)

Spine portability is **build-properly Day 1** — non-negotiable for the "no lock-in" claim.

```bash
# Export full state from source Hub
spine export --output spine-state-$(date +%Y%m%d).tar.zst

# Tarball is signed + integrity-verified; round-trippable via spine import

# Stand up fresh Hub in target shape (run installer there)
# Then:
spine import --input spine-state-20260518.tar.zst
# Audit-chain verified, KG reproduced, identical decision history
```

What gets exported: audit chain + KG + role charters + bundle config + vault references (NOT values — those re-pull from new vault) + memory + lessons + project history + license bundle. What does NOT export: secret values, ephemeral state, container-local cache.

Export format spec is **public** and **demonstrably round-trippable** — sample export downloads available at `docs/sample-exports/` (deferred to Wave 6).

---

## Related artifacts

- [`INSTALL.md`](../INSTALL.md) — Day-0 install across all 4 shapes
- [`docs/HUB_OPERATIONS_GUIDE.md`](HUB_OPERATIONS_GUIDE.md) — day-2 ops
- [`docs/FEDERATION_GUIDE.md`](FEDERATION_GUIDE.md) — multi-Hub setup
- [`docs/DR_RUNBOOK.md`](DR_RUNBOOK.md) — DR per layer + per shape
- [`docs/SECURITY_GUIDE.md`](SECURITY_GUIDE.md) — vault + identity per shape
- [`hub/README.md`](../hub/README.md) — Hub container internals
- [`vault/README.md`](../vault/README.md) — vault per shape
- [`keycloak/tier-config.md`](../keycloak/tier-config.md) — Keycloak per tier
