# Spine Bundle Install Pipeline

> Implements `STORY-2.1.2` (install + validate), `STORY-2.1.3` (per-role injection), `STORY-2.1.4` (auditor consumption), `STORY-2.1.5` (drift detection). See `docs/BACKLOG.md` INIT-2 EPIC-2.1 and PRD `REQ-INIT-1 FR-7/FR-8`.

## Why a clean install command

A role-prompt rebuild is **one command, not 13 manual edits**. When an org publishes a new bundle version (a new banned pattern, a tighter cost cap, a new compliance pack), `spine bundle install <url>` re-runs the entire fetch → validate → store → inject → audit pipeline and every relevant role prompt is rewritten in lockstep. Hand-editing 13 markdown files in 13 worktrees was the failure mode this story replaces.

## Lifecycle

```
fetch        →  validate     →  store              →  inject              →  audit
(curl/git/cp)   (validator.py)  (~/.spine/bundles)    (prompt_injector.py)    (audit_record.py)
```

1. **fetch** — URL (`curl -fsSL`), `git+<repo>` (shallow clone, picks first `bundle*.yaml`), or local path (`cp`). Output: a staged YAML in `/tmp`.
2. **validate** — Pydantic v2 model in `validator.py` matches the bundle schema; cross-section rules flagged as errors or warnings. Refuse to install on any error.
3. **store** — atomic write to `~/.spine/bundles/<bundle_id>/v<bundle_version>/`. SHA-256 + install timestamp + source URL recorded alongside.
4. **inject** — `prompt_injector.py` rewrites the role-prompt files (one per role) by replacing the block between `<!-- SPINE-BUNDLE-INJECT-BEGIN -->` and `<!-- SPINE-BUNDLE-INJECT-END -->` markers. Idempotent.
5. **audit** — best-effort `audit_record.py record --action bundle_install`. Install does not fail if audit is down; the install row is what matters operationally.

## Storage layout

```
~/.spine/bundles/<bundle_id>/v<bundle_version>/
  bundle.yaml      # the validated bundle
  sha256           # hex digest, drift-detection anchor
  installed_at     # ISO-8601 UTC timestamp
  source_url       # http(s):// or git+ or file:// (drift queries this)
~/.spine/active/
  org              # bundle_id active org-wide
  project-<id>     # per-project override (most-specific-wins)
```

## How injection works

Each role prompt receives a YAML slice scoped to its authority (see `prompt_injector.py:ROLE_SLICES`):

| Role | Slice |
|---|---|
| `product`    | documentation requirements, compliance tags, capability grants |
| `architect`  | compliance packs, deployment targets, summary of libs + banned patterns |
| `engineer`   | full approved_libs, full banned_patterns, style guides, naming conventions |
| `qa`         | sast/dependency scanning, test coverage threshold |
| `operator`   | deployment targets, secret scanning |
| `auditor`    | full banned_patterns, full security block, compliance tags |
| `datawright` | PII/GDPR flags, approved libraries |

The block is bracketed by markers so re-injection touches only that region — every hand-edit outside the markers is preserved. The block also stamps `bundle_id` and `bundle_version`, so a `git diff` after a re-install reviews cleanly.

## Drift detection

`spine bundle status` re-fetches the source URL of the active bundle and compares its SHA-256 to the locally stored digest:

- `in_sync` — local matches upstream.
- `drifted` — upstream has changed; run `install` to re-pin.
- `source_unreachable` — upstream not reachable (offline / 404). Local install still authoritative.
- `unknown` — source wasn't a URL (e.g., installed from a local path); no remote to query.

This is the STORY-2.1.5 anchor — orgs publish bundle bumps; users find out at `status` time, not by surprise mid-engagement.

## Override hierarchy

```
org bundle (~/.spine/active/org)                ← baseline
  └── project bundle (~/.spine/active/project-<id>)   ← narrows further (never widens)
```

`spine bundle install <path>` installs without activating beyond org-default. `spine bundle activate <bundle_id> --project <id>` flips the project-scope active pointer. `spine bundle inject --project <id>` re-emits the per-project slice into role prompts.

Team scope (`spine bundle activate ... --team <id>`) lands when `STORY-1.7.3` wires the inherits-from resolver — the storage layout already accommodates it (`~/.spine/active/team-<id>` follows the same convention).

## Worked example: install the regulated bundle

```
$ bash shared/standards/install_bundle.sh install \
       shared/standards/bundle-regulated-enterprise.yaml
{"ok":true,"bundle_id":"regulated-enterprise-reference","bundle_version":1,
 "source_url":"file:///.../bundle-regulated-enterprise.yaml",
 "sha256":"e3b0…","dest":"/Users/me/.spine/bundles/regulated-enterprise-reference/v1",
 "role_prompts_modified":["/Users/me/.../lib/role-prompts/engineer.md", …],
 "counts":{"grants":3,"banned_patterns":7,"compliance_packs":4}}
```

After the run, `lib/role-prompts/engineer.md` gains a block like:

```yaml
<!-- SPINE-BUNDLE-INJECT-BEGIN bundle_id=regulated-enterprise-reference -->
## Org bundle policy (regulated-enterprise-reference v1)

approved_libs:
  python: [fastapi, pydantic, sqlalchemy, pytest, httpx, cryptography, anthropic]
  typescript: [react, next, zod, vitest, "@anthropic-ai/sdk"]
banned_patterns:
  - pattern: "pickle\\.loads?\\("
    severity: critical
    message: "Insecure deserialization (pickle). Use JSON or msgpack..."
  - ...
<!-- SPINE-BUNDLE-INJECT-END -->
```

The auditor receives the same `banned_patterns` block — by design, so a violation the engineer ignores is the finding the auditor blocks the gate on.

## Cross-references

- `docs/PRD.md` REQ-INIT-1 FR-7 (customization authority), FR-8 (versioning, audit).
- `docs/BACKLOG.md` INIT-2 EPIC-2.1 (`STORY-2.1.1`…`STORY-2.1.6`).
- `shared/standards/bundle-schema.yaml` (source of truth for shape).
- `shared/standards/README.md` (override hierarchy + bundle architecture).
- `orchestrator/lib/router.sh` (the stylistic template for `install_bundle.sh`).
