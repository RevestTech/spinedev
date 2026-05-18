# Install Guide

## TL;DR

```bash
bash /path/to/SpineDevelopment/install.sh ~/projects/your-project
cd ~/projects/your-project
make team-up
make team-status
```

That starts **every manager role listed in `scripts/roles.sh`**, **ten worker slots per manager**, and the watchdog — see `PROTOCOL.md` §1 for the lifecycle model.

---

## Install modes

| Mode | Command | What updates |
| --- | --- | --- |
| **Full** | `bash install.sh <target>` | `scripts/*.sh`, dashboard, Makefile targets, playbook seeds, protocol, recipes, orchestration docs, ADR templates, role prompts |
| **Knowledge-only** | `bash install.sh <target> --pull-knowledge-only` | Protocol, requirements, recipes, `docs/` (including `SPINE_PRACTICES.md`), ADR templates, role prompts — **scripts and dashboard untouched** |
| **Force overwrite** | add `--force` | Overwrites role prompts / recipes / templates where the installer would otherwise keep existing files |

Use **knowledge-only** on mature projects whose `scripts/` you have patched locally but you still want updated recipes and protocol text from the SpineDevelopment package.

---

## What the full installer does

1. Runs **preflight** (unless `--pull-knowledge-only`) using host requirements.
2. Creates `.planning/orchestration/agent-handoff/teams/<role>/` for **every role** in `scripts/roles.sh`.
3. Installs **`role-prompt.md`** per role.
4. Places idle **`directive.md`** placeholders where missing.
5. Copies **`scripts/*.sh`** (includes `roles.sh`, daemon, `team.sh`, watchdog, helpers) and **`scripts/spine-migrate.py`** (v1→v2 SQLite; **`make db-migrate`**).
6. Installs **`dashboard/index.html`**.
7. Copies **`PROTOCOL.md`** / **`REQUIREMENTS.md`** into orchestration paths.
8. Copies **`recipes/`** → `.planning/orchestration/recipes/`.
9. Copies **`docs/`** snippets (`SPINE_PRACTICES.md`, `IMPROVEMENT_CHECKLIST.md`, `EXTENSIONS.md`, **`PROGRAM_DELIVERY.md`**) respecting overwrite rules.
10. Copies **`templates/orchestration/`** + **`templates/program/`** (REQ ledger, POLICY stub, phases).
11. Seeds **`~/.spine-development/playbook/`** (never clobbers lessons).
12. Wires **`Makefile`** team targets when needed.
13. Optionally appends **`CLAUDE.md`** guidance.

Install is **idempotent**: existing files stay unless **`--force`** applies to that artifact class.

---

## Prerequisites

CLI agent on `PATH` — see **`REQUIREMENTS.md`**. Preflight verifies this for a **full** install.

---

## Verifying the install

```bash
make team-up
```

You should see a line like **`Starting agent team (N managers + M worker slots + watchdog)`** (from `lib/team.sh` via `scripts/team.sh`), where **N** is the number of roles in `scripts/roles.sh` and **M = N × 10** — e.g. **13 managers + 130 worker slots** in the stock template (ADR-001; see `DECISIONS.md` / `lib/roles.sh`).

```bash
make team-status
```

Each role block should show a running manager PID and workers.

If a manager fails, read `.planning/orchestration/agent-handoff/teams/<role>/log/daemon.log`.

---

## First directive

Smoke test via researcher — see **`README.md` » First use**, or paste a template from **`.planning/orchestration/recipes/`**.

---

## Context hygiene (avoid drift)

After install, read **`.planning/orchestration/docs/SPINE_PRACTICES.md`**. Keeps parallel agents aligned with **`AGENT_TEAM_PROTOCOL.md`**, **`DECISIONS.md`**, and **`SESSION_HANDOFF.md`**.

---

## Cleaning up daemons

```bash
make team-down
```

---

## Troubleshooting

### `cursor-agent: not found`

Install your chosen AI CLI and ensure it is on `PATH` for **non-interactive** shells (daemon uses `nohup`).

### Directives idle forever

The first line of the directive file must match `# Directive — …` — see **`AGENT_TEAM_PROTOCOL.md`**.

### Refresh recipes without risking script edits

```bash
bash /path/to/SpineDevelopment/install.sh . --pull-knowledge-only
```

Use **`--force`** if you deliberately want packager copies to replace edited in-repo recipes or role prompts.
