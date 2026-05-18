#!/usr/bin/env bash
# usage-parsers.sh — extract token/cost usage from an executor's log.
#
# Sourced by team-agent-daemon.sh. Provides a single public function:
#
#   spine_parse_usage AGENT_LOG_FILE EXECUTOR_KIND
#       Prints to stdout a single line of JSON with shape:
#         {"tokens_in":NUM,"tokens_out":NUM,"cost_usd":NUM,"model_id":"STRING"}
#       Or, if nothing parseable: {}
#
# Design notes:
#   * Parsing is done via an embedded python3 heredoc — bash regex would be
#     fragile against multi-line JSON, escaped quotes, partial writes, etc.
#   * The function MUST NEVER raise. Worst case: parsing throws and we emit
#     "{}". The daemon falls back to zero-token cost rows.
#   * Wired CLIs (Pass C / Pass E): claude, cursor-agent, aider. The
#     remaining placeholders (opencode, codex, generic, auto) return "{}"
#     because their output formats are not standardised yet — extending
#     them is a follow-up. Each parser is independently fallback-safe:
#     any parse failure returns "{}" rather than raising.
#
# Claude Code JSON contract (--output-format=json --verbose):
#   The CLI emits a single top-level JSON object at the end of stdout, e.g.:
#     {"type":"result","subtype":"success","is_error":false,
#      "result":"...","session_id":"...","total_cost_usd":0.012,
#      "usage":{"input_tokens":1234,"output_tokens":567,
#               "cache_creation_input_tokens":0,"cache_read_input_tokens":0},
#      "model":"claude-sonnet-4-6"}
#   We scan the log from the bottom and take the last balanced JSON object,
#   then map:
#     tokens_in  = usage.input_tokens + cache_creation_input_tokens
#                                     + cache_read_input_tokens
#     tokens_out = usage.output_tokens
#     cost_usd   = total_cost_usd
#     model_id   = model

# Intentionally not "set -eu" — this file is sourced by team-agent-daemon.sh
# and must not propagate failures up.

spine_parse_usage() {
  local agent_log="${1:-}" kind="${2:-}"

  if [[ -z "$agent_log" || ! -f "$agent_log" ]]; then
    echo '{}'
    return 0
  fi

  case "$kind" in
    claude)
      _spine_parse_usage_claude "$agent_log"
      ;;
    cursor-agent|cursor)
      _spine_parse_usage_cursor_agent "$agent_log"
      ;;
    aider)
      _spine_parse_usage_aider "$agent_log"
      ;;
    *)
      # opencode / codex / generic / auto: not yet implemented. Emit empty
      # so the cost row goes through with zeros.
      echo '{}'
      ;;
  esac
}

