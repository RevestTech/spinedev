# Overnight handoff — 2026-05-23

> **Operational queue:** [`MASTER_TODO.md`](MASTER_TODO.md) (updated 2026-05-25).
> **Latest session narrative:** [`SESSION_HANDOFF.md`](SESSION_HANDOFF.md) (2026-05-24).

> Written while Khash sleeps. Agent continued as founder proxy.

## What got done tonight

### Product wiring (code)
| Item | Status |
|------|--------|
| Engineer squad lead (FE/BE/DB) wired in hub runner | Done |
| Spine-on-Spine sandbox (`resolve_code_dir`, `spine_on_spine` on project create) | Done |
| Inline LLM fallbacks removed → orchestrator gap cards | Done |
| Plan artifacts → git `docs/` + KG commit (`promote_plan_artifacts`) | Done |
| Smart Spine hook on dispatch success (`smart_spine_bridge.py`) | Done |
| Phase watcher uses orchestrator + gap cards on miss | Done |
| Post-ack golden path tests (`test_post_ack_golden_path.py`) | Done |
| Golden path dry-run tool (`tools/golden-path-dry-run.sh`) | Done |
| `build_dispatch` default fixed (`SYNTHESIZE_BRIEF` vs hub hijack) | Done |

### Verification
- **Smoke:** `101 PASS / 0 FAIL / 1 WARN`
- **Unit tests:** project workspace, engineer squad, post-ack golden path — all pass
- **Hub rebuild:** started via `bash tools/hub-up.sh --rebuild` (needed for `spine_on_spine` API field in running container)

## What I could not finish alone (needs you)

These are **real** blockers for §9 + V1 ship — not code gaps:

1. **§9 founder walkthrough** — approve cards in Hub SPA with live LLM through intake → deploy. Requires you (or explicit approval automation) with `ANTHROPIC_API_KEY` set.
2. **V1_SHIP_CHECKLIST §1–§7** — vendor CI/CD, Shamir key ceremony, spine.dev, design partners, BYOC live runs. Operational / business, not repo code.
3. **Hub container** — if rebuild finished, verify:
   ```bash
   curl -sS -X POST http://localhost:8090/api/v2/projects \
     -H 'Content-Type: application/json' \
     -H 'Authorization: Bearer <token>' \
     -d '{"name":"Spine on Spine","project_type":"feature","spine_on_spine":true}'
   ```
   Should **not** return `extra_forbidden` on `spine_on_spine`.

## Your 5-minute morning routine

```bash
cd ~/Projects/Apps/SpineDevelopment
bash tools/smoke-test.sh                    # expect 101 PASS
bash tools/golden-path-dry-run.sh           # bridge + MCP registry
# LLM keys: hub-up auto-loads from kmac-vault (:9999) when unset/placeholder
bash tools/hub-up.sh --rebuild              # if Hub image or env changed
bash tools/spine-on-spine.sh "First dogfood sprint"
open http://localhost:8090/spa/
```

Walk Decision Queue → approve through PRD → plan → build → verify → release.

When §9 feels true, open `docs/V1_SHIP_CHECKLIST.md` and start checking ops gates.

## Spine-on-Spine framing (unchanged)

- **Spine** = phases, gates, audit, KG, charters  
- **Claude/subagents** = work inside roles  
- **You** = approve at gates, sleep while agents run  

Dogfood output: `.spine/dogfood/<uuid>/` (safe). Repo write only with `SPINE_ON_SPINE_ALLOW_REPO_WRITE=1`.

---

## Morning update (2026-05-23, agents)

- Hub rebuilt; `spine_on_spine` project create works.
- **`bash tools/golden-path-walkthrough.sh`** — auto intake + ack loop (needs valid `ANTHROPIC_API_KEY` in Hub env).
- Dogfood workspace zip/list/read fixed to use `.spine/dogfood/<uuid>/`.
- Legacy `_post_ack` reject fix-loop + local deploy now use `resolve_code_dir` (same dogfood path as orchestrator).
- **Walkthrough blocked:** Hub returns `401 invalid x-api-key` — set a valid key in host shell before `bash tools/hub-up.sh --rebuild`.
- **Dry-run:** `bash tools/golden-path-dry-run.sh` PASS; smoke **101 PASS / 0 FAIL**.
- Run walkthrough to complete §9; then `V1_SHIP_CHECKLIST.md`.

*Good night. The operating company loop is wired; the launch ceremony is yours.*
