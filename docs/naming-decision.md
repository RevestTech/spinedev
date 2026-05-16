# Naming & Branding — Decision Record

> ADR-style decision doc for the project name and brand mark. Implements `STORY-5.1.3` in [`docs/BACKLOG.md`](BACKLOG.md). Status: **Proposed — pending user sign-off.**

---

## Context

"Spine" has been the working name since v1. v2 expanded the scope materially — the original v1 was an agent orchestrator alone; v2 unifies Plan + Build + Verify + Orchestrator + TRON-integrated verification into a single product. Eight commits, ~25,000 LOC, ~80 of ~180 stories Done across 9 INITs.

Before the public launch (positioning doc shipped, comparison doc shipped, landing page in flight at `STORY-5.1.4`), the name deserves a deliberate look. The repo is currently called `SpineDevelopment`; the product is referred to as "Spine" in `docs/positioning.md`, `docs/comparison.md`, `README.md`, all role prompts, and the dashboard.

The cost of getting this wrong is non-trivial — but the cost of churning on it indefinitely is worse. This document records the options, the criteria, and the recommendation so the choice can be made and locked.

---

## Options considered

### Option A — Keep "Spine"

Simple. Established internally. Conveys "central support structure that holds the rest together" — which is exactly what the orchestrator does.

- **Pros:** zero rebrand cost. Brand built up in ~25k LOC of internal docs, role prompts, and commit history. Metaphor maps cleanly to the orchestrator-as-backbone architecture. Short, single syllable, easy to say.
- **Cons:** generic English word — SEO competes with anatomy, animation libraries (`spine.js`, EsotericSoftware Spine), book bindings, and dozens of unrelated products. No audio/visual identity yet (no logo, no wordmark, no font). The `spine.dev` / `spine.io` domains may already be parked or held.

### Option B — "Spine v2" / "Spine Platform"

A modifier signaling the v2 transition while preserving "Spine" recognition.

- **Pros:** signals a new chapter without throwing away brand equity. Useful as a transition label for the first six months post-launch.
- **Cons:** "v2" feels transitional permanently — every reader wonders what changed and whether to wait for v3. "Platform" is overused to the point of meaninglessness in dev tools (every tool is a platform now). Adds a word to every doc reference; doesn't actually solve the SEO problem.

### Option C — New name entirely

Pick a distinctive mark. Candidate set (filtered for short, sayable, evocative of "structure / coordination / forge"):

