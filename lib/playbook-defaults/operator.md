# Operator playbook — default lessons (seeded on install)

These are infrastructure / Docker / deploy gotchas accumulated across
projects. Each lesson is one-line followed by the "why" so a future agent
can apply the rule with appropriate edge-case judgment.

## Docker on macOS

- **2026-05-07 — Single-file bind mounts on macOS Docker Desktop break when the host file is rewritten via atomic-write.** Editors (VSCode, JetBrains, vim default) save by writing a temp file then renaming over the target. The rename gives the new file a different inode. Docker's single-file bind mount is locked to the *original* inode at mount time, which is now unlinked — so the file appears DELETED inside the container even though it's right there on the host. Fix: mount the parent DIRECTORY instead (`./frontend:/app/frontend:ro`), not the individual file. Affects only macOS; Linux Docker handles inode-vs-path differently.

- **2026-05-07 — `docker compose restart` does NOT pick up `.env` changes.** It just restarts the same process inside the existing container with the env vars baked in at create time. To re-read `.env`, use `docker compose up -d --force-recreate <service>` (and `--no-deps` if you don't want dependencies dragged along).

- **2026-05-07 — `host.docker.internal` works on Mac Docker Desktop but the host needs `0.0.0.0` binding.** A service listening on `127.0.0.1:PORT` on the Mac is NOT reachable from a container via `host.docker.internal:PORT` because the loopback interface is host-only. Set the service to bind on `0.0.0.0` (or `*`) so the Docker bridge can reach it.

- **2026-05-07 — Docker for Mac does not pass through Metal/GPU.** Containers cannot access the Mac's GPU. For LLM inference at decent speed, the LLM service must run on the host (brew install + `brew services start ollama`), not inside Docker. Docker containers reach it via `host.docker.internal:11434` after the binding is fixed (above).

## Apps that respawn themselves

- **2026-05-07 — Killing macOS GUI apps that have a watchdog respawns them instantly.** Some macOS apps (Ollama.app among them) launch a daemon that auto-restarts the binary if killed. To stop them permanently: remove the binary FIRST, then kill the process. The watchdog's re-exec then fails. Don't forget to also remove the LaunchAgent (`~/Library/LaunchAgents/`), Login Item (`osascript -e 'tell application "System Events" to delete login item "X"'`), and Application Support config to prevent next-boot respawn.

## Compose hygiene

- **2026-05-07 — Hardcoded env values in compose silently override `.env`.** When the same key appears in `service.environment:` as a literal AND in `.env`, the literal wins. To respect `.env` while keeping a sensible default, use `KEY: ${KEY:-default-value}`. Comments don't substitute for actual env-var indirection.

- **2026-05-07 — `docker compose up -d --force-recreate worker` brings dependencies back up too.** If you stopped a depended-on service intentionally, recreating a service that depends_on it will bring it back. Use `--no-deps` to recreate only the named service.

- **Volumes "in use" prevent removal.** A stopped container still references its volumes. To remove volumes: `docker compose rm -f <service>` first, then `docker volume rm <volume-name>`. Or directly `docker rm -f <container-id>`.

## Profiles for opt-in services

- **Use compose profiles to gate services that aren't always wanted.** Default-off services should set `profiles: ["some-profile"]`. They won't start on `docker compose up -d` unless explicitly requested with `--profile some-profile`. Useful for fallbacks (e.g. in-Docker LLM when host-side LLM isn't installed) and for environment-specific services.

## Macros and scripts

- **`make team-status` / equivalent should be the single "is everything alive?" command.** When a script's output starts to fall behind reality (e.g. daemons died but no one noticed), audit the status command first. If it says "everything is fine" while reality is broken, fix the status command before fixing anything downstream.

## Cleanup defaults

- **iCloud-synced folders (`~/Documents`, `~/Desktop`) are hostile to large local-only data.** macOS will silently evict files, sync conflicts, and produce `EDEADLK` ("resource deadlock avoided") errors. Use `~/.config`, `~/.local`, `~/.<app>` for ML model weights, Docker volumes, and similar. Some apps default to bad locations on first launch — verify and override.

## Long-running batch jobs (the 25-minute timeout trap)

- **2026-05-08 — The team-agent-daemon's 25-min hard timeout (`INVOCATION_TIMEOUT_S=1500`) kills any single agent invocation that runs longer.** Default appropriate for normal directives; wrong for batch jobs (full-archive labeling, large training runs, per-doc enrichment of thousands of docs). Symptoms: agent reports `rc=0` but the directive output is incomplete or absent — cursor-agent exits cleanly under SIGTERM. For batch directives, override per-process: `INVOCATION_TIMEOUT_S=5400 nohup bash scripts/team-agent-daemon.sh <role> manager &`.

- **2026-05-08 — A daemon that's been killed silently is invisible without the watchdog.** Pre-v1.3 installs have no auto-restart. After bumping a timeout for batch work, also `bash scripts/team.sh status` periodically to confirm the daemon is still alive. v1.3+ projects: install the watchdog (`scripts/watchdog.sh`) which detects heartbeat staleness and re-launches dead managers.

- **Design batch scripts to be resumable from checkpoint.** A long batch that dies near the end is wasted effort if the script can't pick up where it left off. Pattern: write per-N-row checkpoint markers to a file; on script start, read the checkpoint and skip already-processed rows. An auto-labeling run that survives a daemon restart is the proof this works.

- **Schedule batch jobs around macOS sleep.** A laptop that sleeps mid-batch loses the host-side LLM, the worker container, AND any file-bus daemon running on the host. For overnight runs, set `pmset -a sleep 0` (Mac plugged in, no sleep) before kicking off, restore after. Or run on a desktop / server that doesn't sleep.
