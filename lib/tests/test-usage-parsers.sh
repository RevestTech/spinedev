#!/usr/bin/env bash
# Pass E selftest: sources lib/usage-parsers.sh and feeds it synthetic log
# fixtures for each supported executor kind. Asserts:
#   (1) spine_parse_usage prints exactly one line of valid JSON.
#   (2) For known executors with parseable input: tokens_in / tokens_out /
#       cost_usd / model_id match the fixture values.
#   (3) For empty / malformed / unknown-executor input: output is "{}".
#
# Negative assertions live under set -euo so any helper exit propagates.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

ROOT="$(mktemp -d "${TMPDIR:-/tmp}/spine-usage-parsers.XXXXXX")"
cleanup() { rm -rf "$ROOT"; }
trap cleanup EXIT

# Wave 3 (Squad A): usage-parsers.sh migrated lib/ → shared/runtime/.
USAGE_SH="$REPO/shared/runtime/usage-parsers.sh"
[[ -f "$USAGE_SH" ]] || USAGE_SH="$REPO/lib/usage-parsers.sh"
# shellcheck source=/dev/null
source "$USAGE_SH"

# Helper: assert spine_parse_usage on LOG_FILE / KIND prints JSON with the
# expected keys/values. Args:
#   $1 label   $2 log_path   $3 kind
#   $4 expected_tokens_in   $5 expected_tokens_out
#   $6 expected_cost_usd    $7 expected_model_id
assert_parse() {
  local label="$1" log="$2" kind="$3"
  local exp_in="$4" exp_out="$5" exp_cost="$6" exp_model="$7"
  local out
  out="$(spine_parse_usage "$log" "$kind")"
  python3 - <<PY
import json, sys
raw = """${out}"""
# The bash variable expansion above can leave trailing whitespace; strip it.
raw = raw.strip()
try:
    obj = json.loads(raw)
except json.JSONDecodeError as e:
    print(f"FAIL [$label] not valid JSON: {e}: {raw!r}", file=sys.stderr); sys.exit(1)
if not isinstance(obj, dict):
    print(f"FAIL [$label] not a JSON object: {obj!r}", file=sys.stderr); sys.exit(1)
exp = {
    "tokens_in":  $exp_in,
    "tokens_out": $exp_out,
    "cost_usd":   $exp_cost,
    "model_id":   "$exp_model",
}
errs = []
for k, v in exp.items():
    got = obj.get(k)
    # Tolerate int/float interchange for cost_usd
    if k == "cost_usd":
        if abs(float(got or 0) - float(v)) > 1e-6:
            errs.append(f"{k}: expected {v}, got {got!r}")
    elif got != v:
        errs.append(f"{k}: expected {v!r}, got {got!r}")
if errs:
    print(f"FAIL [$label] " + "; ".join(errs), file=sys.stderr); sys.exit(1)
print(f"OK [$label] {obj}")
PY
}

assert_empty() {
  local label="$1" log="$2" kind="$3"
  local out
  out="$(spine_parse_usage "$log" "$kind")"
  python3 - <<PY
import json, sys
raw = """${out}""".strip()
try:
    obj = json.loads(raw)
except json.JSONDecodeError as e:
    print(f"FAIL [$label] not valid JSON: {e}: {raw!r}", file=sys.stderr); sys.exit(1)
if obj != {}:
    print(f"FAIL [$label] expected {{}}, got {obj!r}", file=sys.stderr); sys.exit(1)
print(f"OK [$label] {{}}")
PY
}

# ─────────────────────────────────────────────────────────────────────
# Fixture 1: Claude Code --output-format=json envelope
# ─────────────────────────────────────────────────────────────────────
CLAUDE_LOG="$ROOT/claude.log"
cat > "$CLAUDE_LOG" <<'EOF'
----- 2026-05-11T00:00:00Z invoke (engineer/manager, phase=pickup) -----
some text streaming from the model
intermediate JSON noise {"type":"system","subtype":"info"}
{"type":"result","subtype":"success","is_error":false,"result":"done","session_id":"sess1","total_cost_usd":0.0125,"usage":{"input_tokens":1000,"output_tokens":500,"cache_creation_input_tokens":100,"cache_read_input_tokens":50},"model":"claude-sonnet-4-6"}
----- exit rc=0 wall=42s outcome=completed -----
EOF
# tokens_in = 1000 + 100 + 50 = 1150
assert_parse "claude" "$CLAUDE_LOG" "claude" 1150 500 0.0125 "claude-sonnet-4-6"

