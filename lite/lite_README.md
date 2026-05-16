# Spine — lite install

> The minimum-viable Spine surface for Claude Code users who don't want
> to stand up Postgres, Docker, or daemons. Role prompts + skills +
> intake templates, dropped into `~/.spine-lite/` and surfaced inside
> Claude Code.

Implements **STORY-4.3.1**, **STORY-4.3.2**, **STORY-4.3.3**
(`docs/BACKLOG.md` EPIC-4.3).

---

## 30-second install

```bash
bash lite/install-lite.sh install
```

Defaults to `~/.spine-lite/`. Ships role prompts, skills, intake templates,
and artifact schemas (as docs). Recipes are opt-in:

```bash
bash lite/install-lite.sh install --with-recipes
```

Install at a custom path:

```bash
bash lite/install-lite.sh install --target-dir /opt/spine-lite
```

Register as a Claude Code plugin (after install):

```bash
bash lite/install-lite.sh as-claude-code-plugin
```

---

## What's included

- **13 role prompts** at `~/.spine-lite/role-prompts/` — `engineer`,
  `product`, `architect`, `planner`, `operator`, `datawright`, `qa`,
  `auditor`, `memory`, `researcher`, `seer`, `conductor`, `ux`. Invoke
  via @-mention inside Claude Code.
- **Skills** at `~/.spine-lite/skills/` — `brainstorming`,
  `verification-before-completion`, and any others bundled at release.
  Auto-triggered by Claude Code on matching contexts.
- **Intake templates** at `~/.spine-lite/templates/intake/` — six
  project archetypes (`web-app`, `internal-tool`, `data-pipeline`,
  `mobile`, `api-service`, `cli-tool`).
- **Pydantic artifact schemas** at `~/.spine-lite/artifacts/` —
  documentation reference for PRD/TRD/Roadmap shape. Not runnable in
  lite mode (no validator daemon).
- **`~/.spine-lite/SPINE.md`** — master doc Claude Code loads
  automatically; explains what's where.

See [`feature_matrix.md`](./feature_matrix.md) for the full lite-vs-full
comparison.

---

## What's NOT included

So you're not surprised:

- No Postgres, no Docker, no Python runtime requirement.
- No multi-agent daemon orchestration (you're one Claude Code session).
- No MCP server, no programmatic dispatch surface.
- No knowledge graph or cross-project semantic recall.
- No TRON verify, no audit log, no cost router, no eval harness, no
  Control Center dashboard.
- No cross-machine federation (`spine-connect`).

If you need any of those, install [full Spine](../INSTALL.md) instead,
or run `bash lite/upgrade-to-full.sh` after living with lite for a while.

---

## Use cases

- **Solo dev** using Claude Code for personal projects. You want role
  discipline (architect-vs-engineer-vs-qa) without infrastructure.
- **Evaluator** kicking Spine's tires before committing to the full
  install footprint.
- **Contributor** experimenting with prompt or skill changes — lite is
  fast to install/uninstall/reinstall.
- **Constrained env** where org policy disallows local daemons or
  Docker (laptop fleets, locked-down corporate machines).

---

## Subcommands

```bash
bash lite/install-lite.sh install [--target-dir PATH] [--with-recipes]
bash lite/install-lite.sh update                          # refresh from source; preserves edits
bash lite/install-lite.sh status                          # show installed components
bash lite/install-lite.sh uninstall [--yes]               # remove ~/.spine-lite/
bash lite/install-lite.sh as-claude-code-plugin           # register with ~/.claude/plugins/spine/
```

All subcommands are **idempotent**. Rerunning `install` is equivalent to
`update` — it never overwrites a file you've modified locally (detected
via mtime: if your copy is newer than the source ship, it's kept).

---

## Upgrade to full

```bash
bash lite/upgrade-to-full.sh ~/projects/my-app
```

This stages your local edits, runs the standard `install.sh`, then
merges your edits back over the full install so they're not overwritten.
Your `~/.spine-lite/` directory is archived to `~/.spine-lite.archive-<ts>/`
(remove when you've confirmed everything works).

See [`upgrade-to-full.sh`](./upgrade-to-full.sh) `--help` for options
(`--remove-lite`, `--preserve-archive`, `--dry-run`).

---

## Uninstall

```bash
bash lite/install-lite.sh uninstall
```

Asks for confirmation. Removes `~/.spine-lite/` only — leaves Claude
Code itself and your projects untouched. If you registered the Claude
Code plugin (`as-claude-code-plugin`), also remove the symlink:

```bash
rm ~/.claude/plugins/spine
```

---

## Files in this directory

| File | Purpose |
|---|---|
| `install-lite.sh` | The installer / updater / uninstaller. |
| `manifest.yaml` | Declarative bundle definition (what ships in lite). |
| `feature_matrix.md` | Side-by-side lite-vs-full comparison. |
| `upgrade-to-full.sh` | Migrate to full install, preserving edits. |
| `lite_README.md` | This file. |
| `claude-code-plugin/spine.json` | Claude Code plugin manifest. |
| `claude-code-plugin/README.md` | Plugin-install-path instructions. |
