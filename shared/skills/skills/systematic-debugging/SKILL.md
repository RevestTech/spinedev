# Skill — systematic debugging

The directive in front of you describes a **bug, failure, exception, or
unexpected behavior**. The default failure mode here is well-documented:
agent reads the message → jumps to a hypothesis → starts changing
code → spends turns on the wrong fix. Don't. Run the 5 steps below in
order. They are slower per step than guessing and faster end-to-end by
a wide margin.

## The 5 steps

### Step 1 — Reproduce
Confirm you can trigger the bug yourself. Run the failing command,
load the failing input, hit the broken endpoint. If you **can't
reproduce**, do not fix — investigate why it's happening for the
reporter but not for you (different env, different data, different
build, race condition). Reporting "I tried it, looked fine" is a valid
output; "I changed three files based on the description" is not.

### Step 2 — Localize
Narrow the bug to a specific code region. Use the Knowledge Graph,
not blind grep:
- `find_callers(broken_symbol)` — who triggers the failing path?
- `code_neighborhood(broken_symbol)` — what's nearby that might be
  related?
- `impact_radius(broken_file)` — what else depends on this?
- `doc_for_region(broken_file)` — any ADRs or lessons-learned about
  this code?

End of Step 2: you can point at a function or a small region and say
*"the bug is in here"* with evidence.

### Step 3 — Form hypothesis
State EXACTLY what you think is wrong, and WHY, in ONE sentence.
Example:
> *"The parser returns `None` on empty input because the early-return
> on `len(s) == 0` runs before the default-value branch."*

Do **not** fix yet. If you can't write the sentence cleanly, you don't
have a hypothesis — you have a guess. Go back to Step 2.

### Step 4 — Test hypothesis
Make the **smallest possible change** to confirm or refute your
hypothesis. Add a `print`, add an `assert`, add a focused test that
captures the broken behavior. Run it. Read the output. Do **not**
commit the fix code yet — you are still proving the hypothesis is
correct.

If the hypothesis is refuted: back to Step 3 with the new evidence.
If confirmed: go to Step 5.

### Step 5 — Fix + verify
Now implement the fix. Then:
1. Run the original failing case → confirm it now passes
2. Run related tests → confirm no regression
3. If the bug was in untested code, the test you added in Step 4
   stays — it's the regression net for next time
4. Run `impact_radius` on your fix and verify nothing downstream
   broke (the `verification-before-completion` skill takes over here)

## Common anti-patterns

- **Shotgun debugging.** Changing multiple things at once means that
  when something works, you don't know what fixed it (and when it
  breaks again, you don't know what to undo).
- **Skipping Step 1.** Assuming reproduction without trying. The bug
  report's repro steps might be wrong; the bug might be environmental.
- **Skipping Step 4.** Jumping from hypothesis straight to fix.
  "I think this is it" without evidence is how an agent commits three
  wrong fixes in a row.
- **"I think this is it" without evidence.** If you can't point to a
  Step-4 experiment that proved the hypothesis, it isn't proven.

## When the bug is in untested code

Add a test **first** that captures the broken behavior — it should
fail before your fix and pass after. This converts the bug into a
permanent regression test, and gives Step 5 a binary pass/fail signal
instead of "looks fixed to me."

## Cross-refs

- `REQ-INIT-7` — engineer artifact contract (your fix lands here)
- `obra/superpowers` — `systematic-debugging` skill (pattern origin)
- `verification-before-completion` skill — picks up at Step 5 and
  carries you through to the BuildArtifact seal
- KG tools: `find_callers`, `code_neighborhood`, `impact_radius`,
  `doc_for_region`, `who_owns` (use these for Step 2 localisation)
