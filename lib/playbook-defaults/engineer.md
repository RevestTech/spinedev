# Engineer playbook — default lessons (seeded on install)

These are general engineering pitfalls accumulated across projects that
have used the SpineDevelopment template. Each lesson is one-line at the
top followed by enough context for an agent reading this in a future
prompt to apply the rule correctly.

The agent reads this file on every invocation as part of memory loading.
Add new lessons by appending with `bash scripts/team.sh learn "rule" --role engineer`,
or by editing this file directly.

## Bash + psql interaction

- **2026-05-08 — psql command-tag captures into shell variables corrupt UUIDs.** When you do `VAR=$(psql ... <<EOF ... INSERT ... RETURNING id; EOF)`, psql writes the returned UUID followed by a separate line `INSERT 0 1` (the command tag). `$VAR` ends up as a multi-line string. Subsequent SQL using `'$VAR'` fails with "invalid input syntax for type uuid". Fix: extract only the UUID with a regex pipe — e.g. `VAR=$(echo "$VAR" | grep -oE '[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}' | head -n 1)`. Same trap for serial integers (use `grep -oE '^[0-9]+$'`).

- **2026-05-08 — `psql` heredocs silently exit 0 even when SQL errored.** psql treats `ERROR:` as a runtime message, not a process failure, unless you explicitly opt in. Always include `--set ON_ERROR_STOP=on` in the `psql` invocation when running scripted SQL, and check `$?` after each heredoc.

- **2026-05-08 — `ON CONFLICT DO NOTHING` is a no-op without a unique constraint.** The clause needs an actual conflict target. Either (a) add a unique index in a migration first, or (b) use a SELECT-then-INSERT-if-empty pattern instead. The clause silently succeeds and inserts duplicates if there's no constraint to fire.

- **2026-05-08 — apostrophes in shell-interpolated SQL strings break the heredoc.** "OCR'd" inside a shell-substituted string within a heredoc breaks bash quoting. Either escape (`\'`) or rephrase the literal. Better: pass values via `psql --set` or via a JSON parameter file.

## Idempotency

- **Idempotency is a script-level property, not a comment.** A script that says "idempotent" but fails on the second run because it INSERTed without a uniqueness check is not idempotent. Test by running it twice; the second run must be a clean no-op.

- **Pre-flight + post-flight counts are the cheapest correctness check.** Before a bulk operation: capture relevant DB counts. Run the operation. Capture again. Confirm the deltas match expectations. If they don't, STOP and report.

## Defensive bash

- **Avoid `set -e` in scripts that have any `|| true` patterns.** They interact badly. Prefer explicit `if ! cmd; then ... fi` for the cases that matter and let the rest fall through.

- **Heredoc + variable interpolation = quoting hazard.** When the variable can contain user-controlled or query-result text, prefer file-based parameter passing over inline interpolation.

- **Capture exit codes immediately.** `cmd; rc=$?` — anything else (a function call, an `echo`, a subshell) clobbers `$?`. If you need the exit code for a decision, save it on the very next line.

## Schema vs data

- **Schema migrations are a separate workstream from data backfills.** A bash script that does data backfill (INSERT/UPDATE/DELETE rows) is in scope for engineer. A script that does ALTER TABLE / CREATE INDEX is migration territory and should be a Drizzle/SQL migration, not a one-shot script.

- **Don't paper over schema drift in scripts.** If a script needs an `as unknown as number` cast or a string-to-UUID coercion to compile, the schema drift is the real bug. Fix the schema or schema definition; the script should remain readable.

## Reporting style

- **A failure with a clear cause is more valuable than a "success" with subtle wrongness.** Agents that STOP-and-report when things look weird save downstream cleanup. Agents that silently continue past warnings produce 3am pages.

- **Always quote stdout/stderr verbatim in failure reports.** Don't paraphrase. The exact text of an error message is the source of truth for diagnosis.
