---
name: spine-harness-session
description: >-
  Start/finish a Spine agent session with Harness Lite + PM check-in. Use at
  session start, before claiming done, or when running ADR-008 audit/fix/verify waves.
---

# Spine harness session protocol

## Session start

1. `cd ~/dev/SpineDevelopment`
2. PM check-in (in_progress):
   ```bash
   npm run pm:checkin -- --agent cursor --role builder --status in_progress --task <ID> --message "Starting …"
   ```
3. Read `.spine/harness/state.json` if present
4. Optional: `bash tools/harness/spine-harness status --markdown`

## During work (ADR-008)

| Phase | Command / skill |
|-------|-----------------|
| Audit | `spine harness audit` or `harness-audit-wave` |
| Fix | `harness-fix-wave` (exclusive file scope) |
| Verify | `spine harness verify --run-qa` or `harness-verify-wave` |

Never mix audit and fix in one wave.

## Session end

1. Run evidenced QA:
   ```bash
   bash tools/fc-sdlc/ci-test-full.sh
   # or: bash tools/harness/spine-harness verify --project . --run-qa
   ```
2. PM check-in (completed) with deliverable path
3. Update `Handoff.md` changelog if Harness milestone

## Token rules

- Subagent prompts: 200–400 words
- Audit output: structured JSON / drift tables, not prose dumps
- Use `cavecrew-investigator` for locate; `cavecrew-builder` for ≤2 file edits
