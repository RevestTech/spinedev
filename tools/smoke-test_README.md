# tools/smoke-test.sh — Spine v2 integration smoke harness

Purpose: catch integration regressions across the ~296-file v2 codebase by
codifying the manual sequence the wave 8 team ran by hand. See
`docs/STATUS.md` §5 for the original results table — each row in that
table maps to a check in this harness, and a green run here means none of
the F1-F11 bugs documented there has regressed.

This is a single bash file. There are no per-check sub-scripts (bundled
for portability + single-file ops). Python is invoked only via inline
`python3 -c` for the Pydantic / MCP-registry / skills checks; no virtualenv
is required.

## Run locally

```bash
bash tools/smoke-test.sh                    # all 7 phases, text output
bash tools/smoke-test.sh --phase 2          # just the DB schema phase
bash tools/smoke-test.sh --no-cleanup       # leave test rows in DB for debugging
bash tools/smoke-test.sh --format json      # JSON summary on stdout
```

## Run in CI

```bash
bash tools/smoke-test.sh --ci               # implies --format junit --no-color
                                            # exits 1 on any FAIL, 2 on env problem
```

Pipe stdout to your JUnit collector (CircleCI, GitHub Actions JUnit, etc.).

## What each phase tests + why

| # | Phase | What it asserts |
|---|---|---|
| 1 | Environment | `docker` + `spine_postgres` container + `python3 >=3.10` + `psql` + 21 Flyway migrations on disk. Warns (not fails) on missing `yq`. |
| 2 | DB schema  | Loads `db/.env` to build `SPINE_DB_URL` (the F8/F9 fix), pings the DB, asserts the 9 `spine_*` schemas exist, asserts minimum table counts per schema. |
| 3 | Python imports + registries | `discover_tools()` registers >=27 MCP tools; `discover_skills()` returns >=5 skills; 7 named Pydantic / cost / audit modules import; `shared.api` is INFO-only (FastAPI optional, F4). |
| 4 | Pydantic validators | Draft `BuildArtifact` constructs; refuse-to-seal validator fires on engineer+sealed+code_changes+empty kg_impact; `PRDv1` rejects `problem_statement="TBD"`. |
| 5 | Lifecycle flow | Inserts a `smoke-harness-$$-001` project with all required fields (incl. `pipeline_manifest_path`); runs `orchestrator/lib/transition.sh validate` then `execute` for `intake -> plan_in_progress`; asserts the row advanced and a `transition` row was written. |
| 6 | KG MCP tools | Skipped gracefully if `spine_kg.kg_node` is absent (F3 / pgvector). Otherwise asserts `find_callers` is in `TOOL_REGISTRY`. |
| 7 | Optional integrations | INFO/WARN on missing `yq`, `fastapi`, `pgvector` — none of these is a FAIL. |

## Output statuses

- `PASS` — check succeeded.
- `FAIL` — real regression; harness exits non-zero.
- `WARN` — degraded but not blocking (e.g. yq missing → awk fallback).
- `SKIP` — prerequisite absent (e.g. DB unreachable → phases 2/5/6 skip).
- `INFO` — informational only (e.g. FastAPI not installed).

Final summary line: `PASS=N FAIL=N WARN=N SKIP=N INFO=N (total=N)`.

## Exit codes

| Code | Meaning |
|---|---|
| 0   | All checks PASSed (WARN/SKIP/INFO allowed). |
| 1   | One or more FAILs that look like real regressions. |
| 2   | Environment problem (Postgres unreachable, python3 missing, psql missing). CI should treat this as "infrastructure", not "code broke". |
| 3   | Harness internal error (reserved). |
| 64  | Unknown / invalid flag. |

## Interpreting failures

| FAIL id | Likely cause |
|---|---|
| `env.postgres_container` | spine_postgres not running — `cd db && make up`. |
| `env.migrations` | <21 V*.sql on disk — repo checkout stale or partial. |
| `db.connect` | `SPINE_DB_URL` wrong; the script reads `db/.env`. Same root cause as F8/F9. |
| `db.schema.spine_*` | Missing schema — run `cd db && make migrate` or apply the relevant V14-V21 file via `make psql`. |
| `db.tables.*` | Schema present but tables missing — partial migration; check Flyway history. |
| `py.mcp_tools` | A tool module raised on import; run `python3 -c "from shared.mcp.tools import discover_tools; discover_tools()"` for the traceback. |
| `py.skills` | `shared/skills/skills/` empty or invalid SKILL.yaml; see `shared/skills/registry.py`. |
| `py.import.<mod>` | Module import broken; check `PYTHONPATH` (the harness sets it to repo root). |
| `pyd.build_refuse_seal` | The refuse-to-seal validator in `shared/schemas/build/build_artifact.py` regressed. |
| `pyd.prd_tbd_reject` | The `is_empty_or_tbd` gate in `plan/artifacts/_base.py` regressed. |
| `lc.validate` / `lc.execute` | F8 (port), F9 (password), F10 (yq/awk parse) or F11 (router.sh unbound) — see `docs/STATUS.md` §5. |
| `lc.phase_advanced` | Transition silently no-op'd — check `orchestrator/lib/transition.sh` SQL. |
| `kg.find_callers_registered` | `shared/mcp/tools/kg.py` failed to load or `register_tool` regression. |

## Cross-references

- `docs/STATUS.md` §5 — the manual sequence this harness automates.
- `lib/tests/test-*.sh` — sibling harnesses with the same PASS/FAIL style.
- `Makefile.v2` already has a `smoke-test:` target; add a line to invoke this script:

  ```make
  smoke-test: ## Run the integration smoke harness
  	@bash tools/smoke-test.sh --ci
  ```

- `db/.env` — connection source of truth (the harness loads it; do **not** hardcode `33000`).
- `orchestrator/lib/transition.sh` — bash style + exit code conventions this harness mirrors.

## Idempotence + cleanup

The harness inserts rows under `name LIKE 'smoke-harness-$$-%'` (PID-suffixed)
so concurrent runs don't collide. On exit it `DELETE`s those rows (cascades
to `phase_history` / `transition`). Pass `--no-cleanup` if you need to
inspect them.
