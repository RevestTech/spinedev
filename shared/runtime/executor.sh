#!/usr/bin/env bash
# executor.sh — pluggable AI CLI dispatcher.
#
# The daemon calls this script with a prompt FILE PATH; this script decides
# which CLI to invoke and how. Add new CLIs here without touching the daemon.
#
# Usage:
#   bash executor.sh <prompt-file>
#   stdin: ignored — the prompt is read from <prompt-file>.
#   stdout: agent's output (whatever the CLI prints)
#   exit code: agent's exit code
#
# SECURITY — prompt content is NEVER placed on argv. All executors receive
# the prompt either:
#   1. via stdin redirection from <prompt-file>, or
#   2. via a file-path flag (e.g., aider's --message-file)
# This prevents prompt content from leaking through /proc/<pid>/cmdline or
# `ps -ef` output on shared hosts. See docs/_archived/v1-PROTOCOL.md hardening notes.
#
# Selection priority:
#   1. EXECUTOR_CMD env var explicitly set → use that
#   2. EXECUTOR_KIND env var set (cursor|claude|aider|opencode|codex|generic) → use it
#   3. Auto-detect from PATH in priority order
#
# Supported CLIs and how they're invoked:
#   cursor-agent  → `cursor-agent <stdin>`             (prompt via stdin)
#   cursor        → `cursor <stdin>`                   (prompt via stdin)
#   claude        → `claude -p --output-format=json --verbose <stdin>`
#                     (Claude Code CLI; structured output so lib/usage-parsers.sh
#                      can extract tokens_in/tokens_out/cost_usd/model)
#   aider         → `aider --message-file <FILE> --yes` (file flag, no argv leak)
#   opencode      → `opencode <stdin>`                 (prompt via stdin)
#   codex         → `codex <stdin>`                    (prompt via stdin)
#   generic       → reads $EXECUTOR_CMD as a shell command and pipes prompt to stdin
#
# Claude --output-format=json note:
#   Claude Code emits a single JSON envelope at the end of stdout instead of
#   streaming markdown. That's the right trade-off for cost tracking: the
#   daemon's stall-watcher works on log growth (one final big write still
#   counts), and lib/usage-parsers.sh needs the JSON envelope to extract
#   usage. Users who specifically want streaming markdown can override with
#   EXECUTOR_KIND=generic + EXECUTOR_CMD='claude -p' (and accept zero-token
#   cost rows for those invocations).
#
# If your CLI doesn't accept prompt via stdin, set EXECUTOR_KIND=generic and
# EXECUTOR_CMD to a wrapper that reads stdin and invokes the CLI however it
# needs (e.g., `cat | your-cli --prompt-arg "$(cat)"` — but note this re-leaks
# via argv; the wrapper is responsible for the trade-off).

set -uo pipefail

PROMPT_FILE="${1:?prompt file required}"
[[ -f "$PROMPT_FILE" ]] || { echo "executor: prompt file not found: $PROMPT_FILE" >&2; exit 2; }

# --- discover the CLI ---

resolve_executor() {
  # Explicit kind override
  if [[ -n "${EXECUTOR_KIND:-}" ]]; then
    case "$EXECUTOR_KIND" in
      cursor)   command -v cursor-agent >/dev/null 2>&1 && { echo "cursor-agent"; return; } ;;
      claude)   command -v claude       >/dev/null 2>&1 && { echo "claude";       return; } ;;
      aider)    command -v aider        >/dev/null 2>&1 && { echo "aider";        return; } ;;
      opencode) command -v opencode     >/dev/null 2>&1 && { echo "opencode";     return; } ;;
      codex)    command -v codex        >/dev/null 2>&1 && { echo "codex";        return; } ;;
      generic)  echo "generic"; return ;;
    esac
    echo "executor: EXECUTOR_KIND=$EXECUTOR_KIND requested but binary not found on PATH" >&2
    return 1
  fi
  # Explicit binary override
  if [[ -n "${EXECUTOR_CMD:-}" ]]; then
    # If EXECUTOR_CMD is just a binary name and that exists, use it
    local first_word
    first_word=$(echo "$EXECUTOR_CMD" | awk '{print $1}')
    if command -v "$first_word" >/dev/null 2>&1; then
      echo "explicit:$EXECUTOR_CMD"
      return
    fi
    echo "executor: EXECUTOR_CMD=$EXECUTOR_CMD not found on PATH" >&2
    return 1
  fi
  # Auto-detect in priority order
  for bin in cursor-agent cursor claude aider opencode codex; do
    command -v "$bin" >/dev/null 2>&1 && { echo "$bin"; return; }
  done
  return 1
}

EXECUTOR="$(resolve_executor)" || {
  cat >&2 <<EOF
executor: no AI CLI found on PATH.
  Install one of: cursor-agent, cursor, claude, aider, opencode, codex
  Or set EXECUTOR_CMD=/path/to/your-cli (must accept prompt via stdin)
EOF
  exit 127
}

# --- invoke the CLI ---
#
# All invocations read the prompt from stdin (redirected from $PROMPT_FILE)
# or via a file-path flag. Prompt content is never placed on argv.

case "$EXECUTOR" in
  cursor-agent|cursor|opencode|codex)
    # These CLIs accept the prompt via stdin in one-shot mode.
    exec "$EXECUTOR" < "$PROMPT_FILE"
    ;;
  claude)
    # Claude Code CLI — -p reads prompt from stdin when no positional arg.
    # --output-format=json emits a structured envelope (with usage + model
    # fields) that lib/usage-parsers.sh consumes for token-level cost
    # tracking. --verbose is required by Claude Code when --output-format
    # is set on a non-streaming invocation.
    exec claude -p --output-format=json --verbose < "$PROMPT_FILE"
    ;;
  aider)
    # Aider — has a first-class file flag, no argv leak at all.
    exec aider --message-file "$PROMPT_FILE" --yes --no-pretty
    ;;
  generic)
    # User supplied a custom command — pipe prompt to its stdin.
    if [[ -z "${EXECUTOR_CMD:-}" ]]; then
      echo "executor: EXECUTOR_KIND=generic requires EXECUTOR_CMD" >&2
      exit 2
    fi
    exec bash -c "$EXECUTOR_CMD" < "$PROMPT_FILE"
    ;;
  explicit:*)
    # User passed a full command — run it as a shell command with prompt on stdin.
    # Note: EXECUTOR_CMD is treated as trusted shell input by design. Do not
    # populate it from untrusted sources.
    cmd="${EXECUTOR#explicit:}"
    exec bash -c "$cmd" < "$PROMPT_FILE"
    ;;
  *)
    echo "executor: internal error — unknown resolved executor '$EXECUTOR'" >&2
    exit 2
    ;;
esac
