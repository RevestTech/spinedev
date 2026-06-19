# Timed DR drill runbook (SPINE-019)

> Operator guide for a **timed** backup → restore → verify cycle with an
> explicit RTO gate. Complements the architectural runbook in
> [`DR_RUNBOOK.md`](DR_RUNBOOK.md) and the auto-generated per-deployment
> runbook from `recovery/runbook_generator.py`.

---

## Purpose

Layer 4 (#32) requires a **tested** restore, not just backups that exist.
SPINE-019 adds a wall-clock **RTO gate** to `tools/dr-test.sh`:

- Records `rto_elapsed_seconds` for the full script run (pre-flight through
  teardown).
- Fails non-dry-run executions when elapsed time exceeds
  `--max-rto-seconds` (default **1800** = 30 minutes).
- Emits structured JSON with `rto_elapsed_seconds` and `rto_gate_pass`.

Target: **RTO ≤ 30 min** for full Hub restoration in customer deployments.

---

## Deployment tiers

| Tier | Command | RTO gate | What it proves |
|------|---------|----------|----------------|
| **Laptop / CI wiring** | `bash tools/dr-test.sh --dry-run` | Skipped (`rto_gate_skipped: true`) | Python driver, recovery imports, JSON shape |
| **Synthetic local** | `bash tools/dr-test.sh --dry-run` + unit tests | Skipped | Same as wiring; no live backup substrate |
| **Customer-grade timed drill** | `bash tools/dr-test.sh --target-uri=…` | **Enforced** (default 1800s) | Real backup pick → throwaway restore → verify |

**Hold:** customer-grade timed drills against production-like backup
substrate are **deferred until a design partner** (SPINE-020). Do not
claim customer RTO compliance from laptop dry-runs alone.

---

## Laptop / developer drill (safe default)

Use this on every clone and before pushing recovery changes:

```bash
# Wiring check (smoke + nightly dry-run equivalent)
bash tools/dr-test.sh --dry-run

# RTO gate unit smoke (dry-run path only)
bash tools/test_dr_rto_gate.sh

# Recovery module tests (no live cloud)
.venv/bin/python -m pytest recovery/tests/ -q
```

Expected dry-run JSON fields (minimum):

```json
{
  "cycle_id": "dry-run",
  "all_passed": true,
  "rto_elapsed_seconds": 0,
  "rto_gate_pass": true,
  "rto_gate_skipped": true,
  "max_rto_seconds": 1800
}
```

`rto_elapsed_seconds` is wall-clock for the entire script; values near
zero are normal on fast laptops.

---

## Customer-grade timed drill (when unblocked)

Prerequisites:

1. At least one completed `spine_dr.backup_run` in the target environment.
2. `--target-uri` sourced from bundle DR config (not invented for the drill).
3. Throwaway env name (`--env=dr-sandbox` default) with no production traffic.
4. On-call notified; maintenance window if primary Hub is stressed.

### Procedure

1. **Record start** — note UTC timestamp and release / bundle version.
2. **Run timed drill:**

   ```bash
   bash tools/dr-test.sh \
     --env=dr-sandbox \
     --target-uri="${BUNDLE_DR_TARGET_URI}" \
     --max-rto-seconds=1800
   ```

3. **Capture JSON** — redirect stdout to an artifact path, e.g.
   `_state/dr_drill_$(date -u +%Y%m%dT%H%M%SZ).json`.
4. **Verify gates:**
   - `all_passed` is `true`
   - `rto_gate_pass` is `true`
   - `rto_elapsed_seconds` ≤ `max_rto_seconds`
   - `worst_rto_seconds` within bundle RTO policy (see `DR_RUNBOOK.md` §2)
5. **Tear-down** — script removes throwaway Postgres/KG; confirm no
   `spine-dr-test-*` containers remain.
6. **Evidence** — attach JSON + log excerpt to change record / compliance
   export if required (`evidence/` exporters).

### Override max RTO (exception only)

```bash
bash tools/dr-test.sh --target-uri=… --max-rto-seconds=2400
```

Requires documented approval when bundle policy is still 30 min. The JSON
records the limit used (`max_rto_seconds`).

### Failure handling

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| Exit 1, `all_passed: false` | Restore or smoke verify failed | Follow `DR_RUNBOOK.md` §5; page on-call |
| Exit 1, `rto_gate_pass: false` | Drill exceeded max wall-clock | Investigate backup size, network, restore path; do not ship |
| Exit 2 | Missing `--target-uri`, bad env, no Python | Fix pre-flight; re-run dry-run first |
| `no_completed_backup_run_found` | No backup history | Run layer-3 backup job; retry drill |

---

## Scheduling

| Cadence | Job | Notes |
|---------|-----|-------|
| Weekly | `bash tools/dr-test.sh` (full) | Default in `.github/workflows/nightly.yml` |
| Every PR / local | `--dry-run` | Wired in `tools/smoke-test.sh` |
| Pre-release | `--validate-against-version=<ver>` | Layer 12 compat check |

---

## Related artifacts

- `tools/dr-test.sh` — driver + RTO gate
- `tools/test_dr_rto_gate.sh` — dry-run RTO JSON assertions
- `recovery/restore.py` — `RestoreManager.run_weekly_test()`
- `docs/DR_RUNBOOK.md` — 12-layer architecture and escalation
- `todo/BACKLOG.md` — SPINE-019 acceptance, SPINE-020 design partner hold
