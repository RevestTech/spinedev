# vault/ — Spine v3 secrets subsystem

> **Wave 0 deliverable** per `docs/V3_BUILD_SEQUENCE.md`. Implements decision
> #9 (Vault-only secrets, OpenBao Day-0 default) and #32 layer 8 (Vault
> unseal recovery) from `docs/V3_DESIGN_DECISIONS.md`.

## What this subsystem is

The `vault/` directory packages the **OpenBao container, its Day-0 init
wizard, the Shamir / KMS unseal configuration, and the DR runbook** —
everything needed to stand up the Spine secrets backend for any of the four
v1.0 deployment shapes (#17).

OpenBao is the **upstream OSS fork of HashiCorp Vault**. Spine ships it as
the wizard-installed default because (a) #9 mandates a free, source-available
secrets backend that customers can self-host, and (b) the HashiCorp BSL
license change makes Vault Enterprise unsuitable as a Day-0 bundled product.

### Image source switch (TODO)

The Dockerfile currently pins `openbao/openbao:2.1.1`. If at build time the
OpenBao registry coordinates have changed or the image is unavailable for
your architecture, swap to `hashicorp/vault:latest` in `Dockerfile` and
`docker-compose.yml`. The API and CLI are compatible — `bao` is the OpenBao
CLI but the `vault` CLI works against OpenBao for now. Track upstream
divergence and re-pin OpenBao when stable. This swap is documented as a known
fallback, not a recommended default.

## Boundaries

This subsystem owns:

- The Vault container image (`Dockerfile`)
- The laptop-shape compose file (`docker-compose.yml`)
- The Day-0 interactive init wizard (`init-wizard.sh`)
- The two least-privilege policies (`policies/spine-{hub,readonly}.hcl`)
- Unseal-mode runbooks for all four supported modes
  (`unseal/shamir-config.md`, `unseal/kms-config-{aws,azure,gcp}.md`)
- The vault-specific DR runbook (`dr-runbook.md`)
- A smoke test (`tests/test-vault-up.sh`)

This subsystem does NOT own:

| Concern | Owner |
|---|---|
| The Python adapter library that Hub + roles call to fetch secrets | `shared/secrets/` (Agent A) |
| Identity / OIDC (separate from secrets) | `keycloak/` (Agent E) + `shared/identity/` |
| Cross-subsystem DR orchestration | `recovery/` (Wave 5, Squad E) |
| Snapshot/restore tooling for the data volume | `recovery/` |
| Root `Makefile` integration | Wave 6 task |

## Deployment-shape matrix

Per decision #17, Spine v1.0 ships four deployment shapes. This subsystem
must work in all four.

| Shape | Unseal mode | Storage | Runbook |
|---|---|---|---|
| **Laptop** | Shamir (3-of-5) auto-captured at first run | local Docker volume, single-node Raft | `unseal/shamir-config.md` |
| **BYOC (vendor-managed in customer cloud)** | KMS auto-unseal (cloud follows account) | cloud block storage, single-node Raft | `unseal/kms-config-{aws,azure,gcp}.md` |
| **Self-hosted customer-cloud (EKS/AKS/GKE)** | KMS auto-unseal | PVC, 3-node Raft cluster | `unseal/kms-config-{aws,azure,gcp}.md` |
| **Self-hosted on-prem** | Shamir 3-of-5 (default) OR KMS if hybrid | local PV / SAN, 3-node Raft cluster | `unseal/shamir-config.md` (+ KMS if applicable) |
| *(v1.1)* Air-gapped | Shamir only | local PV, 3-node Raft cluster | `unseal/shamir-config.md` |

The `docker-compose.yml` here covers the **laptop** shape only. K8s charts
for the other three shapes are built in Wave 3 (`hub/` container + its
sibling charts).

## Contract with `shared/secrets/` (Agent A)

Agent A's `shared/secrets/` package is the cross-cutting Python library every
Spine subsystem imports to fetch a secret. It talks to **this container**
over HTTP.

| Contract item | Value |
|---|---|
| Default endpoint | `http://vault:8200` (compose network) / `http://127.0.0.1:8200` (host) |
| Override env var | `SPINE_VAULT_ADDR` (Hub side) — VaultAdapter reads this |
| KV mount path | `spine/` (KV v2) — wizard creates this |
| AppRole name | `spine-hub` — wizard creates with `spine-hub` policy attached |
| Hub auth env vars (issued by the wizard) | `SPINE_VAULT_ROLE_ID`, `SPINE_VAULT_SECRET_ID_WRAPPED` |
| Hub auth flow | VaultAdapter unwraps `SPINE_VAULT_SECRET_ID_WRAPPED` once via `sys/wrapping/unwrap`, logs in via `auth/approle/login`, caches the resulting client token (renews via `auth/token/renew-self` before TTL expires) |
| Read path | `spine/data/<key>` — KV v2 endpoint |
| Write path | `spine/data/<key>` — KV v2 endpoint |
| Audit / verify-class read role | `spine-readonly` (separate AppRole if Agent A needs read-only verify path) |

If Agent A needs additional AppRoles (e.g. per-project Spines with their own
scoped policies), the same wizard + policy pattern extends — add policy files
to `policies/`, extend the wizard's role-creation step (Wave 4 federation
work, not Wave 0).

