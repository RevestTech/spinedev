# Skill — verification-before-completion

You are about to seal a `BuildArtifact` and report **done**. Before you do,
walk this checklist. It is *not* optional; the auditor (STORY-7.4.3) verifies
your claims and a missing step here is a confidence hit on the whole report.

## The six checks

1. **Re-read the directive end-to-end.** Did you address every line? If the
   directive listed three asks and you handled two, you are not done —
   either finish the third or explicitly defer it under
   `## Deferred items` with a one-line reason.

2. **Run `impact_radius`** on every changed file. Populate
   `BuildArtifact.kg_impact` with the full node list, `impact_distance` field
   included unchanged. Do **not** summarise or prune — the auditor uses the
   raw set to detect underclaimed scope.

3. **Run the test suite** if you changed code that has tests. The repo's
   baseline test count is treated as a hard floor; new tests pass, existing
   tests keep passing. If a test failed, do **not** seal — report the
   failure with `lint`/`test` output captured verbatim and stop.

4. **Reconcile `## Files touched`** against `git status --short`. If the
   diff shows a file your report doesn't mention, either claim it
   (with a one-line "(modified — what)" annotation) or delete it. No
   silent leftovers.

5. **Look for the obvious things you didn't check.** Boundary cases (empty
   list, single item, max length), error paths (what does the function do
   when the DB is down?), off-by-one (range bounds, slice indices),
   concurrency (was the file you wrote also being read?), and the
   sentinel that always catches people — *did you remember the `await`?*

6. **State your verification explicitly.** End your report with a section:
   `## Self-verification` listing every claim as either
   `"verified X by Y"` (e.g., "verified parser handles empty input by adding
   `test_empty_input`") or
   `"did NOT verify Z because <reason>"`. Silence is not a verification;
   the auditor will treat an unstated claim as unverified.

## Refuse-to-seal rule

If **any** of checks 1-5 cannot be completed (tests blocked, KG unreachable,
directive items unresolved), do **not** emit the `BuildArtifact`. Instead,
report what blocked you and stop. A blocked-but-honest report is worth more
than a sealed-but-overclaimed one — the auditor catches the second case and
your trust score takes a bigger hit than the time you saved.

## Why this exists

Pattern lifted from `obra/superpowers` —
`verification-before-completion` is the highest-leverage skill in their set
because it shifts verification cost from a separate auditor pass into the
agent's own loop. The auditor still runs (STORY-7.4.3 verifies your
`kg_impact` claim), but on a *much smaller* set of claims because you
caught the trivially-wrong ones first.

Cross-refs: `REQ-INIT-7 FR-3`, `STORY-7.4.3`, `shared/charters/engineer.md`
(the KG section already requires `impact_radius`; this skill makes the
self-check the cap-stone, not the first step).
