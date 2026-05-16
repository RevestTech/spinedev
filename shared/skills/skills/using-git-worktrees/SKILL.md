# Skill — using git worktrees for parallel work

You are about to dispatch parallel workers that will touch the codebase.
Stop running them in scratch dirs. **Provision a `git worktree` per
worker** so each one gets a real branch, real history, and a real path
home through a PR. Scratch dirs were the old Spine pattern; they lose
git state, fight each other on merges, and drift from `main` the moment
a worker takes longer than a coffee break.

## The pattern in one sentence

`git worktree` creates an isolated working tree from the *same* repo —
each worker gets its own checkout dir and its own branch, but they all
share one `.git` and one history. No clone cost, no sync drift, and
cleanup is one command.

## Step-by-step

1. **Create the worktree** (sibling to the main checkout, named for the
   worker):
   ```bash
   git worktree add ../spine-worker-01 -b feat/worker-01-<slug> main
   ```
   This drops a fresh working tree at `../spine-worker-01/` on a new
   branch `feat/worker-01-<slug>` based on `main`.

2. **Hand the path to the worker.** Worker `cd`s into
   `../spine-worker-01/` and runs as if it owned the repo. It commits
   freely to its own branch; commits are visible to everyone (shared
   `.git`).

3. **Wait for completion.** Worker reports done with its branch name
   and any open PR.

4. **Clean up** when merged or abandoned:
   ```bash
   git worktree remove ../spine-worker-01
   git branch -D feat/worker-01-<slug>   # only if not merged via PR
   ```

5. **Merge** via a normal PR review (preferred) or `git merge
   feat/worker-01-<slug>` from `main` if the worker's branch is trusted
   and small. PR path is the default — it preserves the audit trail the
   auditor expects.

## Why this beats scratch dirs

- **Real git state per worker.** A worker can commit, push, and rebase
  inside its worktree. Scratch dirs gave you a pile of files with no
  history; the conductor had to manually `git add` the deltas and lost
  attribution.
- **Easy cleanup.** `git worktree remove` is one command; scratch-dir
  cleanup was an `rm -rf` that occasionally took the wrong directory.
- **No file conflicts between workers.** Each worktree is a separate
  directory — workers can edit "the same file" without trampling each
  other; reconciliation happens at merge time, where it belongs.
- **PR-able from the worker branch.** No copy step, no rebase dance —
  the worker's branch *is* what gets reviewed.

## When NOT to use

- **Single-file edits.** Provisioning a worktree to change one line is
  overkill — let the worker run in-place.
- **Read-only workers.** If the worker only reads (research,
  investigation, KG queries), no worktree needed.
- **Disk-constrained environments.** Each worktree is a full checkout.
  On a 5GB repo with 8 workers, that's 40GB. Use worktrees only when
  the disk math works.

## Spine integration

`build/daemons/team-agent-daemon.sh` (and any future dispatcher) should
provision a worktree per parallel worker when **both** are true:
(a) workers_count ≥ 2, and (b) the directive scope includes code
changes. A read-only swarm (e.g. Tech Review Swarm in `plan/swarm/`)
does not need worktrees — its workers only read.

Naming convention: `../spine-worker-<NN>` for the dir,
`feat/worker-<NN>-<task-slug>` for the branch. The conductor that
dispatched the swarm tracks the mapping in the dispatch log so cleanup
is mechanical.

## Cross-refs

- `REQ-INIT-7 §7.5 FR-1` — parallel worker isolation requirement
- `obra/superpowers` — `using-git-worktrees` skill (pattern origin)
- `build/daemons/team-agent-daemon.sh` — dispatch site that should
  provision worktrees
- `plan/swarm/swarm_engine.py` — read-only swarms that intentionally
  *skip* this skill
