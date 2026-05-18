# shared/identity — Spine OIDC client library

Spine v3 identity is **Keycloak-only** (design decision #25). This package is
the OIDC client library that every Wave 1+ feature uses to obtain the current
user. Spine Hub never touches SAML / SCIM / social-login / MFA directly —
all of that is delegated to the embedded Keycloak container.

## When to use

- Any FastAPI route that needs an authenticated user → `Depends(current_user)`
- Any route that needs a role/scope check → `Depends(require_role("admin"))`
- Any code that needs to verify a Bearer token outside a request → `KeycloakClient.verify_token(token)`
- Any code that needs to read the licensed tier's identity capabilities →
  `capabilities_for_tier(tier)`

## Public API (locked)

```python
from shared.identity import (
    KeycloakClient,
    current_user, optional_user,
    require_role, require_scope, has_role, has_scope,
    User, Role, Group, TokenClaims,
)
from shared.identity.feature_flag_lightening import (
    TIER_CAPABILITIES, capabilities_for_tier, supports, capability_level,
)
```

### FastAPI usage

```python
from fastapi import FastAPI, Depends
from shared.identity import (
    KeycloakClient,
    current_user,
    require_role,
    set_keycloak_client,
)

app = FastAPI()

@app.on_event("startup")
async def _wire_identity() -> None:
    set_keycloak_client(
        KeycloakClient(
            base_url="http://keycloak:8080",
            realm="spine",
            client_id="hub",
        )
    )

@app.get("/me")
async def me(user = Depends(current_user)):
    return {"id": user.id, "email": user.email, "roles": user.roles}

@app.post("/admin/bundles", dependencies=[Depends(require_role("admin"))])
async def upload_bundle(...): ...
```

## Dependencies (NOT auto-installed by this package)

Per Wave 0 scope rules this package does NOT modify `requirements.txt`. Add
these to whichever app pulls `shared.identity`:

| Package         | Min version | Purpose                                |
|-----------------|-------------|----------------------------------------|
| `pyjwt[crypto]` | 2.8         | JWT decode + RS256 signature verify    |
| `httpx`         | 0.27        | Async HTTP client (JWKS / userinfo)    |
| `fastapi`       | 0.110       | `Header`, `Depends`, `HTTPException`   |
| `pydantic`      | 2.6         | `User` / `TokenClaims` models          |

(The package degrades gracefully when imported without `fastapi` / `httpx` /
`pyjwt` — `py_compile` and unit-import succeed. Calling code paths that
actually need those libs raises a clear `RuntimeError`.)

## Tier capability matrix (#25 × #14)

| Capability                  | free | founder    | team       | enterprise | airgapped |
|-----------------------------|------|------------|------------|------------|-----------|
| Realms                      | 1    | 1          | 1          | multi      | 1         |
| Clients per realm           | 1    | 5          | 25         | multi      | multi     |
| Username + password         | yes  | yes        | yes        | yes        | yes       |
| MFA                         | no   | optional   | required   | required   | required  |
| Passwordless                | no   | optional   | optional   | optional   | optional  |
| Social login                | no   | yes        | yes        | yes        | **no**    |
| IdP federation              | no   | single     | multi      | multi      | multi     |
| SAML inbound                | no   | single     | multi      | multi      | multi     |
| SCIM                        | no   | no         | basic      | full       | full      |
| Custom themes               | no   | no         | yes        | yes        | yes       |
| Custom email templates      | no   | yes        | yes        | yes        | yes       |
| Audit export                | no   | no         | basic      | full       | full      |
| Event streaming             | no   | no         | no         | yes        | yes       |
| Hub UI: Groups admin tab    | no   | yes        | yes        | yes        | yes       |
| Hub UI: SCIM tab            | no   | no         | yes        | yes        | yes       |
| Hub UI: IdP federation tab  | no   | yes        | yes        | yes        | yes       |
| Hub UI: Audit export tab    | no   | no         | yes        | yes        | yes       |

The same Keycloak container ships at every tier. The matrix governs which
features are surfaced in the Hub UI + Day-0 wizard + accepted in bundle
policy. Enforcement (license signature, "upgrade to unlock" UI) lives in
`shared/license/` (Wave 1).

## Architecture notes

- **JWKS cache TTL:** 5 minutes (`DEFAULT_JWKS_TTL_SECONDS`). Verification
  forces one refresh on `kid`-miss so rotated keys propagate within a single
  failed verification.
- **Algorithm:** RS256 only. HS256 / none / EdDSA are rejected.
- **No password grant.** Authorization-code via the Keycloak login page is
  the only end-user flow.
- **Process-wide `KeycloakClient`** is registered once via
  `set_keycloak_client()`. Tests inject mocks via the same setter.
- **Bundle-policy resolver** is a swap-in (`set_policy_resolver`) so Wave 2
  can add group → role expansion without touching call sites.

## Wave 3 wiring (what's NOT done yet)

Per Wave 0 scope this package does NOT touch
`shared/api/dependencies.py`. Wave 3 replaces the header-stub `current_user`
there with:

```python
from shared.identity import current_user, optional_user  # noqa: F401
```

…and wires `set_keycloak_client(...)` into the Hub FastAPI startup hook.
Cookie / session support (browser SPA login round-trip) is also Wave 3 work.

## Test invocation

```bash
pytest shared/identity/tests/ -q
```

Tests that exercise full RS256 round-trip skip cleanly when
`pyjwt[crypto]` / `cryptography` is not installed.
