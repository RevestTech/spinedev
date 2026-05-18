# `shared/secrets/` — Vault-only secret access for Spine v3

> **Status:** Wave 0 — BUILD-NEW (this package). Every Wave 1+ feature
> that touches a secret depends on this surface.
>
> **Design driver:** [`docs/V3_DESIGN_DECISIONS.md` #9 — Vault-only secrets,
> no exceptions, OpenBao Day-0 default](../../docs/V3_DESIGN_DECISIONS.md).
> Closed-source posture per #18 means a vault leak becomes a customer
> incident with no community-side mitigation; the rule is therefore
> stricter than typical OSS hygiene.

## What this package is

A vendor-agnostic adapter library for vault-class secret stores. Every
Spine code path that needs a secret value imports from here. There is
**no fallback to environment variables, no built-in secret store, no
on-disk cache, no return-to-env shortcut**.

## What this package is NOT

* It is **not** the OpenBao container or its init wizard — that lives
  at top-level `vault/` (created in Wave 0, separate squad).
* It is **not** a place to stash configuration values that happen to
  be sensitive-looking. If the value isn't a secret payload, route it
  through `shared/standards/` (bundle config) instead.
* It is **not** a replacement for the bootstrap flow that fetches the
  initial Vault token. Whoever constructs the adapter is responsible
  for the boot-time auth handshake (Kubernetes service account,
  AppRole, OIDC, manual unseal — varies per deployment shape).

## Public API

```python
from shared.secrets import (
    # Module-level convenience
    get_secret,           # async (path: str) -> str
    put_secret,           # async (path: str, value: str) -> None
    delete_secret,        # async (path: str) -> None
    list_secrets,         # async (prefix: str = "") -> list[str]
    set_default_adapter,  # (adapter: SecretAdapter | None) -> None
    get_default_adapter,  # () -> SecretAdapter

    # Types
    SecretAdapter, SecretRef,

    # Exceptions
    SecretNotFound, SecretAccessDenied, SecretBackendError,

    # Concrete adapters
    VaultAdapter,
    AWSSecretsManagerAdapter,
    AzureKeyVaultAdapter,
    GCPSecretManagerAdapter,
    CachedAdapter,
)
```

All adapter methods and module-level functions are **async**.

### Typical wizard bootstrap

```python
from shared.secrets import CachedAdapter, VaultAdapter, set_default_adapter

adapter = CachedAdapter(
    VaultAdapter(
        url="https://vault.spine.local:8200",
        token=bootstrap_token,   # sourced via wrapped-secret / k8s SA / etc.
        mount="secret",
        namespace="tenant-a",    # optional, OpenBao / Vault Enterprise
    ),
    default_ttl=60.0,
)
set_default_adapter(adapter)

# from this point, any module can `await get_secret("kv/app/db-url")`
```

### Adapter selection chain

When `get_secret` is called and no adapter is registered:

1. Explicit `set_default_adapter(...)` wins — preferred.
2. `SPINE_SECRETS_ADAPTER` env var (e.g. `vault`, `aws`, `azure`, `gcp`)
   acts as a *hint* — but does NOT auto-construct. If the hint is set
   without a registered adapter, the call still raises with a message
   directing the operator to the wizard.
3. Raise `SecretBackendError` — there is no env-var secret fallback.

## Adapter selection rules

