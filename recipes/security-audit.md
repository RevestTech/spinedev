# Recipe — Security audit (planner)

Drop into `teams/planner/directive.md`. Orchestrates a full-stack security pass: dependency vulns, secrets in repo, auth surface, infra/container hardening, and a write-up.

---

```markdown
# Directive — Security audit of <SCOPE>

## Tier hint: medium

(Planner stays at medium. Specialist sub-directives mostly run LOW; only deep code review of the auth surface should escalate.)

## Goal
Produce an audit of <scope> across five attack surfaces:
1. Vulnerable dependencies (transitive included)
2. Secrets / credentials leaked into the repo or build artifacts
3. Auth + authorization surface (route-level access checks)
4. Infra hardening (container images, exposed ports, env handling)
5. Logging + observability gaps (where would an intrusion hide?)

The output is a prioritized list of findings — NOT fixes. Fix work is a follow-on directive.

## Specialist plan
1. researcher → "Run dependency audits (npm audit / pip-audit / cargo audit / etc) for every package manifest in repo. Capture high+ severity items with CVE IDs. DO NOT fix." (LOW tier)
2. researcher → "Grep the repo for likely secrets — API keys, JWT secrets, private keys, .env contents committed by mistake, hardcoded passwords. Report file paths + line ranges, redact actual secret values in the report." (LOW tier, parallel with #1)
3. engineer → "Review auth + authorization surface: every public route, what authn it requires, what authz check runs, whether ownership/RBAC is enforced. Flag any route that's reachable unauthenticated when it shouldn't be." (MEDIUM tier — needs careful reading)
4. operator → "Review Dockerfile + compose: base image freshness, non-root user, exposed ports vs intended public surface, secret mounting strategy, healthcheck presence." (LOW tier)
5. researcher → "Review logging — what gets logged on auth events, on 4xx/5xx responses, on data mutations. Identify gaps where an attacker's actions would leave no trace." (LOW tier, parallel with #4)
6. memory → "Synthesize findings into a SECURITY_AUDIT.md report with severity rankings + recommended remediation order." (MEDIUM tier; runs last)

## Stop conditions
- If a P1 finding is uncovered (e.g. unauthenticated admin route, committed production secret), escalate IMMEDIATELY in the report — do not wait for full audit completion.
- Architect approval required before any remediation work begins.

## Report format (planner aggregate)
Replace this file with `# Report — security audit of <scope>` containing:
- Headline: count of P1/P2/P3 findings
- P1 findings (must fix before next deploy): with file/line refs, recommended remediation
- P2 findings (fix this sprint)
- P3 findings (track in backlog)
- What's clean (record this — useful as a baseline for next audit)
- Recommended follow-on directives (one per P1, batched per P2/P3)
- Pointer to full SECURITY_AUDIT.md (memory output)
```
