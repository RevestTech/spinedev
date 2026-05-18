# Spine v3 — `spine-hub` Vault policy
#
# Per V3_DESIGN_DECISIONS #9 (Vault-only secrets) — least-privilege grant for
# the Spine Hub container's app-role. Hub writes and reads its own secrets
# (LLM API keys, integration tokens, signing keys) under spine/. No access to
# other paths — no sys/, no auth/, no cubbyhole.
#
# Mount layout (KV v2):
#   spine/data/<key>         <- actual secret payload
#   spine/metadata/<key>     <- versions + custom metadata
#   spine/delete/<key>       <- soft-delete a specific version
#   spine/destroy/<key>      <- hard-destroy a specific version
#   spine/undelete/<key>     <- restore a soft-deleted version

# --- Read / write / list / delete secrets under spine/ ----------------------
path "spine/data/*" {
  capabilities = ["create", "read", "update", "delete"]
}

path "spine/metadata/*" {
  capabilities = ["read", "list", "delete"]
}

path "spine/delete/*" {
  capabilities = ["update"]
}

path "spine/undelete/*" {
  capabilities = ["update"]
}

# --- Explicit DENY by omission: no destroy ----------------------------------
# Permanent destruction (hard-delete of all versions) is reserved for the
# `spine-admin` role used by the Day-0 wizard + DR runbook. Hub MUST NOT be
# able to nuke its own historical secrets — that capability sits with humans.

# --- Token self-renewal ------------------------------------------------------
path "auth/token/renew-self" {
  capabilities = ["update"]
}

path "auth/token/lookup-self" {
  capabilities = ["read"]
}
