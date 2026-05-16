# Anthropic Prompt Cache Wrapper — `shared/cost/prompt_cache.py`

Implements **`STORY-1.5.4`** (REQ-INIT-1 §1.5 FR-6 mechanism #4 —
"Prompt caching for long intake conversations").

## Why this matters

Anthropic charges **~10 %** of normal input rate for cache reads (and a
**~25 % premium** on the one-time cache-creation write). On a typical
5-move Spine intake conversation — system prompt + role intro + retrieved
context all stable, only the user message changing each turn — caching
the prefix cuts per-turn input cost by **~85 %** after the first call.

## When to use it

Good fits:

* Long intake / discovery sessions (system + role + KG context reused 5-20+ turns)
* Multi-turn architect review (TRD draft + spec hangs around)
* Per-project assistants with stable role prompts

Bad fits:

* One-off calls (write premium dominates; net negative)
* Short system prompts (< 1024 tokens — Anthropic's minimum cacheable)
* Sessions where every turn changes the context drastically

The helper `should_use_cache(prefix_tokens=N, expected_turns=K)` encodes
this rule.

## Cache breakpoint strategy

Anthropic supports up to **4 `cache_control` markers per request**. Put
markers AFTER the long stable context, BEFORE the per-turn user message:

```
[system prompt]                       <- always cached (auto)
[role intro]
[retrieved KG context]                <- cache_breakpoints=[0]
[prior turn summary]                  <- cache_breakpoints=[1]
[user message THIS turn]              <- never cached
```

`cache_breakpoints=[]` means "do not cache" — useful for one-shot calls
even when the call shape would otherwise support it.

## Integration with the router

This wrapper does **not** modify `router.py`. The intended call shape:

```python
from shared.cost.router import RouteRequest, route
from shared.cost.prompt_cache import (CachedPromptCall, Message,
                                      call_with_caching, should_use_cache)

decision = route(RouteRequest(...))
if not decision.blocked and should_use_cache(prefix_tokens=2400, expected_turns=6):
    text, stats = call_with_caching(CachedPromptCall(
        system_prompt=ROLE_INTRO + KG_CONTEXT,
        cache_breakpoints=[0],
        user_messages=[Message(role="user", content=turn_text)],
        model=decision.selected_model, max_tokens=1024))
    # daemon: emit cost row using stats.input_tokens + stats.cache_read_input_tokens
```

A future story (STORY-1.5.x) can add a `use_prompt_cache=True` flag on
`team_router.TeamRouteRequest` that auto-routes through this wrapper.

## Cost projection

Use `estimate_savings()` to forecast on a typical 5-turn intake (2400-token
prefix, 200-token user message, claude-haiku-3.5 @ $0.001/1k):

| Strategy        | Total input tokens billed | Effective cost |
|-----------------|---------------------------|----------------|
| No cache        | 5 × 2600 = 13 000          | $0.013         |
| Cache (1 write + 4 reads) | 2400×1.25 + 200×5 + 2400×4×0.10 = 4960 | $0.005 |

→ **~62 % savings** on a small session; the savings curve steepens with
longer prefixes + more turns.

## Cross-refs

* `docs/BACKLOG.md` → STORY-1.5.4
* `docs/PRD.md` → REQ-INIT-1 §1.5 FR-6 mechanism #4
* `shared/cost/router.py` (model selection — unchanged by this story)
* `shared/cost/team_router.py` (auto-router — extension point for opt-in)
* Anthropic prompt caching docs: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
