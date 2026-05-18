# Spine v3 — `spine-readonly` Vault policy
#
# For audit / compliance / Evidence-Store collectors (Wave 4 evidence/
# subsystem, per V3_DESIGN_DECISIONS #24). Cite-or-Refuse verify-class roles
# (#12) may also use this role when they need to PROVE a secret exists at a
# given path without revealing the payload.
#
# Read-only access to spine/. NO write, NO delete, NO destroy.

path "spine/data/*" {
  capabilities = ["read"]
}

path "spine/metadata/*" {
  capabilities = ["read", "list"]
}

# Subkeys (KV v2 feature) — lets compliance verify a key EXISTS at a path
# without reading its value. Useful for "is there an API key configured?"
# checks that must not leak the key itself.
path "spine/subkeys/*" {
  capabilities = ["read"]
}

# --- Token self-renewal ------------------------------------------------------
path "auth/token/renew-self" {
  capabilities = ["update"]
}

path "auth/token/lookup-self" {
  capabilities = ["read"]
}
