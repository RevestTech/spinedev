# Recipe — Wiring host-side LLMs into Dockerized workers (operator + engineer)

For the increasingly common pattern: **AI inference needs GPU/Metal acceleration, the rest of your stack runs in Docker**. On macOS this is a hard constraint (Docker for Mac cannot pass through Metal/GPU), so the LLM service MUST run on the host while everything else stays containerized. This recipe codifies the moves needed to wire that cleanly.

Captured from a production **OCR / host-side LLM** migration where inference had to leave Docker (GPU/Metal) while the rest of the stack stayed containerized. Intended to turn multi-hour debugging into a repeatable checklist.

---

```markdown
# Directive — Move <LLM service> from Docker to host-side <Metal/CUDA> for <PROJECT>

## Tier hint: low

## Why now
<one paragraph: which inference is slow today, what the wall-clock penalty is,
why moving to host-side will help. Include real numbers if you have them —
e.g. "30s/doc CPU-only in Docker → 2.5s host-side Metal, ~12× speedup">

## Architecture move

The LLM service moves from `docker compose --profile <X> up -d <llm>` (CPU-only,
inside Docker) to a host-native installation (Metal/CUDA-accelerated, outside Docker).

Workers in Docker reach the host-side service via `host.docker.internal:<port>`.
The Docker version of the service stays in compose under a profile so it can be
the fallback for environments without a host-side install (Linux servers, CI).

## The seven moves (run in this order, do not skip)

### 1. Verify the platform supports host-side acceleration
- macOS Apple Silicon: `system_profiler SPHardwareDataType | grep "Chip"` → must show M-series.
- Linux with NVIDIA: `nvidia-smi` → must show a GPU.
- Anything else: this recipe doesn't apply; either accept CPU performance or use cloud inference.

### 2. Install the LLM service host-side
- macOS: `brew install <service>` (Ollama, llama.cpp, vLLM-via-uv)
- Linux: package manager or pre-built binary; do NOT `pip install` into the system Python.
- After install, **disable any auto-launch** that competes with the brew/native version (see #3).

### 3. Hunt and disable competing instances
The LLM service may already be running from a different install path:
- macOS GUI app: `/Applications/<Service>.app` — drag to Trash AFTER killing the daemon (the watchdog respawns it instantly otherwise — kill the binary first, then the process)
- LaunchAgents: `~/Library/LaunchAgents/com.<service>*.plist`, `~/Library/LaunchAgents/ai.<service>*.plist` — `launchctl unload` then `rm`
- Login Items: `osascript -e 'tell application "System Events" to delete login item "<Service>"'`
- Application Support: `rm -rf ~/Library/Application\ Support/<Service>`

If the model files were stored under iCloud-synced folders (`~/Documents`, `~/Desktop`),
move them to `~/.<service>/` to avoid `EDEADLK` errors during writes.

Verify nothing's listening on the target port before proceeding:
```
lsof -i :<port>  # should be empty
```

### 4. Configure the service to bind on 0.0.0.0
The service MUST listen on all interfaces so Docker containers can reach it via
`host.docker.internal`. Loopback-only (`127.0.0.1`) does NOT work.

For Ollama via brew:
```bash
launchctl setenv OLLAMA_HOST "0.0.0.0:11434"
# OR persistent across reboot — edit ~/Library/LaunchAgents/homebrew.mxcl.<service>.plist:
/usr/libexec/PlistBuddy -c "Add :EnvironmentVariables:OLLAMA_HOST string 0.0.0.0:11434" "$PLIST"
brew services restart <service>
```

Verify:
```
lsof -i :<port>
# Must show *:<port> or 0.0.0.0:<port>, NOT localhost:<port>
```

### 5. Pull the model into the standard cache location
Default is `~/.<service>/models/` or similar. Confirm the path is NOT inside
an iCloud-synced directory. Pull the model. Do a cold-start warmup so the
model loads into RAM (this can take 30-120s on first call for a 5-7GB model).

### 6. Update worker config to use `host.docker.internal`
Two changes in your repo:

(a) `.env` — point the URL at the host:
```
<SERVICE>_URL=http://host.docker.internal:<port>
```

(b) `docker-compose.yml` — make the value respect `.env`. If the value was
hardcoded:
```yaml
environment:
  <SERVICE>_URL: http://<service-name>:<port>   # OLD — overrides .env