| Deployment shape (per #17)        | Default adapter           |
|-----------------------------------|---------------------------|
| Laptop (free)                     | `VaultAdapter` → OpenBao container the wizard installs |
| BYOC (vendor-managed)             | `VaultAdapter` → OpenBao container provisioned in customer's cloud |
| Self-hosted customer-cloud        | `VaultAdapter` → customer-chosen: OpenBao OR Vault Enterprise OR cloud-native adapter |
| Self-hosted on-prem / air-gapped  | `VaultAdapter` → OpenBao container; cloud adapters disabled |

The cloud-native adapters (`AWS`, `Azure`, `GCP`) exist for
customers who already standardise on those services and want Spine
to use what they have rather than introduce OpenBao. Per #9 these
are all **vault-class** stores — none of them is "environment
variables in disguise."

## Hard rules

1. **No env-var secret payloads.** The adapter constructors may read
   their *own* metadata (Vault URL, token bootstrap path) from env
   if the wizard chose to put them there, but secret VALUES NEVER
   come from env. The Wave 1 validation agent greps for
   `os.environ.get` outside this package to enforce this.

2. **All methods are async.** Sync SDKs (boto3, azure-keyvault-secrets,
   google-cloud-secret-manager) are bridged via `asyncio.to_thread`
   inside the respective adapter.

3. **Errors normalize to three canonical exceptions:**
   * `SecretNotFound` — path does not exist
   * `SecretAccessDenied` — authenticated but lacks permission, OR
     missing/expired auth
   * `SecretBackendError` — everything else (transport, 5xx, parse)

4. **`delete` is idempotent.** Deleting an already-absent secret
   returns cleanly. Callers MAY catch `SecretNotFound` from `get`
   to test existence rather than calling a separate `exists()`.

5. **`list` returns paths, never values.** The cost of accidentally
   logging a value list is too high to even expose the shape.

6. **The cache is opt-in.** `CachedAdapter` is composed explicitly.
   It defaults to 60s TTL; per-call override is supported. Cache is
   invalidated on `put` and `delete` for the affected path.

## Dependencies (declare in v3 `pyproject.toml`)

| Adapter                       | Required dependency                  |
|-------------------------------|--------------------------------------|
| `VaultAdapter`                | `httpx >= 0.27`                      |
| `AWSSecretsManagerAdapter`    | `boto3 >= 1.34`                      |
| `AzureKeyVaultAdapter`        | `azure-keyvault-secrets >= 4.8`, `azure-identity >= 1.15` |
| `GCPSecretManagerAdapter`     | `google-cloud-secret-manager >= 2.18` |
| `VaultLeaseRenewer`           | `httpx >= 0.27`                      |
| `CachedAdapter`               | none (stdlib only)                   |

Spine ships **all four cloud adapters in the default install** so the
SAME container image can switch providers via runtime config — no
re-builds per customer. Operators uninstall what they don't need
via the bundle policy (Wave 4 license flags).

This Wave 0 package does **not** modify `pyproject.toml` /
`requirements.txt`; deps are documented here and the dependency
agent handles the actual package manifest update in Wave 0 close-out.

## Module map

| File                              | Purpose                                                                                   |
|-----------------------------------|-------------------------------------------------------------------------------------------|
| `__init__.py`                     | Public surface, default-adapter chain, module-level convenience functions                 |
| `base.py`                         | `SecretAdapter` abstract base, `SecretRef`, exception hierarchy                           |
| `vault.py`                        | OpenBao / HashiCorp Vault adapter (HTTP API v1, KV v2 mount, token + namespace)           |
| `aws_secrets_manager.py`          | AWS Secrets Manager adapter (boto3 bridged async)                                         |
| `azure_keyvault.py`               | Azure Key Vault adapter (azure-keyvault-secrets bridged async)                            |
| `gcp_secret_manager.py`           | GCP Secret Manager adapter (google-cloud-secret-manager bridged async)                    |
| `cache.py`                        | `CachedAdapter` — TTL wrapper composable around any adapter                               |
| `rotation.py`                     | `VaultLeaseRenewer` + cross-cloud `RotationHook` registry (Wave 4 audit integration TODO) |
| `tests/`                          | Contract + adapter mock tests (Wave 1 validation agent runs the full suite)               |

## Design decisions made independently in Wave 0

These are decisions the Wave 0 author made without explicit guidance;
flagging here so Wave 1 / 4 can revisit if needed:

1. **KV v2 default mount = `"secret"`.** Matches OpenBao + Vault
   dev-mode defaults and the wizard configuration target. KV v1 is
   intentionally unsupported; fork rather than complicate.
2. **`delete` removes ALL versions** (KV v2 metadata DELETE),
   not soft-delete-current. Conservative "really gone" semantic
   matches the abstract contract's implication.
3. **Vault retry policy = 3 attempts, exponential 0.2/0.4/0.8s,
   retry on network errors and 5xx only**. Aggressive enough for
   transient blips; bounded enough that a hard outage surfaces fast.
4. **`get` on a multi-key KV v2 entry raises `SecretBackendError`**
   unless the entry has exactly one key (returned as the value) or
   a top-level `"value"` key. Multi-key secrets need a dedicated
   reader API; Wave 1 can add `get_dict(path)` if needed.
5. **Cache `name` mirrors the wrapped adapter's name** so
   `SecretRef(adapter=cache.name, ...)` round-trips correctly.
6. **`SPINE_SECRETS_ADAPTER` env var is a discovery hint only**
   — it does not auto-construct an adapter, because Vault URL /
   token bootstrap differ too much across deployment shapes to
   be inferred. The wizard / bootstrap MUST register explicitly.
7. **Rotation registry is scaffolded but not wired** to the audit
   chain in Wave 0 — Wave 4 wires it once `evidence/` and `devops/`
   exist.

## Wave 1 follow-ups (handoff to validation agent)

* Run the test suite (`python3 -m unittest discover shared/secrets/tests`).
* Add a `tests/test_e2e_openbao.py` that starts the OpenBao container
  via docker-compose and exercises the full `VaultAdapter` against it.
* Migrate the 5 identified env-var-secret violations
  (`orchestrator/lib/approval.py`, `lib/_env_loader.sh`,
  `lib/share-pg.sh`, `lib/run-standalone-watcher.sh`,
  `lib/spine-connect.sh`) to use `get_secret`.
* Grep-gate CI: zero `os.environ.get("SPINE_*")` outside this package
  that resolves to a secret value (per #9 hard rule).
* Add named adapter registry for the multi-backend deployments where
  one Hub talks to vault for ops secrets but AWS Secrets Manager for
  customer secrets — module-level `get_secret(SecretRef(...))`
  overload comes in Wave 1.

## See also

* `docs/V3_DESIGN_DECISIONS.md` §9, §18, §20
* `docs/V3_TRIAGE.md` — `shared/secrets/` rows (lines 533–544) +
  the 5 vault violations list (lines 101–107)
* `docs/V3_BUILD_SEQUENCE.md` — Wave 0 deliverables table
