# Spine v3 — Keycloak per-tier feature matrix

> **Driver:** Decision #25 (Identity = Keycloak embedded by default, **feature-flag lightening per
> tier**). Decision #14 (3 segments → 5-tier matrix). Decision #17 (4 deployment shapes; air-gapped
> must work fully).
>
> **Cross-reference:** `shared/identity/feature_flag_lightening.py` (Agent C's scope) is the
> runtime enforcer of every flag in this table. License bundles (`license/feature_flags.py`, Wave 4)
> publish the flags; the OIDC client middleware in `shared/identity/` gates Hub features against them.
>
> **This file is the SOURCE OF TRUTH for which Keycloak capabilities are exposed per tier.** If
> `feature_flag_lightening.py` or any tier-bundle YAML disagrees, this file wins until explicitly
> updated.

---

## The 5 tiers

| Tier | Audience | Deployment shape (#17) | Identity posture |
|---|---|---|---|
| **free** | Solo founder / dev evaluating Spine on a laptop | Laptop | Single realm, local username+password only. No MFA enforcement. No IdP federation. |
| **founder** | Solo + early mid-market on managed BYOC | Vendor-Managed (BYOC) | + Optional MFA. + Social login (Google personal + GitHub OAuth). + ONE IdP federation. |
| **team** | Mid-market self-hosting | Self-hosted customer-cloud | + MFA REQUIRED. + Multi-IdP federation. + Basic SCIM. + Email/SMS notification channels. |
| **enterprise** | Regulated enterprise | Self-hosted on-prem | + Full SCIM 2.0. + Multi-realm. + Advanced password/lockout policy. + Custom themes. + Admin event export + retention. + WebAuthn/passkey. + Step-up auth for high-risk operations. |
| **airgapped** | Defense / classified | Air-gapped (v1.1) | Works fully. Social login DISABLED by default. IdP federation requires local IdP. No outbound telemetry. |

---

## Feature matrix (Keycloak capabilities)

Column legend: **Y** = on by default, **N** = off (license can grant), **opt** = off by default but
admin-toggleable in-tier, **req** = required (cannot be disabled).

| Keycloak capability | free | founder | team | enterprise | airgapped | Flag name (consumed by `shared/identity/feature_flag_lightening.py`) |
|---|:---:|:---:|:---:|:---:|:---:|---|
| Single realm                                           | Y   | Y   | Y   | Y    | Y   | `keycloak.single_realm` |
| Multi-realm                                            | N   | N   | N   | Y    | opt | `keycloak.multi_realm` |
| Username + password login                              | Y   | Y   | Y   | Y    | Y   | `keycloak.password_login` |
| Email verification on register                         | Y   | Y   | req | req  | Y   | `keycloak.email_verify` |
| Password policy (12-char + complexity)                 | Y   | Y   | req | req(14)| req | `keycloak.password_policy_strict` |
| Brute-force protection                                 | Y   | Y   | req | req  | req | `keycloak.brute_force_protection` |
| Account self-service (reset password)                  | Y   | Y   | Y   | Y    | Y   | `keycloak.account_self_service` |
| MFA — TOTP                                             | opt | opt | req | req  | req | `keycloak.mfa_totp` |
| MFA — WebAuthn / passkey                               | N   | opt | opt | req  | opt | `keycloak.mfa_webauthn` |
| MFA — recovery codes                                   | N   | opt | Y   | Y    | Y   | `keycloak.mfa_recovery_codes` |
| Step-up auth (re-prompt MFA for high-risk operations)  | N   | N   | opt | req  | req | `keycloak.step_up_auth` |
| Social login — Google personal                         | N   | opt | opt | opt  | N   | `keycloak.social_google` |
| Social login — GitHub OAuth                            | N   | opt | opt | opt  | N   | `keycloak.social_github` |
| Social login — Microsoft personal                      | N   | opt | opt | opt  | N   | `keycloak.social_microsoft` |
| IdP brokering — Okta                                   | N   | 1*  | Y   | Y    | opt | `keycloak.idp.okta` |
| IdP brokering — Azure AD / Entra                       | N   | 1*  | Y   | Y    | opt | `keycloak.idp.azure_ad` |
| IdP brokering — Google Workspace                       | N   | 1*  | Y   | Y    | opt | `keycloak.idp.google_workspace` |
| IdP brokering — Ping Identity                          | N   | 1*  | Y   | Y    | opt | `keycloak.idp.ping` |
| IdP brokering — OneLogin                               | N   | 1*  | Y   | Y    | opt | `keycloak.idp.onelogin` |
| Multi-IdP federation (more than one IdP simultaneously)| N   | N   | Y   | Y    | opt | `keycloak.multi_idp` |
| SAML 2.0 (in addition to OIDC)                         | N   | N   | opt | Y    | opt | `keycloak.saml` |
| SCIM 2.0 — basic (user provisioning)                   | N   | N   | Y   | Y    | opt | `keycloak.scim_basic` |
| SCIM 2.0 — full (groups, custom attrs, deprovision)    | N   | N   | N   | Y    | opt | `keycloak.scim_full` |
| Default groups + roles                                 | Y   | Y   | Y   | Y    | Y   | `keycloak.default_groups` |
| Custom roles / scopes                                  | N   | opt | Y   | Y    | Y   | `keycloak.custom_roles` |
| Fine-grained admin authz                               | N   | N   | opt | Y    | Y   | `keycloak.fine_grained_admin` |
| Custom login theme                                     | N   | N   | opt | Y    | Y   | `keycloak.custom_theme` |
| Custom email theme                                     | N   | N   | opt | Y    | Y   | `keycloak.custom_email_theme` |
| Admin events enabled                                   | Y   | Y   | Y   | req  | req | `keycloak.admin_events` |
| Admin event export to external SIEM                    | N   | N   | opt | Y    | Y   | `keycloak.admin_event_export` |
| Audit log retention > 30 days                          | N   | opt | Y   | Y    | Y   | `keycloak.audit_long_retention` |
| Token exchange                                         | N   | N   | opt | Y    | opt | `keycloak.token_exchange` |
| CIBA (Client-Initiated Backchannel Authentication)     | N   | N   | N   | Y    | opt | `keycloak.ciba` |
| Outbound telemetry to vendor (Tier 2 Smart Spine)      | opt | opt | opt | opt  | **DISABLED** | `keycloak.outbound_telemetry` |

*\* `founder` tier permits exactly **one** IdP federation at a time — admin can swap which one.*

---

## Token / session lifetimes per tier

These layer on top of the realm defaults in `realm-config/spine-realm.json` (Founder defaults).
Tier overrides are applied at bootstrap time and on every license-bundle refresh.

| Lifetime | free | founder | team | enterprise | airgapped |
|---|---|---|---|---|---|
| Access token TTL                  | 15m | 15m | 15m | **10m** | **10m** |
| Refresh token TTL                 | 30d | 30d | 14d | **7d**  | **7d**  |
| SSO session idle                  | 1h  | 30m | 30m | **15m** | **15m** |
| SSO session max                   | 24h | 10h | 10h | **8h**  | **8h**  |
| Step-up auth re-prompt window     | n/a | n/a | 1h  | **15m** | **15m** |
| Refresh-token reuse allowed       | N   | N   | N   | N       | N       |

---

## Default groups → tier visibility

All 5 default groups (`hub-admins`, `project-admins`, `developers`, `viewers`, `service-accounts`)
are seeded at every tier. Only the **role assignments** widen per tier:

- `free` / `founder`: hub-admin role is the same human as the realm admin (small teams).
- `team`+: hub-admin is a distinct role from realm admin (separation of duties).
- `enterprise`: `hub-admins` group can be split per business unit via custom roles flag.

---

## Cross-agent contract — what Agent C consumes

`shared/identity/feature_flag_lightening.py` MUST:

1. Accept tier name in `{free, founder, team, enterprise, airgapped}`.
2. Return a `dict[str, bool]` keyed by the **flag names in the table above**.
3. Resolve precedence: **license bundle** > **bundle-policy override** > **this table's default**.
4. Refuse unknown tiers with a typed error (do not silently default to `free`).
5. Re-evaluate on every license-bundle refresh event (per #23).

The Hub middleware (`shared/identity/middleware.py`) gates UI surfaces and API endpoints by calling
`feature_flag_lightening.is_enabled(tier, flag)`. UI shows graceful "upgrade to unlock" message per
#23 ("licensing becomes product discovery, not a wall").

---

## When this file changes

- A new Keycloak capability becomes available (KC version bump).
- A new tier is added (e.g. `regulated-mid` between `team` and `enterprise`).
- A capability moves between tiers (always coordinate with `license/feature_flags.py` definitions).
- Bump `_revision` in `shared/identity/feature_flag_lightening.py`'s default fallback table.

**Last revision:** 2026-05-17 — initial Wave 0 lock.
