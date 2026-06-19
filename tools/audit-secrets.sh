#!/usr/bin/env bash
# tools/audit-secrets.sh — V1 §4 secret-value grep audit, with classifier.
#
# Per design decision #9 (vault-only secrets, no exceptions), no SECRET
# VALUE may live in committed code. Vault-path REFERENCES are fine
# (they tell the operator where the real secret lives). Env-var NAME
# references are fine (they tell the runtime what variable holds the
# bootstrap credential).
#
# This script categorizes every grep hit and only fails on confirmed
# value leaks. Run as part of V1_SHIP_CHECKLIST.md §4 launch gate.
#
# Exit codes:
#   0 — clean (zero value leaks)
#   1 — value leaks found (printed)
#   2 — usage / invocation error

set -euo pipefail

readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

readonly PATTERN='ANTHROPIC_API_KEY|OPENAI_API_KEY|SPINE_[A-Z_]+_KEY|SPINE_[A-Z_]+_PASSWORD|SPINE_[A-Z_]+_SECRET|SPINE_[A-Z_]+_TOKEN'

# Path-based exclusions: docs that intentionally enumerate the pattern.
readonly PATH_EXCLUDE='vault-refs|TRIAGE|BUILD_SEQUENCE|DESIGN_DECISIONS|SECURITY_GUIDE|LICENSING_GUIDE|FEDERATION_GUIDE|HUB_OPERATIONS_GUIDE|DEPLOYMENT_SHAPES|README|CHANGELOG|RELEASE_NOTES|V1_SHIP_CHECKLIST|STATUS.md|legal/|chatsession|audit-secrets.sh|^./.agents/|^./.venv/|^./node_modules/|^./.spine/work/'

# Hits that look like value assignments (the only category that's a real leak).
#   FOO=value           — bash export / docker compose env entry
#   "FOO": "value"      — JSON/YAML value
#   FOO = "value"       — Python assignment
#   FOO=${FOO:-default} — bash default-fallback IS suspicious if default
#                         is not a vault path
# We extract everything after the first `=` and decide.

# Allow-list of "obviously fake" value patterns. Smoke tests own
# their stack end-to-end and use these placeholders against ephemeral
# infra they bring up + tear down themselves; these cannot be confused
# with real production secrets.
readonly OBVIOUS_FAKE_PATTERNS='^(smoke-test-|test-|__SET_ME_|<piped|<set-|<your-|changeme|REPLACE_|tron_LOCAL_DEV_ONLY_2026|tron_dev_only|spine-dev-|fake-|dummy-|example-|EXAMPLE_)'

fail=0
hits=$(grep -rnE "${PATTERN}" \
  --include="*.py" --include="*.sh" --include="*.yaml" --include="*.yml" \
  2>/dev/null \
  | grep -v -E "${PATH_EXCLUDE}" \
  || true)

if [[ -z "${hits}" ]]; then
  printf '✓ secret-value grep audit: 0 hits\n'
  exit 0
fi

while IFS= read -r line; do
  # Extract value after first `=` if present.
  value="${line#*=}"
  # Trim leading/trailing quotes and whitespace.
  value="${value#\"}"; value="${value#\'}"
  value="${value%\"*}"; value="${value%\'*}"
  value="${value%% *}"

  # Cases where the line is NOT a value leak:
  #   1. The grep matched on env-var NAME usage like
  #      `os.environ.get("ANTHROPIC_API_KEY")` or
  #      `env_var = "ANTHROPIC_API_KEY"` — no `=<value>` followed by
  #      a non-empty literal.
  #   2. The value after `=` is itself the pattern name (test asserting
  #      env-var absence: `for forbidden in ("ANTHROPIC_API_KEY", ...)`).
  #   3. The value matches OBVIOUS_FAKE_PATTERNS allow-list.
  #   4. The value is a vault path (contains `/` and no whitespace).
  #   5. The value is a `${VAR:-default}` reference where the default is
  #      itself an env-var-name pattern.

  # Strip everything after the line:NNN: prefix to get the actual code.
  code="${line#*:*:}"

  # If no `=` in the code part (env-var name reference only) → not a leak.
  if [[ "${code}" != *=* ]]; then
    continue
  fi

  # Extract the RHS of the first `=` in the code itself, not the file prefix.
  rhs="${code#*=}"
  # Trim leading whitespace + optional `${`
  rhs_trim="$(printf '%s' "${rhs}" | sed -E 's/^[[:space:]]*//')"

  # Skip lines that are just comments/docstrings:
  case "${code}" in
    \#*|\;*|//\ *|\*\ *) continue ;;
  esac

  # Skip log lines (operational messages referencing flag names, not assignments).
  if [[ "${code}" =~ ^[[:space:]]*log[[:space:]] ]]; then
    continue
  fi

  # Skip bash boolean flag checks (`[[ "$VAR" == "1" ]]`) — not secret assignments.
  if [[ "${code}" =~ \=\=[[:space:]]*\"[01]\" ]]; then
    continue
  fi

  # Skip `os.environ.get(...)` / `os.getenv(...)` / `environ.pop(...)` —
  # these are env-var NAME usages, not value assignments. The `=` we
  # split on is the Python assignment to the LHS variable, but the RHS
  # is a function call that READS the env var, not a value literal.
  if [[ "${code}" =~ os\.(environ\.(get|pop)|getenv)\( ]]; then
    continue
  fi
  # Same for shell `${VAR:-default}` patterns where VAR is the secret name.
  if [[ "${code}" =~ \$\{[A-Z_]+_(KEY|PASSWORD|SECRET|TOKEN)[^}]*\} ]]; then
    continue
  fi

  # Skip if RHS is a bash required-env-or-fail (`:?...`).
  if [[ "${rhs_trim}" == *:?* ]]; then
    continue
  fi

  # Extract first token of the RHS.
  first_token="$(printf '%s' "${rhs_trim}" | awk '{print $1}' \
    | tr -d '",;{}()' )"

  # If the first token references another env var (`$VAR` or `${VAR...}`),
  # it's a passthrough — not a leak.
  case "${first_token}" in
    \$*|\${*) continue ;;
  esac

  # If the first token starts with a recognized obviously-fake pattern,
  # it's a documented test placeholder.
  if [[ "${first_token}" =~ ${OBVIOUS_FAKE_PATTERNS} ]]; then
    continue
  fi

  # If first token looks like a vault path (has `/` and no whitespace),
  # it's a path reference.
  if [[ "${first_token}" == *"/"* ]]; then
    continue
  fi

  # If first token is the pattern name itself (test asserting absence),
  # not a leak.
  if [[ "${first_token}" =~ ^(ANTHROPIC_API_KEY|OPENAI_API_KEY|SPINE_)[A-Z_]*$ ]]; then
    continue
  fi

  # If first token is empty (after trimming) or quote-only, skip.
  if [[ -z "${first_token}" || "${first_token}" == '""' || "${first_token}" == "''" ]]; then
    continue
  fi

  # If we get here, this is a potential value leak.
  printf '⚠ potential value leak: %s\n' "${line}"
  fail=1
done <<< "${hits}"

if (( fail == 0 )); then
  printf '✓ secret-value grep audit: 0 confirmed value leaks (raw hits classified as env-var names / vault paths / obvious-fake test placeholders)\n'
  exit 0
fi

printf '\n✗ secret-value grep audit: %d potential value leak(s) — fix or add allow-list entry\n' "${fail}" >&2
exit 1
