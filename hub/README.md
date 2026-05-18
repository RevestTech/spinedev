# `hub/` — Spine v3 containerized product

> **Status:** Wave 3 Squad B skeleton (per `docs/V3_BUILD_SEQUENCE.md`).
> Decision drivers: **#3** (Hub-as-product), **#17** (4 deployment shapes),
> **#25** (Keycloak embedded), **#14** (3 segments), **#9** (Vault-only),
> **#23** (feature-flag licensing).

`hub/` is the **primary management surface** of Spine — a single
containerized product that customers run in one of four deployment shapes
and that bundles everything needed to manage a Spine federation: vault,
identity, Postgres, schema migrations, the FastAPI app, and the Day-0
bootstrap wizard. Per decision **#3**, the v1 framing ("drop Spine into your
project as a template") is wrong; v3 makes the Hub the front door and the
CLI a power-user tool.

This README documents what the subsystem ships, how it composes with sister
subsystems (`vault/`, `keycloak/`, `shared/api/`, `shared/secrets/`,
`shared/identity/`, `shared/runtime/`), and how each of the four deployment
shapes consumes it.

---

## What this directory contains

| Path | Purpose |
|---|---|
| `Dockerfile` | Multi-arch (amd64+arm64) Python 3.11 + uvicorn image; non-root user `spine`; healthcheck via `healthcheck.sh`. |
| `docker-compose.yml` | Laptop-shape compose: hub + bundled vault (OpenBao) + bundled keycloak (+ its own postgres) + spine postgres + flyway migrator. Shared `spine` bridge network so each service can talk by name. |
| `entrypoint.sh` | Container PID-1 (under `tini`): wait-for-vault, wait-for-postgres, wait-for-keycloak, optional flyway run, bootstrap secrets adapter, exec `uvicorn shared.api.app:create_app --factory`. |
| `healthcheck.sh` | Curl-based `/healthz` probe referenced by Dockerfile HEALTHCHECK. Exit codes documented in the file. |
| `__init__.py` / `main.py` | Tiny Python surface; `main.py` is the ASGI entry point (`uvicorn hub.main:app`) and is a thin wrapper over `shared.api.app.create_app`. |
| `config/default_bundle.yaml` | Day-0 default org bundle: vault adapter, Keycloak realm/client, license tier `free`, comm prefs (web+email), feature flags all OFF except free-tier ON-set, federation `parent_hub: null`. |
| `config/free_tier_flags.yaml` | The small ON-set the free tier turns on above the all-OFF baseline. |
| `wizard/init.sh` | Day-0 bootstrap wizard. Interactive by default; fully non-interactive via flags (per #21 ALL-AI). |
| `tests/test-hub-up.sh` | Smoke test. Validation pass runs by default; `--run` opts in to actual docker compose spin-up + `/healthz` + `/api/v2/spec` + `/api/v2/projects` probes. |
| `_state/` | Created at wizard time. Contains `hub_id.txt` + `wizard_manifest.json`. Git-ignored. |

---

## How it relates to `shared/api/`

Wave 3 Squad B (this squad) does **not** define a Hub-specific FastAPI
factory. Per the build sequence:

> Hub uses the shared FastAPI factory; Wave 3 Squad C extends `shared/api/`
> with new routes.

`hub/main.py` is therefore a four-line wrapper:

```python
from shared.api.app import create_app as _shared_create_app
def create_app(): return _shared_create_app()
app = create_app()
```

This keeps the Hub container, the CLI, and federated Spines all running the
same code paths. When Squad C lands new routes (`decisions`, `role_chat`,
`registry`, `vault_config`, `integrations`, `federation`, `license`) and new
middleware (OIDC via Keycloak, feature-flag enforcement), the Hub picks them
up automatically — no edits to `hub/` required.

---

## Deployment-shape matrix (per #17)

| Shape | Operator | Runs on | Compose / chart | Vault | Keycloak |
|---|---|---|---|---|---|
| **laptop** | Customer | Customer's laptop (Docker Desktop / Podman) | `hub/docker-compose.yml` | bundled OpenBao | bundled |
| **byoc** (Vendor-Managed) | Spine company (delegated role) | Customer's cloud (AWS/Azure/GCP/Railway/Fly/DO) | k8s chart (Wave 4 Squad A — `devops/planes/*`) | Customer's cloud KMS or external Vault | bundled or external |
| **customer-cloud** | Customer | Customer's EKS/AKS/GKE | k8s chart (`devops/planes/*`) | External Vault or KMS adapter | external (federate into Keycloak) |
| **on-prem** | Customer | Customer datacenter (vanilla k8s / OpenShift / Rancher) | k8s chart (`devops/planes/*`) | External Vault | external |
| *(v1.1)* air-gapped | Customer | Air-gapped infra | k8s chart (offline-bundle variant) | External Vault | bundled (no IdP federation) |

`hub/docker-compose.yml` covers the **laptop** shape only. The other three
shapes share the same Dockerfile (multi-arch) but their compose / chart
lives under `devops/planes/*` (Wave 4 Squad A). All four shapes use the
same `entrypoint.sh` + `healthcheck.sh` — only the surrounding orchestration
differs.

---

## Day-0 wizard flow

`hub/wizard/init.sh` runs **once per deployment**. Steps (all non-interactive
via flags per #21):

1. **Detect deployment shape** — auto-detect (`KUBERNETES_SERVICE_HOST` →
   `customer_cloud`) or prompt; explicit `--deployment-shape=`.
2. **Pick vault adapter** — `openbao | external-vault | aws | azure | gcp`.
   Sensible defaults per shape (`laptop → openbao`, `byoc → aws`,
   `customer-cloud / on-prem → external-vault`).
3. **Pick keycloak deployment** — `bundled | external`.
4. **Pick LLM provider** — `anthropic | openai | bedrock | vertex | ollama
   | qwen | vllm` (per #2 LLM-agnostic). Sets the primary; the others stay
   `enabled: false` in the bundle until configured.
5. **Bootstrap initial admin** — `--admin-email` required; password EITHER
   generated and displayed ONCE in the final banner OR resolved from
   `--admin-password-from-vault-path=spine/data/keycloak/bootstrap-admin`
   (the AI-driven path; never echoes a secret).
6. **Write `hub_id`** — UUIDv4 (or `--hub-id=`) to `hub/_state/hub_id.txt`;
   recorded in `wizard_manifest.json`; intended to be inserted into
   `spine_federation.hub` on first DB connect (Wave 4 federation work
   completes that round-trip).
7. **Print banner** — Hub URL + admin login + generated password (once).

Outputs:

- `.env.local` (repo root, mode 600) — env file for docker-compose.
  Per #9, **no secret VALUES** here — only non-secret hints and
  `__SET_ME_FROM_VAULT_*__` placeholders for the operator to populate
  via a vault injector (sealed secrets / SSM / etc.). The compose file's
  `${FOO:?msg}` syntax fails loudly if any required env is still a
  placeholder.
- `hub/_state/wizard_manifest.json` (mode 600) — non-secret audit record
  of choices.

Example AI-driven invocation:

```bash
./hub/wizard/init.sh \
  --non-interactive \
  --deployment-shape=laptop \
  --vault-adapter=openbao \
  --keycloak=bundled \
  --llm-provider=anthropic \
  --admin-email=ops@example.com \
  --admin-password-from-vault-path=spine/data/keycloak/bootstrap-admin
```

---

## Cross-subsystem contracts

| Contract | How it flows |
|---|---|
| `vault://` paths | The bundle (`config/default_bundle.yaml`) names paths like `spine/data/keycloak/spine-hub/client-secret`. `shared/secrets/get_secret(path)` resolves them via the adapter installed by `entrypoint.sh`. **Hub code never reads env for secret VALUES** (#9). |
| `keycloak://` (OIDC) | `default_bundle.yaml.identity.keycloak.issuer_url_hint` documents the issuer; `shared/identity/keycloak_client.py` (already shipped in Wave 0) consumes `SPINE_KEYCLOAK_URL` + realm + client_id from env to bind the OIDC client. Hub never handles SAML/SCIM directly — Keycloak does. |
| `hub_id` registration | Wizard writes `hub/_state/hub_id.txt`. On first Hub start, the federation subsystem (Wave 4 Squad A) reads it and registers the hub in `spine_federation.hub`. Until Wave 4 lands, the value is captured but unused. |
| `entrypoint → uvicorn` | The bootstrap step installs the secrets adapter into the process via `shared.secrets.set_default_adapter(...)` BEFORE `uvicorn` imports `shared.api.app`, so the FastAPI factory finds a wired-up backend when it runs lifespan. |
| `flyway → spine_*` schemas | The compose's `flyway` service runs `db/flyway/sql/V22..V32` against the spine database before `hub` starts. Hub depends on `flyway:condition=service_completed_successfully`. |

---

## Runtime dependencies

Pinned in `Dockerfile` (do not modify `pyproject.toml` per scope):

| Package | Version | Why |
|---|---|---|
| `fastapi` | `0.115.0` | Shared API factory. |
| `uvicorn[standard]` | `0.30.6` | ASGI server. |
| `pydantic` | `2.9.2` | Already required by `shared/`. |
| `asyncpg` | `0.29.0` | Wave 3 swap from subprocess psql (Squad C). |
| `httpx` | `0.27.2` | OIDC discovery + JWKS fetch. |
| `PyYAML` | `6.0.2` | Bundle parsing. |
| `PyJWT[crypto]` | `2.9.0` | Keycloak JWT verification. |
| `cryptography` | `43.0.1` | Backs `PyJWT[crypto]` + Ed25519 license signature verification (#23). |

System deps: `libpq5`, `curl`, `jq`, `ca-certificates`, `tini`.

---

## Smoke validation

The agent brief's validation block, what it does, and the expected result:

```bash
# Bash syntax
bash -n hub/entrypoint.sh hub/wizard/init.sh hub/healthcheck.sh hub/tests/test-hub-up.sh

# Python compiles
python3 -m py_compile hub/__init__.py hub/main.py

# YAML configs parse
python3 -c "import yaml; [yaml.safe_load(open(f)) for f in ['hub/config/default_bundle.yaml','hub/config/free_tier_flags.yaml']]"

# Compose syntax (the required-env $VAR:?msg pattern fails on purpose
# without an env file — that's the validation behavior, not an error).
docker compose -f hub/docker-compose.yml config --quiet 2>&1 \
  || echo 'compose missing required env at validation time (expected — no secrets in committed compose)'
```

The smoke test (`hub/tests/test-hub-up.sh`) wraps these into a single
exit-coded run. By default it runs the **validation pass only**; pass
`--run` to opt in to actually spinning up the compose stack.

---

## Wave 3 part 2 (SPA panels) follow-ups

Wave 3's larger scope (per `V3_BUILD_SEQUENCE.md`) includes the 10-panel Hub
SPA. Squad B (this squad) ships the container skeleton; the SPA is Squad
C+D's work. Files we anticipate but do **not** ship here:

- `shared/ui/dashboard/panels/{decision-queue,master-roles,registry,audit,vault-config,integrations,role-chat,federation,license,kg-search}.js`
- `shared/ui/dashboard/responsive.css`
- `shared/ui/login/index.html` (OIDC redirect entry)
- `shared/api/routes/{decisions,role_chat,registry,vault_config,integrations,federation,license}.py`
- `shared/api/middleware/{oidc.py,feature_flag.py}`

Once those land, the Hub container picks them up via `shared/api/` without
any change to `hub/main.py`. The `hub/docker-compose.yml` may add a
`spine-spa` static-asset sidecar in a Wave 3 part-2 iteration (TBD by Squad
C+D).

---

## Wave 4 follow-ups (federation client wiring)

The Day-0 wizard captures `hub_id` and `parent_hub_url`, but the **actual
federation registration** (mTLS upstream client, consent records, update
cascade subscription) is Wave 4 Squad A's work. Wave 4 will add:

- `federation/hub_registry.py` — DB row in `spine_federation.hub` keyed on
  the value in `hub/_state/hub_id.txt`.
- `federation/upstream_client.py` — mTLS + bearer-token client used by this
  Hub to call its parent (when `parent_hub` is non-null in the bundle).
- A new compose-time env hint `SPINE_FEDERATION_PARENT_HUB` (already
  reserved in `docker-compose.yml`) becomes load-bearing.

Until Wave 4 ships, the wizard's federation outputs are captured and inert
— a root Hub works fully, a child Hub does not yet receive cascaded
updates.

---

## Independent decisions taken by this squad

These were not explicitly directed and could be revisited:

1. **`tini` as PID 1**. Picked over `uvicorn --workers=N`-handles-signals
   because `tini` is the standard idiom for proper zombie reaping and
   forwards SIGTERM cleanly to a single worker. Worker count is an
   operational tuning decision belonging to the chart, not the image.
2. **Builder + runtime two-stage Dockerfile** rather than single-stage.
   Cuts ~250 MB by leaving `build-essential` + `libpq-dev` out of the
   runtime layer.
3. **`flyway` as a sibling compose service** rather than baking flyway
   into the Hub image. Keeps the Hub image small and lets k8s users run
   flyway as a `Job` of their choosing.
4. **`pgvector/pgvector:pg16` for spine_pg** in the laptop compose, so KG
   + memory features in later waves don't need a separate image swap.
5. **`SPINE_HUB_DEV=1` → InMemoryAdapter** is a hard branch in
   `entrypoint.sh`. In production we fail loudly if the adapter is
   missing — never silently fall back to env-var secrets (per #9).
6. **`.env.local` in repo root** (not `hub/.env.local`) so the same env
   file works with `vault/docker-compose.yml` and
   `keycloak/docker-compose.yml` when an operator runs them separately
   for dev. Repo `.gitignore` already excludes `.env.local`.
7. **Default exposed Hub host port = 8090** (not 8080). 8080 is occupied
   by Keycloak's user-facing port in the laptop compose; moving Hub to
   8090 avoids the conflict and keeps Keycloak's port stable for
   bookmarked admin URLs.
