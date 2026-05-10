# Recipe — Writing a safe DB-interacting bash script (engineer)

For the class of script that hits Postgres / MySQL / Redis from bash and
mutates state. Drop into `teams/engineer/directive.md` or use as a checklist
when you write one yourself.

This recipe codifies lessons from **2026-05-08 sponsor–archive linkage debugging** — a bash + `psql` script that looked correct but silently mis-handled stderr and exit codes.

---

```markdown
# Directive — Write/audit a DB-interacting bash script for <PURPOSE>

## Tier hint: low

## Goal
<one paragraph: what data manipulation is needed, against which tables, why a
script (not a migration) is the right tool>

## Required script-hygiene patterns

The script MUST follow ALL of these. Any deviation triggers a re-write.

### 1. psql exit codes
- Use `psql --set ON_ERROR_STOP=on` so SQL errors actually exit non-zero.
- After every heredoc psql call, check `$?` and bail with a clear error.
  ```bash
  RESULT=$($PSQL <<EOF
  ...
  EOF
  )
  if [[ $? -ne 0 ]]; then
    echo "Step <X> failed. SQL output: $RESULT" >&2
    exit 1
  fi
  ```

### 2. Capturing values returned by psql
- NEVER raw-capture `psql` output into a shell variable when the query is
  `INSERT … RETURNING X` or similar. psql writes the value PLUS a separate
  command-tag line (`INSERT 0 1`).
- Always extract the expected shape via regex:
  ```bash
  # UUID
  UUID=$(echo "$RAW" | grep -oE '[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}' | head -n 1)
  # Integer
  N=$(echo "$RAW" | grep -oE '^[0-9]+$' | head -n 1)
  # Boolean
  B=$(echo "$RAW" | grep -oE '^(t|f)$' | head -n 1)
  ```

### 3. ON CONFLICT requires a real constraint
- `ON CONFLICT DO NOTHING` is a no-op without a unique index/constraint to
  conflict on. Verify the conflict target exists. If it doesn't, either
  add the constraint in a migration first (out of scope for a one-shot
  script) or use a SELECT-then-INSERT-if-empty pattern:
  ```bash
  EXISTING=$($PSQL -c "SELECT id FROM tbl WHERE name = '$KEY' LIMIT 1;" | grep -oE '<shape>')
  if [[ -z "$EXISTING" ]]; then
    NEW=$($PSQL -c "INSERT INTO tbl ... RETURNING id;" | grep -oE '<shape>')
    EXISTING="$NEW"
  fi
  ```

### 4. Idempotency
- The script MUST be safe to run twice. The second run prints "Nothing to
  do" or equivalent and exits cleanly with no DB changes.
- Test by ALWAYS running it twice and capturing both runs' output in the
  report.

### 5. Pre-flight + post-flight counts
- BEFORE the mutation: query relevant table counts, capture them.
- Run the mutation.
- AFTER: re-query the same counts. Confirm the deltas match expectations.
- If they don't, STOP and report — don't try to "fix" forward.

### 6. Quoting and shell safety
- Apostrophes in shell-interpolated SQL strings break heredoc quoting. Avoid
  literal apostrophes in description/comment fields. Either escape (`\'`)
  or rephrase ("OCR-processed" instead of "OCR'd").
- For values that may contain user-controlled text, prefer file-based
  parameter passing (`psql -f`) over inline interpolation.

### 7. Defensive bash
- DO NOT use `set -e`. It interacts badly with `cmd 2>&1 || true` patterns
  that operational scripts need.
- DO use `set -uo pipefail` (errors on undefined vars + pipeline error
  propagation, but lets explicit `|| true` work).
- Capture exit codes IMMEDIATELY: `cmd; rc=$?` — anything else clobbers `$?`.

## Tasks
1. Write the script at `scripts/<NAME>.sh` following all hygiene patterns above.
2. Run it once. Capture full stdout + exit code. Verify post-flight counts.
3. Run it AGAIN. Confirm idempotent (no-op + clean exit).
4. Optional: add a unit-test-style script that uses a transient DB to
   verify success-then-no-op behavior in CI.
5. Run `npm run lint:check && npm test` to confirm no regression.

## Stop conditions (do NOT continue if any of these hit)
- The first run produces unexpected post-flight counts. Stop, report, do
  not attempt to recover by mutating again — the architect needs to see
  the bad state to diagnose.
- The second run is NOT a no-op. Idempotency is broken; that's a bug in
  the script, not a one-time data state. Fix the script before doing
  anything else.
- Any psql call returns non-zero exit and the script kept going. The
  `--set ON_ERROR_STOP=on` is missing or the `$?` check was skipped.

## Report format
Replace this file with `# Report — <script-name>` containing:
- The script's path
- Diff (or full file if new)
- First-run stdout (verbatim) + exit code + post-flight counts
- Second-run stdout (verbatim) confirming idempotency
- Anything surprising
- Optional cleanup steps for old/duplicate state
```
