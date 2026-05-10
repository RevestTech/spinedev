# Architecture decisions (ADR log)

**Append-only.** Do not delete or rewrite past ADRs. If a decision is reversed, add a new ADR that references the old one and records the supersession.

Decisions here are the **spine context** for humans and agents: they reduce drift when many sessions or roles touch the same codebase.

---

## How to add an ADR

1. Copy the structure from `ADR_TEMPLATE.md` in this directory (or duplicate the placeholder section below).
2. Use the next number: `ADR-00N` (zero-padded to match your team's convention).
3. Link from `SESSION_HANDOFF.md` or `MASTER_TODO.md` when a change is in flight.

---

## ADR-001: (title — replace when first real decision is recorded)

- **Date:** YYYY-MM-DD  
- **Status:** proposed | accepted | superseded by ADR-00X  
- **Deciders:** names or roles  
- **Context:** what problem or uncertainty triggered this  
- **Decision:** what we agreed to do  
- **Consequences:** what becomes easier or harder  
- **Alternatives considered:** what we rejected and why  

---

_End of scaffold. Replace the ADR-001 block with your first real decision, or remove the placeholder once ADR-001 exists._
