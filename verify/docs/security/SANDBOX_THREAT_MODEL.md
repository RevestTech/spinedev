# Sandbox Threat Model

> Last updated: 2026-04-24 (P0 #14 hardening pass)

Tron's sandbox runs payloads we do not trust — verification snippets generated
by LLMs, PoC exploits for discovered findings, and occasionally user-supplied
snippets from the admin UI. The container boundary is the only thing keeping
that code off the worker host, the audit database, and the rest of the
docker network. This document is the ground truth for what the boundary is
supposed to stop and how.

## In scope — what we defend against

The assumed adversary is **arbitrary code running inside a sandbox container**:
it controls the full Python or bash process, can allocate memory, call syscalls,
fork, open files under the container view, and make outbound network attempts.

Specifically, the boundary must:

- **Prevent filesystem escape** off the container's own rootfs onto the worker
  host. No writes to `/var/run/docker.sock`, `/etc`, the worker's code, or
  anything outside the caller-provided volumes.
- **Prevent network egress** to the public internet, to other docker
  services, or to the worker host's loopback — unless the caller explicitly
  requested `network_mode="bridge"` for the (rare) outbound-HTTPS analysis
  path.
- **Prevent resource exhaustion** from killing the worker: fork bombs, memory
  bombs, disk-fill attacks against tmpfs, FD exhaustion.
- **Prevent capability escalation** via setuid binaries, new privileges from
  sub-processes, or kernel-feature abuse.
- **Prevent information leak** of the host's hostname, PID namespace, or IPC
  primitives to a payload that can exfiltrate via other channels.

## Out of scope — what the sandbox is NOT

- Not a substitute for trusted-code review. A payload that "just runs" is not
  automatically safe to merge.
- Not a defence against a malicious *worker process* — the sandbox is only as
  trustworthy as the code that calls `SandboxClient`. If the caller is
  compromised it owns the Docker socket and can escape.
- Not a shield against shared-kernel vulnerabilities (container escapes via
  kernel bugs like CVE-2022-0185). Defence here is kernel patching and
  seccomp, not sandbox config.
- Not a privacy boundary: stdout/stderr are returned to the caller in full.
- Not rate-limited by itself — upstream callers must cap concurrent
  executions. The sandbox server has a `pids_limit` per container but the
  number of *containers* is bounded only by the caller.

## Defence-in-depth inventory

Every container launched by `tron/services/sandbox_client.py::SandboxClient`
carries the kwargs in `_hardened_run_kwargs`. Both `run_python` and
`run_bash` route through that single helper — there is intentionally no
second code path that could drift.

| Flag | Value | What it stops |
|------|-------|---------------|
| `network_mode="none"` (default) | no NIC | Any egress, lateral moves |
| `network_disabled=True` (when none) | belt-and-braces on libnetwork | Races where netns is created but mode not applied |
| `cap_drop=["ALL"]` | no Linux caps | CAP_SYS_ADMIN tricks, raw sockets, ptrace, etc. |
| `security_opt=["no-new-privileges:true"]` | blocks setuid | Re-escalating via `su`, `sudo`, setuid binaries |
| `read_only=True` | immutable rootfs | Persisting tooling, corrupting the base image |
| `tmpfs={"/tmp": "size=10M,mode=1777"}` | writable scratch capped | Disk-fill on the host; tools that need `/tmp` still work |
| `user="65534:65534"` | runs as `nobody:nogroup` | Root-only syscalls, file ownership on bind mounts |
| `pids_limit=64` | max 64 procs | Fork bombs |
| `ulimits` fsize=10 MiB, nofile=128/256 | kernel-enforced | Writing a huge core dump, FD exhaustion |
| `mem_limit` / `memswap_limit` equal | no swap | Memory-bomb worst case, swap-thrashing side channel |
| `cpu_quota` | 0.5 CPU default | CPU exhaustion |
| `ipc_mode="private"` | new IPC ns | shm_open lateral between sandboxed siblings |
| `hostname="tron-sandbox"` | fixed label | Leaking the worker's hostname into payload logs |
| `environment={"HOME":"/tmp", "PYTHONDONTWRITEBYTECODE":"1"}` | writes only hit tmpfs | Requires read-only rootfs to actually hold |
| `remove=True` | auto-GC on exit | Orphan containers piling up with payload state |
| `_ALLOWED_NETWORK_MODES` allowlist | at call time | Caller passing `"host"` or `"container:..."` |

### Network-mode allowlist

`network_mode` is explicitly validated at the Python layer before any
container is created:

```python
_ALLOWED_NETWORK_MODES = frozenset({"none", "bridge"})
```

- **`none`** (default). No NIC inside the container, nothing to route against.
- **`bridge`**. Standard Docker NAT bridge. Used by the Layer-3 audit path
  that needs to reach a configured allowlist of outbound HTTPS endpoints.
  `network_disabled` is *not* set in this mode by design.

Anything else — `host`, `container:<id>`, a custom name — is rejected with
`ValueError` before `containers.run()` is called. The sandbox HTTP server
duplicates this check in `ExecuteBody` so bad input dies at the edge with a
422, not deeper in the stack.

## Enabling gVisor (optional, stronger isolation)

The default `SANDBOX_RUNTIME=runc` uses the standard Docker runtime.
That's adequate alongside the seccomp profile, dropped capabilities,
and read-only rootfs documented above. Operators who need stronger
isolation — e.g. running Tron as a multi-tenant audit service for
mutually distrustful customers — can opt into gVisor for the sandbox
container only:

1. Install `runsc` on the host (`https://gvisor.dev/docs/user_guide/install/`).
2. Register it as a Docker runtime in `/etc/docker/daemon.json`:
   ```json
   { "runtimes": { "runsc": { "path": "/usr/local/bin/runsc" } } }
   ```
   Restart the Docker daemon.
3. Set `SANDBOX_RUNTIME=runsc` in `.env` for the worker / sandbox
   process.
4. Confirm with `docker info | grep -i runtime` that `runsc` is listed.

Performance cost: ~10–30% slower per syscall on the gVisor side
(the user-space kernel intercepts everything). For Python workloads
under the existing 10s timeout, this is usually invisible. We don't
default to gVisor because requiring `runsc` on every dev machine
would block out-of-the-box installs.

## Known gaps and follow-ups

These are the residual risks the current hardening does *not* mitigate:

1. **Docker socket trust.** The sandbox service itself must hold
   `/var/run/docker.sock`. A compromise of that process is a full host
   takeover. Mitigation on the roadmap: move to `--userns-remap` or
   rootless Docker, then drop more caps from the sandbox service itself.
2. **Shared kernel.** Container boundaries rely on kernel namespaces and
   cgroups. A kernel-local-privesc bug will still escape. Mitigation: keep
   the worker host on a patched LTS kernel, monitor CVE feeds for
   namespace/cgroup issues, add a seccomp profile stricter than the
   Docker default in a follow-up.
3. **No gVisor / Firecracker.** User-space kernel isolation (gVisor) or a
   light VM (Firecracker) would close both gaps 1 and 2 but has cost and
   language-compat tradeoffs. Not in scope for this pass.
4. **Volumes are trust-forwarding.** Anything the caller bind-mounts in
   becomes accessible to the payload, at the container user's UID. Callers
   must treat bind-mounted paths as if the payload wrote to them.

## Verification

- `tests/unit/test_sandbox_client_hardening.py` asserts every flag above is
  passed through `containers.run(...)` for both code paths, and that
  disallowed `network_mode` values raise.
- `tests/unit/test_sandbox_server_request_validation.py` asserts the HTTP
  layer rejects `host` / `container:...` with a 422 before reaching
  `SandboxClient`.
- Bandit and Ruff run against `tron/services/sandbox_client.py` in CI with
  the documented `# nosec B108` suppressions pinned to the specific tmpfs
  mount lines.

If you are changing any hardening flag, update both this document and the
tests in the same PR. Drift between doc and code is how regressions land.
