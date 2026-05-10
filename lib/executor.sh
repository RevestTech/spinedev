#!/usr/bin/env bash
# executor.sh — pluggable AI CLI dispatcher.
#
# The daemon calls this script with a prompt; this script decides which CLI
# to invoke and how. Add new CLIs here without touching the daemon.
#
# Usage:
#   bash executor.sh <prompt-file>
#   stdin: ignored. The prompt is read from <prompt-file>.
#   stdout: agent's output (whatever the CLI prints)
#   exit code: agent's exit code
#
# Selection priority:
#   1. EXECUTOR_CMD env var explicitly set → use that
#   2. EXECUTOR_KIND env var set (cursor|claude|aider|opencode|codex|generic) → use it
#   3. Auto-detect from PATH in priority order
#
# Supported CLIs and how they're invoked:
#   cursor-agent  → `cursor-agent "$prompt"`           (positional arg)
#   cursor        → `cursor "$prompt"`                 (positional arg)
#   claude        → `claude -p "$prompt"`              (Claude Code CLI, -p flag)
#   aider         → `aider --message "$prompt" --yes` (one-shot mode)
#   opencode      → `opencode "$prompt"`               (positional arg)
#   codex         → `codex "$prompt"`                  (OpenAI Codex CLI)
#   generic       → reads $EXECUTOR_CMD as a shell command and pipes prompt to stdin

set -uo pipefail

PROMPT_FILE="${1:?prompt file required}"
[[ -f "$PROMPT_FILE" ]] || { echo "executor: prompt file not found: $PROMPT_FILE" >&2; exit 2; }

PROMPT_CONTENT="$(cat "$PROMPT_FILE")"

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
  Or set EXECUTOR_CMD=/path/to/your-cli (must accept prompt as argv[1] or via stdin)
EOF
  exit 127
}

# --- invoke the CLI ---

case "$EXECUTOR" in
  cursor-agent|cursor|opencode|codex)
    # All take prompt as argv[1]
    exec "$EXECUTOR" "$PROMPT_CONTENT"
    ;;
  claude)
    # Claude Code CLI — use -p flag for prompt
    exec claude -p "$PROMPT_CONTENT"
    ;;
  aider)
    # Aider — non-interactive one-shot mode
    exec aider --message "$PROMPT_CONTENT" --yes --no-pretty
    ;;
  generic)
    # User supplied a custom command — pipe prompt to its stdin
    if [[ -z "${EXECUTOR_CMD:-}" ]]; then
      echo "executor: EXECUTOR_KIND=generic requires EXECUTOR_CMD" >&2
      exit 2
    fi
    exec bash -c "$EXECUTOR_CMD" <<< "$PROMPT_CONTENT"
    ;;
  explicit:*)
    # User passed a full command — use it as-is, prompt as argv[1]
    cmd="${EXECUTOR#explicit:}"
    exec bash -c "$cmd \"\$0\"" "$PROMPT_CONTENT"
    ;;
  *)
    echo "executor: internal error — unknown resolved executor '$EXECUTOR'" >&2
    exit 2
    ;;
esac
