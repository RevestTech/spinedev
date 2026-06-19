# System Requirements

> **Pre-v3 document — preserved for historical context.** This file describes the host
> requirements for the v1/v2 file-bus orchestration framework (running bash daemons on
> macOS/Linux/WSL2). The v3 product is a containerized **Hub** with a different deployment shape
> (per [`docs/V3_DESIGN_DECISIONS.md`](../V3_DESIGN_DECISIONS.md) **#17**). For current
> deployment requirements see [`docs/DEPLOYMENT_SHAPES.md`](../DEPLOYMENT_SHAPES.md) and
> [`docs/HUB_OPERATIONS_GUIDE.md`](../HUB_OPERATIONS_GUIDE.md); for launch readiness see
> [`docs/V1_SHIP_CHECKLIST.md`](../V1_SHIP_CHECKLIST.md).

What your computer needs to run SpineDevelopment.

> **TL;DR.** macOS or Linux: works out of the box if you have git + bash + curl + an AI CLI (Cursor, Claude Code, Aider, OpenCode). Windows: use WSL2. Run `bash scripts/preflight.sh` after install for a per-host report.

---

## Platforms

| Platform | Status | Notes |
| --- | --- | --- |
| **macOS** (12+) | **Fully supported** | Tested. Daemon, watchdog, scratch dirs, file locks, native notifications all work. Recommended: `brew install bash coreutils` for bash 4+ and gtimeout. |
| **Linux** (any modern distro) | **Fully supported** | Tested on Ubuntu 22.04. Daemon and all helpers work natively. `notify-send` for desktop notifications optional. |
| **Windows 10/11 via WSL2** | **Fully supported** | Recommended Windows path. Install WSL2 + Ubuntu, then run installer inside WSL like Linux. Phone notifications via ntfy.sh / Slack / Discord work the same. |
| **Windows native (Git Bash / MSYS2)** | **Partial** | Most scripts run; backgrounding via `nohup` is flaky; `pgrep` and process-supervision pieces don't all work. Use only if WSL2 isn't an option. |
| **Windows native (PowerShell)** | **Not yet** | A native PowerShell port would be ~800–1000 lines of new code. Not done. PRs welcome. |

**Recommendation for Windows users:** install WSL2. It takes 5 minutes (`wsl --install` from an admin PowerShell, reboot, install Ubuntu from the Microsoft Store), and after that you get a real Linux environment where the entire template runs unchanged.

---

## Required tools

Without these, the team cannot start. The installer's preflight will refuse to proceed if any are missing.

| Tool | Why | Install (macOS) | Install (Linux) | Install (WSL/Windows) |
| --- | --- | --- | --- | --- |
| `bash` 3.2+ | Shell. macOS ships 3.2; Linux ships 5+. Bash 4+ recommended. | `brew install bash` (optional upgrade) | preinstalled | preinstalled in Ubuntu |
| `git` | Engineer rollback snapshots, repo state | `brew install git` | `apt install git` | `apt install git` |
| `curl` | Webhook-based notifications | preinstalled | `apt install curl` | `apt install curl` |
| `tar` | Untracked-file rollback archives | preinstalled | `apt install tar` | preinstalled |
| `find`, `awk`, `sed`, `grep` | Standard text/file utilities | preinstalled | preinstalled | preinstalled |
| `pgrep` | Daemon process detection (`team status`, watchdog) | preinstalled | `apt install procps` | `apt install procps` |
| `shasum` *or* `sha256sum` | Content-hash change detection | preinstalled (macOS has shasum) | `sha256sum` is in coreutils; `shasum` in `libdigest-sha-perl` | preinstalled |
| `ln` | Atomic file-lock helper | preinstalled | preinstalled | preinstalled |

**An AI CLI** — at least ONE of:

| CLI | Install | Notes |
| --- | --- | --- |
| **Cursor Agent** (`cursor-agent`) | Comes with Cursor IDE — <https://cursor.com> | What this template was originally built against. Recommended. |
| **Claude Code** (`claude`) | `npm i -g @anthropic-ai/claude-code` | Anthropic's official CLI. |
| **Aider** (`aider`) | `pip install aider-chat` | Strong git-aware refactoring CLI. |
| **OpenCode** (`opencode`) | <https://opencode.ai> | Open-source. |
| **Codex** (`codex`) | <https://github.com/openai/codex-cli> | OpenAI's CLI. |
| **Custom** | set `EXECUTOR_CMD=/path/to/your-cli` | Any CLI that takes a prompt argument. |

The daemon auto-detects the first one found in the order above. To force a specific one set `EXECUTOR_KIND=cursor|claude|aider|opencode|codex` or `EXECUTOR_CMD=...` in your shell.

---

## Recommended tools

These produce a degraded experience when missing, but the team still runs.

| Tool | What you lose without it | Install (macOS) | Install (Linux) |
| --- | --- | --- | --- |
| `gtimeout` / `timeout` | Hard-timeout enforcement on agent invocations. Without this, a hung agent runs forever. | `brew install coreutils` (provides `gtimeout`) | `apt install coreutils` |
| `osascript` (macOS) | macOS notification banners | preinstalled | n/a |
| `notify-send` (Linux) | Linux desktop notifications | n/a | `apt install libnotify-bin` |
| `mail` | Email notifications via `NOTIFY_EMAIL_TO` | requires postfix configured | `apt install mailutils` |

---

## Optional integrations (for phone pings)

Set any of these env vars in your shell rc (`~/.zshrc` / `~/.bashrc`) to enable that notification channel. None are required, but at least ONE is strongly recommended for overnight/unattended runs.

| Variable | Channel | Setup time |
| --- | --- | --- |
| `NTFY_TOPIC` | ntfy.sh push to phone | ~60 seconds. Install ntfy app, pick a hard-to-guess topic, subscribe. No signup. |
| `SLACK_WEBHOOK` | Slack channel | ~3 minutes. Slack → Apps → Incoming Webhooks → create. |
| `DISCORD_WEBHOOK` | Discord channel | ~3 minutes. Server settings → Integrations → Webhooks → New. |
| `PUSHOVER_TOKEN` + `PUSHOVER_USER` | Pushover push | ~5 minutes + $5 one-time. pushover.net signup, install app, generate app token. |
| `NOTIFY_EMAIL_TO` | Email | depends on `mail` CLI being functional. |

Verify your setup with:

```bash
bash scripts/team.sh notify-test
```

---

## What the daemon actually invokes

Every directive triggers one invocation of the AI CLI. The daemon writes the full prompt (role-prompt + memory + directive + tier guidance + hygiene block) to a temp file, then calls:

```bash
bash lib/executor.sh /tmp/spine-prompt-XXXXXX
```

`executor.sh` knows how to invoke each supported CLI:

| CLI | Invocation pattern |
| --- | --- |
| `cursor-agent` | `cursor-agent "<prompt>"` |
| `cursor` | `cursor "<prompt>"` |
| `claude` | `claude -p "<prompt>"` |
| `aider` | `aider --message "<prompt>" --yes --no-pretty` |
| `opencode` | `opencode "<prompt>"` |
| `codex` | `codex "<prompt>"` |
| `EXECUTOR_KIND=generic` | pipes prompt to stdin of `$EXECUTOR_CMD` |

The temp prompt file is deleted after the invocation completes (success or failure).

---

## Network requirements

- Outbound HTTPS to your AI provider (Cursor, Anthropic, OpenAI, etc) — depends on which CLI you chose.
- Outbound HTTPS to `ntfy.sh`, `hooks.slack.com`, `discord.com`, or `api.pushover.net` if you've armed those channels.
- No inbound ports needed — the team is fully file-bus driven.

---

## Resource footprint (idle and active)

- **Idle (`N` manager daemons + `10×N` worker slots polling):** scales with `scripts/roles.sh` (~low tens of MB RAM baseline, \< 2% CPU on modern laptops).
- **Per active agent invocation:** depends entirely on the AI CLI you use (Cursor uses ~200 MB, Claude Code uses < 100 MB, Aider uses ~50 MB).
- **Disk:** logs are auto-rotated at 5 MB each; total team footprint stays under 200 MB unless `clean archive` is overdue.

---

## Verifying everything works

For a **full** install, three commands:

```bash
bash scripts/preflight.sh   # or: make team-preflight (after Makefile is wired)
make team-up
make team-doctor
```

**Knowledge-only** installs (`install.sh ... --pull-knowledge-only`) intentionally skip preflight — run `preflight`/`team-doctor` only after you have `scripts/` on disk from a full install.

If preflight passes, `team-up` succeeds, and `team-doctor` is clean, drop a directive into a role's `directive.md` and watch it work.

## Pull knowledge without replacing daemons

Existing projects can refresh protocol, recipes, practice docs, ADR scaffolds, and `role-prompt.md` files from the SpineDevelopment package **without** overwriting `scripts/*.sh` or the dashboard:

```bash
bash /path/to/SpineDevelopment/install.sh /path/to/your-repo --pull-knowledge-only
```

Optional: add `--force` to replace in-repo customized copies of recipes or role prompts.

---

## Troubleshooting common host issues

**`bash: command not found: pgrep`** (some minimal Linux containers)
→ `apt install procps`

**Daemon starts but `team doctor` says "no AI CLI found"**
→ The CLI is on your PATH for your interactive shell but not for background processes. Add the export to `~/.bashrc` or `~/.zshrc` (not `~/.bash_profile`).

**macOS Notification Center pings don't appear**
→ System Settings → Notifications → Script Editor → Allow Notifications. Or use ntfy.sh which doesn't need permissions.

**Watchdog keeps restarting a manager every 5 minutes**
→ The daemon is starting but exiting before it touches its heartbeat file. Check `teams/<role>/log/daemon.log` for crashes. Most common cause: AI CLI is misconfigured (e.g. needs an API key the daemon can't see).

**Agent can't see env vars I set in my shell**
→ Daemons are launched with `nohup` from `team up`. Env vars set after that don't reach them. Set vars in `~/.zshrc` / `~/.bashrc` and run `team restart`.