```
change to:
```yaml
environment:
  <SERVICE>_URL: ${<SERVICE>_URL:-http://<service-name>:<port>}  # respects .env, falls back to default
```

### 7. Recreate (not restart) the worker
Critical — `docker compose restart` does NOT pick up `.env` changes. Use:
```bash
docker compose up -d --force-recreate --no-deps <worker-service>
```

`--no-deps` prevents the dependency-graph from bringing the in-Docker LLM
back up. Verify the worker container sees the new URL:
```bash
docker exec <worker-container> sh -c 'echo $<SERVICE>_URL'
# Expected: http://host.docker.internal:<port>
```

### 8. Verify connectivity from inside the worker
The worker container probably doesn't have curl. Use Node or whatever the
worker runtime is:
```bash
docker exec <worker> node -e "
fetch('http://host.docker.internal:<port>/api/version').then(r=>r.text()).then(t=>console.log('OK:',t))
  .catch(e=>console.log('FAIL:',e.message,'cause:',(e.cause||{}).code))"
# Expected: OK: {"version":"X.Y.Z"}
```

If this fails:
- DNS not resolving → add `extra_hosts: ["host.docker.internal:host-gateway"]` to the worker service
- Connection refused → confirm step 4 (binding on 0.0.0.0)
- Connection blocked → check macOS firewall: `sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add /opt/homebrew/opt/<service>/bin/<binary>`

### 9. Profile-gate the in-Docker fallback
The Docker version of the service should stay in compose for environments
that need it (Linux CI, fresh laptops without host install), but DEFAULT
behavior should use host-side. Add a profile:
```yaml
<service>:
  profiles: ["docker-llm"]    # only starts when explicitly requested
  image: <service>/<service>:latest
  ...
```

Now `docker compose up -d` doesn't start the in-Docker LLM. To opt in:
```bash
docker compose --profile docker-llm up -d <service>
```

Also remove `<service>` from any `depends_on` blocks of services that no
longer NEED the in-Docker version. Otherwise compose validation will fail.

### 10. Reclaim the duplicate model storage
The Docker volume holding the model is now duplicate (host-side cache has
its own copy). After confirming the host-side path works for ~24h:
```bash
docker compose rm -f <service>   # remove the stopped container so volume isn't "in use"
docker volume rm <project>_<service>_data
```

## Stop conditions
- Step 4 (binding on 0.0.0.0) doesn't work — the service refuses to bind on
  all interfaces. STOP and report. Some services have hardcoded localhost-only;
  workaround is socat or nginx as a port forwarder.
- Step 8 (worker can reach it) fails after binding is verified — likely a
  macOS firewall or Docker Desktop networking config. STOP and report.
- The service has features that ONLY work in-Docker (e.g. integrations
  with other Docker-network services). The recipe doesn't apply; consider
  a hybrid setup with both running.

## Report format
- Architecture before/after (text or diagram)
- Steps completed (checkbox list)
- Performance comparison: <X>s/call before vs <Y>s/call after, factor speedup
- Any quirks specific to this service that future readers should know
- Compose file diff (one block)
- .env changes (one block)
- Verification: paste the worker-container `fetch` output showing it reaches the host
```

## Variants

- **Linux + NVIDIA:** same recipe, replace "Metal" with "CUDA" and macOS-specific
  steps (LaunchAgents, osascript) with `systemctl` equivalents. Step 4 (0.0.0.0
  binding) is identical.
- **Multiple LLMs in the same project:** repeat for each. They can share the
  same `host.docker.internal` mechanism on different ports.
- **vLLM in production:** typically runs in Kubernetes, not bare metal. The
  recipe still applies for the binding + DNS resolution moves; replace
  "host-side" with "in-cluster service" and adjust the `URL` accordingly.