- **Loom** — weaving multiple threads into one cloth. Strong metaphor for multi-agent coordination. Conflicts with Loom (the video tool, well-known).
- **Atelier** — workshop where a master coordinates apprentices. Captures the role-bounded team. Long, harder to type, slightly precious.
- **Foundry** — where things are forged. Conflicts with Foundry (the FVTT tabletop tool) and Factory.ai's neighborhood.
- **Anvil** — where the smith works. Conflicts with Anvil (Python web framework).
- **Plinth** — the base a column stands on. Distinctive, ownable, but obscure (most readers won't know the word).
- **Forge** — making things from raw material. Heavily used (GitHub, Forge, etc.).
- **Citadel** — fortified center. Wrong vibe (too military).
- **Crucible** — vessel where transformation happens. Strong metaphor; Atlassian's old code-review tool used this name.
- **Bulwark** — defensive structure. Wrong vibe (defensive, not generative).
- **Keystone** — the stone that holds an arch together. Strong metaphor (literally "what holds the system together"). Conflicts with Keystone (CMS, OpenStack identity).

- **Pros:** clear v2 identity. Fresh search results. Brand-ownable. Forces a logo / wordmark / color palette decision now while it's cheap.
- **Cons:** rebrand cost across ~25k LOC + commit history + every doc + every role prompt + dashboard + Makefile targets + `team-up` etc. Existing users (small number today but growing) have to relearn. Delays launch unless we ship under one name and rename later (worst of both worlds).

### Option D — Compound name

Keep "Spine" as a root and add a distinctive suffix or modifier: **Spinedev**, **SpineDev**, **Spine Orchestra**, **Spine Forge**, **Spine Stack**.

- **Pros:** distinctiveness + continuity. Search engines treat compound terms much better than the bare word. Domain availability is far better for compounds.
- **Cons:** longer, harder to say in conversation ("spine dev" reads as two words). "Orchestra" is poetic but doesn't say what the product does. Most compounds end up dropping the second word in practice (people say "Spine" anyway), which leaves you with the Option A problem.

---

## Evaluation criteria

Each option scored against six criteria. Weights reflect what matters at launch (not five years out).

| Criterion | Weight | Why it matters |
|---|---|---|
| Cost to rebrand | High | ~25k LOC, role prompts, commits, dashboard, Makefile, INSTALL flow all touch the name. |
| Searchability (Google + GitHub) | High | A vibecoder searching "AI engineering team local" should find us, not a back-pain forum. |
| Pronunciation | Medium | Says it twice in a sentence; if you can't say it, you can't recommend it. |
| Domain availability (.com / .dev / .io) | Medium | Required for the marketing site; `.dev` and `.io` are acceptable substitutes for `.com`. |
| Trademark cleanliness | Medium | Cursory USPTO + EUIPO search for confusable marks in the dev-tools class. |
| Marketing connotation | Low | Nice to have; not a blocker. Metaphor strength matters more for documentation than logo. |

Scoring (1 = bad, 5 = excellent):

| Option | Rebrand cost | Search | Pronounce | Domain | TM | Connotation | **Weighted** |
|---|---|---|---|---|---|---|---|
| **A. Keep "Spine"** | 5 | 2 | 5 | 2 | 3 | 4 | **3.5** |
| **B. "Spine v2"** | 4 | 3 | 4 | 3 | 3 | 3 | **3.4** |
| **C. New name** | 1 | 4 | varies | 4 | 4 | 4 | **3.0** |
| **D. Compound (Spinedev)** | 4 | 4 | 3 | 4 | 4 | 3 | **3.7** |

The weighted scores are close — no option dominates. Rebrand cost and pronunciation favor staying with "Spine"; searchability and domain availability favor compounds or new names.

---

## Recommendation

**Keep "Spine" as the product name. Use "Spine" in conversation, docs, and the wordmark. Reserve "SpineDev" / "spine.dev" as the primary search-friendly identifier and brand domain.**

Reasoning:

1. **Launch is what matters now.** ~80 of ~180 stories are Done; integration testing is the active sprint. The naming decision should not be a launch blocker. Rebranding mid-flight would consume sprint capacity that should be going to product.
2. **The metaphor works.** "Spine = central support that holds everything together" maps cleanly to the orchestrator. The landing page can lean on this metaphor explicitly to differentiate from generic uses.
3. **Compound name solves the SEO problem at zero cost.** Treating "SpineDev" as the brand for search + domain purposes, while saying "Spine" in conversation, captures the upside of Option D without the downsides. This is how "Go" handles "golang.org" — say one thing, search a different thing.
4. **Rename for v3 if positioning shifts.** If Spine evolves into an enterprise-focused product, a more deliberate brand mark (Atelier, Crucible, Keystone) may fit better. Track that decision; don't pre-decide it.

Consider this decision **reversible** — if a name from Option C develops strong appeal in user research after launch, the cost of renaming a small public user base is bounded.

### Why not Option D fully (rename to "Spinedev")?

Because we'd still say "Spine" in conversation, and the canonical name should match how humans refer to the product. Calling it "SpineDev" in docs while everyone says "Spine" creates the same confusion as "Twitter / X". Pick the spoken name as the canonical one.

---

## Decision

**Proposed — pending user sign-off.**

| Question | Decision |
|---|---|
| Canonical product name | **Spine** |
| Canonical search/domain identifier | **SpineDev** (reserve `spine.dev`, `spinedev.io`) |
| Repo name (`SpineDevelopment`) | Keep through v2 launch; consider rename to `spine` post-launch (low priority) |
| Wordmark | "Spine" in the brand font (system stack for now; commission a wordmark when there's budget) |
| Brand mark | The four-dot + line glyph in the landing-page header (see `docs/landing/index.html`) — placeholder until a designer is engaged |
| Tagline | "The local-deployed AI engineering team." (from `docs/positioning.md`) |

---

## Action items (post-decision)

1. **Reserve domains** — `spine.dev`, `spinedev.io`, `spinedev.com` (someone with a card should buy these before public launch). Owner: TBD.
2. **README badge** — update the project header to "Spine" with an explicit version annotation (`v2.0.0-alpha`). Owner: docs maintainer.
3. **Landing page metaphor copy** — add a one-line gloss on the metaphor ("spine = the central support that holds the engineering team together") in the hero or about copy. Owner: `STORY-5.1.4` author.
4. **Trademark search** — cursory search of USPTO and EUIPO for confusable marks in IC 042 (software services). If clear, file an intent-to-use application before public launch. Owner: legal review.
5. **Wordmark** — commission a wordmark + favicon when there's design budget. Until then, the four-dot SVG glyph in `docs/landing/index.html` is the working mark.
6. **Close this story** — once the decision above is signed, mark `STORY-5.1.3` as Done in `docs/BACKLOG.md` with a pointer to this file.

---

## Cross-references

- `docs/positioning.md` — uses "Spine" throughout; aligned with this decision.
- `docs/comparison.md` — uses "Spine" throughout; aligned.
- `docs/landing/index.html` — the landing page (STORY-5.1.4); brand mark and tagline live there.
- `docs/BACKLOG.md` `STORY-5.1.3` — this decision closes that story.
- `README.md` — apply badge update after sign-off (action item 2).
