# Jira / Linear mapping (optional mirror)

External ALM tools are **not** the source of truth. Canonical IDs live in `todo/BACKLOG.md`.

## Policy

| Direction | Allowed |
|-----------|---------|
| Markdown → ALM | Yes (create/update mirror tickets) |
| ALM → Markdown | Manual pull only; never auto-overwrite BACKLOG |
| Gate sign-offs in ALM | **No** — gates stay in `todo/gates/` |

## ID mapping

| Markdown | Jira / Linear |
|----------|---------------|
| `SPINE-123` | Story/Task title prefix or custom field |
| Epic block | Epic link |
| INIT-### | Initiative / Theme |

## Title convention

```
[SPINE-123] Short description matching BACKLOG row
```

## Export (one-way)

From fc-sdlc package root (path to your `fc-sdlc` clone):

```bash
node fc-sdlc/bridges/atlassian/scripts/export-backlog.mjs --workspace .
```

Outputs `docs/product/jira-export-YYYY-MM-DD.json` for manual import or API batch create.

## When to mirror

- Team visibility in existing Jira boards
- Cross-team dependencies outside git repo
- Compliance audit trail (supplement, not replace gate files)

## When not to mirror

- Gate Go/No-go decisions
- STATUS.md metrics
- Reality audit ratings
- Sprint cleanup reports