_spine_parse_usage_claude() {
  local agent_log="$1"
  # Bound the work: only inspect the tail of the log. Claude's final JSON
  # object is small (< a few KB) but the log can be 5 MB. 256 KB is a safe
  # ceiling that covers any reasonable session summary.
  python3 - "$agent_log" <<'PY' 2>/dev/null || echo '{}'
import json
import sys

EMPTY = "{}"

def emit(payload):
    sys.stdout.write(json.dumps(payload, separators=(",", ":")))
    sys.stdout.write("\n")

def find_last_balanced_object(text):
    """Scan from the end and return the last well-formed top-level JSON
    object string, or None. We bracket-count to find the boundaries; this
    is intentionally conservative — if the tail of the log has a partial
    write the count won't balance and we return None."""
    n = len(text)
    end = -1
    # Find the last '}' that closes a complete object.
    for i in range(n - 1, -1, -1):
        ch = text[i]
        if ch == "}":
            end = i
            depth = 0
            in_str = False
            esc = False
            for j in range(i, -1, -1):
                cj = text[j]
                if in_str:
                    if esc:
                        esc = False
                    elif cj == "\\":
                        esc = True
                    elif cj == '"':
                        in_str = False
                    continue
                if cj == '"':
                    in_str = True
                    continue
                if cj == "}":
                    depth += 1
                elif cj == "{":
                    depth -= 1
                    if depth == 0:
                        return text[j:end + 1]
            # didn't balance from this '}', keep scanning further left
            end = -1
    return None

def main():
    if len(sys.argv) < 2:
        sys.stdout.write(EMPTY + "\n")
        return
    path = sys.argv[1]
    try:
        # Read only the tail to bound CPU. 256 KB is more than enough for
        # Claude's final result envelope.
        with open(path, "rb") as fh:
            try:
                fh.seek(0, 2)
                size = fh.tell()
                start = max(0, size - 262144)
                fh.seek(start)
                data = fh.read()
            except OSError:
                data = fh.read()
        text = data.decode("utf-8", errors="replace")
    except OSError:
        sys.stdout.write(EMPTY + "\n")
        return

    # Walk from the bottom looking for the most-recent parseable JSON object.
    remaining = text
    for _ in range(8):  # bound the search; in practice the first hit wins
        candidate = find_last_balanced_object(remaining)
        if candidate is None:
            break
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            # Not parseable — drop this candidate and continue searching
            # earlier in the buffer.
            cut = remaining.rfind(candidate)
            if cut <= 0:
                break
            remaining = remaining[:cut]
            continue

        # Claude Code emits {"type":"result", ...}. Be lenient: accept any
        # dict that has BOTH a "usage" sub-object and a "model" field, which
        # is what we actually need.
        if not isinstance(obj, dict):
            cut = remaining.rfind(candidate)
            if cut <= 0:
                break
            remaining = remaining[:cut]
            continue
        usage = obj.get("usage")
        model = obj.get("model")
        if not isinstance(usage, dict) or not isinstance(model, str):
            cut = remaining.rfind(candidate)
            if cut <= 0:
                break
            remaining = remaining[:cut]
            continue

        def _as_int(v):
            try:
                return int(v)
            except (TypeError, ValueError):
                return 0

        def _as_float(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0

        tokens_in = (
            _as_int(usage.get("input_tokens"))
            + _as_int(usage.get("cache_creation_input_tokens"))
            + _as_int(usage.get("cache_read_input_tokens"))
        )
        tokens_out = _as_int(usage.get("output_tokens"))
        cost_usd = _as_float(obj.get("total_cost_usd"))

        emit({
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
            "model_id": model,
        })
        return

    sys.stdout.write(EMPTY + "\n")

try:
    main()
except Exception:
    sys.stdout.write(EMPTY + "\n")
PY
}

# ─────────────────────────────────────────────────────────────────────
# Pass E: cursor-agent parser
# ─────────────────────────────────────────────────────────────────────
# Cursor's CLI (`cursor-agent --print ...`) emits a JSON line at the end
# of stdout summarising the assistant response. Observed shape:
#   {"role":"assistant","content":"...","model":"cursor-small",
#    "usage":{"prompt_tokens":1234,"completion_tokens":567,
#             "total_tokens":1801},"cost_usd":0.012}
# We scan the tail of the log line-by-line from the bottom looking for
# the most recent JSON line that has both "model" and "usage" keys, then
# project to the standard usage envelope.
_spine_parse_usage_cursor_agent() {
  local agent_log="$1"
  python3 - "$agent_log" <<'PY' 2>/dev/null || echo '{}'
import json
import sys

EMPTY = "{}"

def emit(payload):
    sys.stdout.write(json.dumps(payload, separators=(",", ":")))
    sys.stdout.write("\n")

def main():
    if len(sys.argv) < 2:
        sys.stdout.write(EMPTY + "\n")
        return
    path = sys.argv[1]
    try:
        with open(path, "rb") as fh:
            try:
                fh.seek(0, 2)
                size = fh.tell()
                start = max(0, size - 262144)
                fh.seek(start)
                data = fh.read()
            except OSError:
                data = fh.read()
        text = data.decode("utf-8", errors="replace")
    except OSError:
        sys.stdout.write(EMPTY + "\n")
        return

    # Walk lines from the bottom; first one that JSON-parses to a dict
    # with both "model" and "usage" wins.
    lines = text.splitlines()
    for raw in reversed(lines):
        line = raw.strip()
        if not line or not line.startswith("{"):
            continue
        if "\"model\"" not in line or "\"usage\"" not in line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        usage = obj.get("usage")
        model = obj.get("model")
        if not isinstance(usage, dict) or not isinstance(model, str):
            continue

        def _as_int(v):
            try:
                return int(v)
            except (TypeError, ValueError):
                return 0

        def _as_float(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0

        tokens_in = _as_int(usage.get("prompt_tokens"))
        tokens_out = _as_int(usage.get("completion_tokens"))
        cost_usd = _as_float(obj.get("cost_usd", 0))

        emit({
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
            "model_id": model,
        })
        return

    sys.stdout.write(EMPTY + "\n")

try:
    main()
except Exception:
    sys.stdout.write(EMPTY + "\n")
PY
}

# ─────────────────────────────────────────────────────────────────────
# Pass E: aider parser
# ─────────────────────────────────────────────────────────────────────
# Aider prints a Tokens/Cost summary at the end of each round, e.g.:
#   Tokens: 1,234 sent, 567 received. Cost: $0.0123 message, $0.0456 session.
# Newer versions also use k/M suffixes:
#   > Tokens: 12.3k sent, 4.5k received. Cost: $0.12 / $0.43 session.
# We grab the LAST such line in the log. The model name appears earlier
# near the top, on a line like:
#   Model: claude-3-5-sonnet-20240620 with diff edit format
# Resilience: any parse failure returns {} so the daemon still emits a
# zero-token cost row.
_spine_parse_usage_aider() {
  local agent_log="$1"
  python3 - "$agent_log" <<'PY' 2>/dev/null || echo '{}'
import json
import re
import sys

EMPTY = "{}"

# Match a number with optional decimals and optional k/m suffix. Commas
# in the integer part are stripped before this match runs.
NUM = r"(\d+(?:\.\d+)?)([kKmM]?)"
TOKENS_RE = re.compile(
    # The comma after "sent" disappears when we strip thousands-separators
    # for numeric parsing, so we make it optional. Whitespace between
    # "sent" and the next number is mandatory.
    rf"Tokens:\s*{NUM}\s*sent,?\s+{NUM}\s*received",
    re.IGNORECASE,
)
COST_RE = re.compile(r"Cost:\s*\$\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
MODEL_RE = re.compile(r"^\s*(?:>\s*)?Model:\s*([^\s,]+)", re.IGNORECASE)

def _suffix_mult(suf):
    s = (suf or "").lower()
    if s == "k":
        return 1000
    if s == "m":
        return 1_000_000
    return 1

def _to_int(num_s, suf):
    try:
        return int(round(float(num_s) * _suffix_mult(suf)))
    except (TypeError, ValueError):
        return 0

def main():
    if len(sys.argv) < 2:
        sys.stdout.write(EMPTY + "\n")
        return
    path = sys.argv[1]
    try:
        with open(path, "rb") as fh:
            try:
                fh.seek(0, 2)
                size = fh.tell()
                start = max(0, size - 262144)
                fh.seek(start)
                data = fh.read()
            except OSError:
                data = fh.read()
        text = data.decode("utf-8", errors="replace")
    except OSError:
        sys.stdout.write(EMPTY + "\n")
        return

    # Find the LAST Tokens-line (aider prints one per round). Strip
    # commas first so "1,234" parses as 1234.
    tokens_in = 0
    tokens_out = 0
    cost_usd = 0.0
    found = False
    for raw in reversed(text.splitlines()):
        no_commas = raw.replace(",", "")
        tm = TOKENS_RE.search(no_commas)
        if not tm:
            continue
        tokens_in = _to_int(tm.group(1), tm.group(2))
        tokens_out = _to_int(tm.group(3), tm.group(4))
        cm = COST_RE.search(no_commas)
        if cm:
            try:
                cost_usd = float(cm.group(1))
            except (TypeError, ValueError):
                cost_usd = 0.0
        found = True
        break

    if not found:
        sys.stdout.write(EMPTY + "\n")
        return

    # Model: scan from the TOP for the first "Model: <name>" line. Aider
    # prints this once when the session starts. If none found, emit empty
    # model_id rather than failing the whole row.
    model_id = ""
    for raw in text.splitlines():
        mm = MODEL_RE.match(raw)
        if mm:
            model_id = mm.group(1).strip()
            break

    sys.stdout.write(json.dumps({
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost_usd,
        "model_id": model_id,
    }, separators=(",", ":")))
    sys.stdout.write("\n")

try:
    main()
except Exception:
    sys.stdout.write(EMPTY + "\n")
PY
}
