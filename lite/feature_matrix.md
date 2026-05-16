# Spine — lite vs full feature matrix

> Implements **STORY-4.3.2** (`docs/BACKLOG.md`, EPIC-4.3).
>
> Two install paths, same role discipline. **Lite** is a Claude Code plugin
> with role prompts + skills + intake templates and zero infrastructure.
> **Full** is the full local-deployed agent team with Postgres, daemons,
> MCP server, knowledge graph, cost router, and audit log.

---

## At a glance

| Feature                                       | Lite      | Full |
|-----------------------------------------------|-----------|------|
| Role prompts (13 roles)                       | Yes       | Yes  |
| Skills (auto-triggered in Claude Code)        | Yes       | Yes  |
| Intake templates (6 project archetypes)       | Yes       | Yes  |
| Pydantic artifact schemas (docs reference)    | Yes       | Yes  |
| Recipes (`ship-feature`, `postmortem`, etc.)  | Opt-in    | Yes  |
| Multi-agent daemon orchestration              | No        | Yes  |
| Postgres state + lifecycle                    | No        | Yes  |
| MCP server                                    | No        | Yes  |
| Knowledge graph (semantic recall)             | No        | Yes  |
| TRON verify pipeline                          | No        | Yes  |
| Audit log (tamper-evident)                    | No        | Yes  |
| Cost router + per-project budget enforcement  | No        | Yes  |
| Eval harness                                  | No        | Yes  |
| Approval queue UI / Control Center            | No        | Yes  |
| Cross-machine federation (`spine-connect`)    | No        | Yes  |
| Docker / Postgres / Python runtime deps       | No        | Yes  |
| Install footprint on disk                     | < 5 MB    | ~ 400 MB (incl. images) |
| Time to first prompt                          | < 30 s    | 5 – 15 min (preflight + DB bring-up) |

---

## Detail

### Role prompts (13 roles)

Both flavors ship the same 13 prompts: `engineer`, `product`, `architect`,
`planner`, `operator`, `datawright`, `qa`, `auditor`, `memory`,
`researcher`, `seer`, `conductor`, `ux`. In lite they live at
`~/.spine-lite/role-prompts/<role>.md` and you invoke them by @-mention
inside Claude Code. In full they live at
`.planning/orchestration/agent-handoff/teams/<role>/role-prompt.md` and the
manager daemons load them on directive pickup.

### Skills

Skills are markdown + YAML bundles that **Claude Code itself** triggers
based on session context. Because the trigger engine runs inside Claude
Code (not inside a Spine daemon), skills work identically in both modes.

### Intake templates

Both flavors ship `web-app`, `internal-tool`, `data-pipeline`, `mobile`,
`api-service`, `cli-tool` archetypes. Lite users open the matching YAML
and hand-walk Claude through the interrogation. Full users get the
`product` role daemon to drive the interrogation automatically.

### Artifact schemas (documentation only in lite)

The Pydantic schemas under `plan/artifacts/` define PRD/TRD/Roadmap shape.
Lite ships them as **reference docs only** — there's no validator daemon
to enforce shape. If you produce a PRD by hand, you can paste the schema
into Claude Code and ask it to verify shape, but no automation does that
for you.

### Recipes (opt-in in lite)

Recipes (`ship-feature.md`, `postmortem.md`, etc.) are runnable narratives.
They're opt-in in lite (`install-lite.sh install --with-recipes`) because
many of them assume the daemon layer exists. The plain-narrative ones
work fine in Claude Code; the orchestration-heavy ones quietly degrade.

### What lite **does not** give you

The following are full-install-only. None of them are "missing" in lite —
they're explicitly excluded because they require infrastructure:

- **Multi-agent daemon orchestration.** Lite is one Claude Code session;
  full runs 13 manager daemons and up to 10 worker daemons each.
- **Postgres state.** Lite has no persistent state across sessions other
  than what you keep in your repo. Full keeps directive history,
  decisions, costs, and audit trail in Postgres.
- **MCP server.** Lite has no programmatic dispatch surface. Full exposes
  one for editors / orchestrators / CI to drive Spine.
- **Knowledge graph + semantic recall.** Lite has no cross-project
  lesson retrieval. Full indexes lessons in pgvector and injects top-K
  into role prompts at directive time.
- **TRON verify, audit log, cost router, eval harness, approval queue UI**
  — all daemon-resident; none in lite.

---

## Picking the right path

### Pick lite when

- You're a solo developer who uses Claude Code for your own projects.
- You want role discipline without standing up Postgres / Docker.
- You're evaluating Spine and don't want to commit to the full footprint.
- You're a contributor experimenting with prompt or skill changes.
- Your org policy disallows local daemons or background processes.

### Pick full when

- You're running a real project that needs persistent state across
  sessions and machines.
- You want enforced gates (PRD sign-off, TRD sign-off, Roadmap sign-off)
  with audit trail.
- You're a team of 2+ humans driving the same Spine instance.
- You need per-project / per-user budget enforcement.
- You need the knowledge graph and cross-project semantic recall.
- You need the Control Center dashboard for portfolio observability.
- You're in a regulated environment that requires the audit log.

---

## Upgrade lite → full

Run `bash lite/upgrade-to-full.sh`. It:

1. Detects the existing `~/.spine-lite/` install.
2. Stages any role-prompt / skill / template **edits you made locally**.
3. Runs the standard `install.sh` (full install).
4. Merges your staged edits back over the full install — **your
   customizations are never overwritten**.
5. Archives `~/.spine-lite/` to `~/.spine-lite.archive-<ts>/` so you can
   roll back.

Typical upgrade time: 5 – 15 minutes (mostly waiting on Docker pulls and
Postgres init). Your custom prompts and lessons carry over verbatim.

---

## Downgrade full → lite

Not officially supported (full has state lite cannot represent). If you
need to step back, run `install-lite.sh install` to create a fresh lite
install alongside the full one — they coexist (different target dirs).
