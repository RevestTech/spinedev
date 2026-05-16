# `backlog_to_jira_csv.py` — Export `docs/BACKLOG.md` to PM-tool CSV

> Implements `STORY-5.3.1` in `docs/BACKLOG.md`. Lets Spine move from the canonical text backlog to a live PM tool (Jira, Linear, GitHub Issues) when ready, without making the backlog stop being the source of truth. Cross-ref: `docs/research/COMPETITIVE_LANDSCAPE.md §4 Tier-cross-cutting`, `STORY-5.3.2` (bi-directional sync, future).

## Why this script exists

`docs/BACKLOG.md` is the canonical product backlog because it's diff-friendly, code-review-friendly, and never goes down. But once the team grows past one or two people, you want a real issue tracker — assignees, comments, sprints, burndowns. This script bridges the two:

- **Stays one-way (canonical→tool)** in v1. The backlog drives, the tool reflects.
- **Idempotent.** Re-running with the same backlog produces the same CSV; re-importing produces the same issues (matched on Spine story ID via the `External ID` / `Identifier` field).
- **Stdlib only.** Python 3.11+, `csv` + `re` + `argparse` + `pathlib`. No pandas, no Jira SDK, nothing to install.
- **Multi-format.** Jira (default), Linear, GitHub Issues.

## Usage

```bash
# Default — Jira CSV of every non-Done story
python3 tools/backlog_to_jira_csv.py \
    --backlog docs/BACKLOG.md \
    --output backlog.csv

# Just INIT-1 (Plan subsystem), Done items included
python3 tools/backlog_to_jira_csv.py \
    --init-filter 1 \
    --include-done \
    --output plan_subsystem.csv

# Linear-flavored CSV for one EPIC
python3 tools/backlog_to_jira_csv.py \
    --epic-filter 1.4 \
    --format linear \
    --output approval_gates.csv

# GitHub Issues format (title/body/labels/state)
python3 tools/backlog_to_jira_csv.py \
    --format github \
    --output github_issues.csv
```

## Field mapping

### Status (Spine → Jira)

| Spine `BACKLOG.md` | Jira `Status` |
|---|---|
| `Backlog` | `To Do` |
| `In Design` | `To Do` |
| `In Progress` | `In Progress` |
| `Done` | `Done` |
| `Won't Do` | `Won't Do` |

### Priority

| Spine | Jira |
|---|---|
| `P0` | `Highest` |
| `P1` | `High` |
| `P2` | `Medium` |
| `P3` | `Low` |

### Size → Story Points

`XS=1 · S=2 · M=5 · L=13 · XL=21` (standard Fibonacci-ish scale).

### Parent

Stories inherit `EPIC-N.M`; epics inherit `INIT-N`; initiatives have no parent.

### Labels

- The item type: `initiative` / `epic` / `story`.
- Inherited tier from parent INIT (e.g., `tier-1`, `tier-2`, `tier-foundational`).
- Sprint tag if the story appears in the `## Sprint Plan` section at the top of `BACKLOG.md` (e.g., `sprint-1`).

## Importing to Jira

1. In your Jira project: **Project Settings → System → External System Import → CSV**.
2. Upload `backlog.csv`. Jira parses headers automatically.
3. Map columns: leave defaults; map `External ID` to Jira's external-ID field for idempotent re-import.
4. Map `Parent` to the parent-link field (Jira's name varies by project type — `Epic Link` in company-managed, `Parent` in team-managed).
5. Map `Sprint` to the Sprint custom field if present.
6. Preview and import.

Reference: [Jira Cloud — Import data from a CSV file](https://support.atlassian.com/jira-cloud-administration/docs/import-data-from-a-csv-file/).

## Linear

Linear has no native CSV bulk-import API for arbitrary projects, but the [Linear Importer](https://linear.app/docs/importing-issues) accepts a CSV with the columns `Title, Description, Status, Priority, Estimate, Labels, Parent Issue, Cycle, Identifier`. Pass `--format linear`. The `Identifier` column is reused as the external ID on re-import.

## GitHub Issues

Pass `--format github`. Output columns: `title, body, labels, state`. Pipe into [`gh issue create`](https://cli.github.com/manual/gh_issue_create) via a small wrapper:

```bash
python3 tools/backlog_to_jira_csv.py --format github --output gh.csv
python3 -c "
import csv, subprocess
for r in csv.DictReader(open('gh.csv')):
    subprocess.run(['gh','issue','create','--title',r['title'],
                    '--body',r['body'],'--label',r['labels']], check=True)
"
```

## Idempotency

Spine story IDs (`STORY-N.M.K`) are stable forever (see `BACKLOG.md` conventions). The script writes them into `External ID` (Jira) or `Identifier` (Linear) so re-importing **updates** existing issues instead of duplicating them. The only path to a duplicate is if you rename a Spine ID — don't.

## Future work — `STORY-5.3.2` (bi-directional sync)

When Spine actually picks a PM tool, follow up with `STORY-5.3.2`: status edits in Jira / Linear should reflect back into `BACKLOG.md` (or vice versa). v1 is one-way on purpose — sync mechanics add a lot of edge cases and we don't have the user demand yet.

## Cross-references

- `STORY-5.3.1` in `docs/BACKLOG.md`
- `docs/BACKLOG.md` — canonical product backlog (the input)
- `docs/research/COMPETITIVE_LANDSCAPE.md` — *why* the Jira bridge exists
- `docs/positioning.md` — Spine positioning narrative