## Quick start (laptop)

```bash
# 1. Start the container (no secrets needed)
docker compose -f vault/docker-compose.yml up -d

# 2. Run the Day-0 wizard (interactive)
./vault/init-wizard.sh

# 3. The wizard prints recovery keys ONCE and the Hub AppRole creds.
#    Capture them in your password manager / safe / KMS BEFORE pressing ENTER.

# 4. Verify
./vault/tests/test-vault-up.sh
```

For CI / scripted use:

```bash
./vault/init-wizard.sh --no-interactive --unseal=shamir --shares=5 --threshold=3 \
    --recovery-output=/secure/spine-init.json
```

## Files in this subsystem

```
vault/
├── Dockerfile                         # OpenBao image, multi-arch, non-root, healthcheck
├── docker-compose.yml                 # Laptop-shape compose (no secrets)
├── .env.example                       # Non-secret env template
├── .gitignore                         # Excludes .env*, recovery dumps
├── init-wizard.sh                     # Day-0 interactive init (Shamir or KMS)
├── README.md                          # This file
├── dr-runbook.md                      # Vault-specific DR procedures
├── policies/
│   ├── spine-hub.hcl                  # Hub least-privilege policy
│   └── spine-readonly.hcl             # Audit/compliance read-only policy
├── unseal/
│   ├── shamir-config.md               # Shamir 3-of-5 distribution best practices
│   ├── kms-config-aws.md              # AWS KMS auto-unseal setup
│   ├── kms-config-azure.md            # Azure Key Vault auto-unseal setup
│   └── kms-config-gcp.md              # GCP KMS auto-unseal setup
└── tests/
    └── test-vault-up.sh               # Smoke test: dev-mode up, write+read, teardown
```

## Security posture

- **No secrets in any committed file.** `.env`, recovery-key dumps, and any
  wizard output files are gitignored.
- **Image runs as non-root.** OpenBao upstream user `openbao` (uid 100).
- **mlock enabled** (`IPC_LOCK` capability granted) to prevent secret memory
  from being swapped to disk.
- **Recovery keys displayed once.** Wizard never writes them to disk unless
  the operator explicitly passes `--recovery-output=<path>`, in which case
  the file is `chmod 600` with a loud warning.
- **AppRole secret-id is wrapped** — single-use token to limit exposure
  window. TTL 300s.
- **Cite-or-Refuse compatible** — `spine-readonly` policy gives verify-class
  roles (#12) a path to PROVE a secret exists without leaking its value
  (via the `subkeys/` endpoint).

## Known limitations / Wave 0 scope

- Single-node Raft only in the laptop compose. Multi-node + HA topologies
  are documented in unseal runbooks but the production HCL templates ship
  with the k8s charts (Wave 3).
- TLS is disabled in the laptop compose (`tls_disable = true`). All other
  shapes MUST enable TLS — sample HCL in each `kms-config-*.md`.
- Snapshot/restore tooling lives in `recovery/` (Wave 5), not here. The DR
  runbook references it.
- The wizard's Hub-credential handoff is print-to-terminal. A future
  enhancement (post-v1.0) wires this directly into the Hub container's
  startup via a one-shot socket — out of scope for Wave 0.

## References

- Design: `docs/V3_DESIGN_DECISIONS.md` §9, §17, §32
- Build sequence: `docs/V3_BUILD_SEQUENCE.md` Wave 0 + Part 1.1
- OpenBao: <https://openbao.org>
- KV v2 spec: <https://openbao.org/docs/secrets/kv/kv-v2/>
- AppRole spec: <https://openbao.org/docs/auth/approle/>
