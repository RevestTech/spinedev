# Spine — Claude Code plugin (lite)

> Install path for Spine lite **as a Claude Code plugin**. This is the
> recommended path for Claude Code users — it puts Spine's 13 role
> personas, auto-triggering skills, and intake templates one keystroke
> away inside any Claude Code session, with zero infrastructure.

Implements **STORY-4.3.1** (`docs/BACKLOG.md`, EPIC-4.3).

---

## Install

### From the Claude Code plugin marketplace (when published)

```bash
claude plugin install spine
```

### Manual install from this repo

```bash
# 1. install the bundle
bash lite/install-lite.sh install

# 2. register it with Claude Code
bash lite/install-lite.sh as-claude-code-plugin
```

The second command symlinks `~/.spine-lite/` to `~/.claude/plugins/spine/`
(or the equivalent under `~/.config/claude/` or
`~/Library/Application Support/Claude/`, whichever your Claude Code
installation uses). Restart Claude Code to pick up the plugin.

### One-shot install via plugin URL (when supported)

```bash
/plugin install RevestTech/spinedev
```

---

## What activates

When the plugin loads, Claude Code:

- Reads `SPINE.md` on session start (master doc; tells the model what
  Spine is and how to invoke roles).
- Registers the 13 role prompts as @-mention targets — type
  `@engineer`, `@product`, `@architect`, etc. and Claude Code loads
  that persona for the next turn.
- Registers the bundled skills (`brainstorming`,
  `verification-before-completion`, plus any others shipped at release)
  for **auto-trigger**: Claude Code's trigger engine fires them when
  the conversation context matches, without you having to invoke them.
- Surfaces intake templates at `templates/intake/` — say "use the
  web-app intake template" and Claude loads it.
- Exposes the Pydantic artifact schemas as documentation. Useful when
  hand-rolling a PRD and asking Claude to verify shape.

---

## What does NOT activate

Anything daemon-resident:

- No background processes, no Postgres, no Docker.
- No MCP server, no audit log, no cost router.
- No knowledge graph, no semantic recall.
- No Control Center dashboard, no approval queue.

See [`../feature_matrix.md`](../feature_matrix.md) for the full
lite-vs-full comparison.

---

## Plugin manifest

The plugin is described by [`spine.json`](./spine.json). Edit `skills[]`
to add/remove auto-triggered skills, or `mentions{}` to add custom
@-mention shortcuts.

The format follows what Anthropic documents for Claude Code plugin
manifests; if you're authoring extensions on top of it, consult the
Claude Code docs for currently supported keys.

---

## Upgrade to full Spine

Lite is the front door, not the destination. When you're ready for the
full local-deployed agent team (Postgres + daemons + MCP + audit log +
knowledge graph), upgrade in place:

```bash
bash lite/upgrade-to-full.sh ~/path/to/your/project
```

The upgrader stages any role-prompt / skill / template edits you made
locally, runs the standard `install.sh`, then merges your edits back
over the full install. Your customizations are preserved verbatim. The
old `~/.spine-lite/` is archived as `~/.spine-lite.archive-<ts>/` so
you can roll back.

After the upgrade, **remove the Claude Code plugin symlink** so the
plugin doesn't shadow the full install:

```bash
rm ~/.claude/plugins/spine
```

(The full install integrates with Claude Code via the per-project
`CLAUDE.md` hook instead of the global plugin path.)

---

## Uninstall the plugin

```bash
# remove the Claude Code symlink
rm ~/.claude/plugins/spine

# remove the bundle itself
bash lite/install-lite.sh uninstall
```

Restart Claude Code. Spine surfaces will no longer be available; your
projects are untouched.