# ─────────────────────────────────────────────────────────────────────
# Fixture 2: cursor-agent JSON line at end of stdout
# ─────────────────────────────────────────────────────────────────────
CURSOR_LOG="$ROOT/cursor.log"
cat > "$CURSOR_LOG" <<'EOF'
some progress text from cursor-agent
maybe more lines
{"role":"assistant","content":"hello world","model":"cursor-small","usage":{"prompt_tokens":1234,"completion_tokens":567,"total_tokens":1801},"cost_usd":0.012}
EOF
assert_parse "cursor-agent" "$CURSOR_LOG" "cursor-agent" 1234 567 0.012 "cursor-small"

# ─────────────────────────────────────────────────────────────────────
# Fixture 3a: aider classic Tokens line (commas, dollar message+session)
# ─────────────────────────────────────────────────────────────────────
AIDER_LOG="$ROOT/aider.log"
cat > "$AIDER_LOG" <<'EOF'
Aider v0.55.0
Model: claude-3-5-sonnet-20240620 with diff edit format
Git repo: .git with 42 files
> /add foo.py
Tokens: 1,234 sent, 567 received. Cost: $0.0123 message, $0.0456 session.
> /run pytest
Tokens: 800 sent, 200 received. Cost: $0.0099 message, $0.0555 session.
EOF
# Last Tokens line wins.
assert_parse "aider-classic" "$AIDER_LOG" "aider" 800 200 0.0099 "claude-3-5-sonnet-20240620"

# ─────────────────────────────────────────────────────────────────────
# Fixture 3b: aider with k-suffix and "$0.12 / $0.43 session" format
# ─────────────────────────────────────────────────────────────────────
AIDER_LOG2="$ROOT/aider-k.log"
cat > "$AIDER_LOG2" <<'EOF'
Aider v0.60.0
Model: gpt-4o-mini with whole edit format
> work work work
> Tokens: 12.3k sent, 4.5k received. Cost: $0.12 / $0.43 session.
EOF
# 12.3k -> 12300; 4.5k -> 4500
assert_parse "aider-suffix" "$AIDER_LOG2" "aider" 12300 4500 0.12 "gpt-4o-mini"

# ─────────────────────────────────────────────────────────────────────
# Fixture 4: empty log
# ─────────────────────────────────────────────────────────────────────
EMPTY_LOG="$ROOT/empty.log"
: > "$EMPTY_LOG"
assert_empty "claude-empty"       "$EMPTY_LOG" "claude"
assert_empty "cursor-empty"       "$EMPTY_LOG" "cursor-agent"
assert_empty "aider-empty"        "$EMPTY_LOG" "aider"

# ─────────────────────────────────────────────────────────────────────
# Fixture 5: unknown / placeholder executor kinds
# ─────────────────────────────────────────────────────────────────────
JUNK_LOG="$ROOT/junk.log"
echo "random output with no recognised summary" > "$JUNK_LOG"
assert_empty "unknown-kind"       "$JUNK_LOG" "opencode"
assert_empty "codex-kind"         "$JUNK_LOG" "codex"
assert_empty "auto-kind"          "$JUNK_LOG" "auto"
assert_empty "generic-kind"       "$JUNK_LOG" "generic"

# Aider log that lacks a Tokens line should also fall through to {}.
NO_TOKENS_LOG="$ROOT/aider-no-tokens.log"
cat > "$NO_TOKENS_LOG" <<'EOF'
Model: claude-3-haiku
nothing else of interest
EOF
assert_empty "aider-no-tokens"    "$NO_TOKENS_LOG" "aider"

# Missing log file path → {}.
assert_empty "missing-file"       "$ROOT/does-not-exist.log" "claude"

printf '%s\n' "test-usage-parsers OK"
