# Recipe — Investigate a bug (researcher)

Drop this into `teams/researcher/directive.md`, customize the placeholders, save.

---

```markdown
# Directive — Investigate <BUG SHORT NAME>

## Symptom
<one paragraph: what you see, where, when. Quote actual error messages or screenshots.>

## What to find out
1. Root cause: which file/function/config produces this behavior
2. Whether it's reproducible — can you reliably trigger it?
3. Scope: how many users / docs / code paths are affected
4. Related history: does git blame / recent commits show anything relevant
5. What I tried that didn't work (so we don't repeat)

## Tasks

### 1. Reproduce
<paste the steps you took or the URL/command that triggers it>

### 2. Trace
- Search for the error string across the codebase
- Read the relevant handler / function / route
- Check logs from the primary app container + relevant services for the time window

### 3. Database state (if relevant)
<SELECT queries to check related tables>

## Constraints
- Read-only. Do NOT modify code or config.
- Quote actual command output. Do not paraphrase.

## Report format
Replace this file with `# Report — <bug name> investigation` containing:
- Root cause: one paragraph synthesis
- Evidence: numbered findings with quoted command output
- Reproduction steps that work
- Suggested fix (file + change), but DO NOT implement
- Open questions
```
