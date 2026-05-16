# `tools/check-module-boundaries.sh` — Spine subsystem boundary lint

Enforces the rule from **REQ-INIT-7 §7.5 FR-1** and **`docs/ARCHITECTURE.md §4`**:
each subsystem owns its internals and only talks to others through
`shared/mcp/`. Fails CI on any cross-subsystem import / source / require.
Implements `STORY-7.1.3` (generalised to every subsystem).

## What's enforced

| Subsystem       | May import from         |
|-----------------|-------------------------|
| `orchestrator/` | `orchestrator`, `shared`|
| `plan/`         | `plan`, `shared`        |
| `build/`        | `build`, `shared`       |
| `verify/` \*    | `verify`, `shared`      |
| `shared/`       | `shared` (leaf)         |

\* `verify/tron/`, `verify/admin-ui/`, `verify/frontend/` are TRON's own
subtree-merged code — not enforced. See `verify/SUBSYSTEM_BOUNDARY.md`.

Languages: **Python** (`ast`; lazy in-function imports → warning),
**Bash** (`source X` / `. X` / `bash X`), **JS/TS** (`import`/`require`/
dynamic `import`). Out of scope (`boundary-rules.yaml` `excluded_paths`):
`lib/`, `scripts/`, `recipes/`, `templates/`, `docs/`, `db/`.

## Special cases

- **`shared/mcp/tools/iso.py` + `sandbox.py`** lazy-import TRON to
  preserve `verify/` standalone-deployability (REQ-INIT-8 G-8) — covered
  by the declarative `shared_mcp_lazy_imports` rule (warning, not error).
- **Lazy Python imports inside functions** downgrade to warning so
  intentional circular-import workarounds aren't blocked, but reviewers
  still see them.

## How to run

```bash
make check-boundaries                           # via Makefile.v2
tools/check-module-boundaries.sh                # text output
tools/check-module-boundaries.sh --changed-only # diff vs origin/main
tools/check-module-boundaries.sh --format json  # for tooling
tools/check-module-boundaries.sh --format junit # for CI test reports
tools/check-module-boundaries.sh --explain      # show which rule fired
```

Override diff base with `SPINE_BOUNDARY_DIFF_BASE=main`. Exit: `0` clean
· `1` violations · `2` warnings only · `3` parser error · `64` bad usage.
Target ≤2s full repo scan on commodity hardware.

## Adding an exception

Preferred: expose the dependency through `shared/mcp/` (see
`orchestrator/lib/router.sh` for the dispatch chokepoint and
`shared/mcp/tools/*.py` for existing wrappers).

If a direct import is genuinely the right call, add an exception:

```bash
tools/check-module-boundaries.sh --add-exception \
  build/some_file.py plan/ "Reason; remove after STORY-X.Y.Z"
```

Appends to `tools/boundary-rules.yaml` with 90-day expiry. Expired
exceptions still pass but log a stderr deprecation note. Each exception
is technical debt — review every sprint. You may also hand-edit
`boundary-rules.yaml` for new declarative rules (cf. `shared_mcp_lazy_imports`).

## CI integration

GitHub Actions:

```yaml
- name: Boundary check
  run: pip install pyyaml && make check-boundaries
```

Pre-commit (`.git/hooks/pre-commit`):

```bash
tools/check-module-boundaries.sh --changed-only || exit 1
```

## Cross-refs

- `docs/PRD.md` REQ-INIT-7 §7.5 FR-1 (binding spec)
- `docs/ARCHITECTURE.md §4` (target repo structure)
- `docs/BACKLOG.md` STORY-7.1.3 (delivery story)
- `Makefile.v2` `check-boundaries` target (dispatches here)
- `orchestrator/lib/router.sh` (the MCP chokepoint this lint protects)
- Per-subsystem contracts: `build/README.md`, `plan/README.md`,
  `verify/SUBSYSTEM_BOUNDARY.md`, `orchestrator/README.md`, `shared/README.md`
