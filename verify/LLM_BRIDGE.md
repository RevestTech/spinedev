# `verify/` — TRON ↔ `shared/llm/` Bridge

> **Status:** FIX1 of the v3 drift audit landed 2026-05-18. This doc
> closes a HIGH-severity finding: TRON's LLM client had its own
> Provider enum + per-provider HTTP/SDK code + env-var key reads —
> bypassing the `shared/llm/` substrate that V3 design decision #2
> ("LLM-agnostic by architecture") commits Wave 1 to route through.
>
> **Source of truth:** `docs/V3_DESIGN_DECISIONS.md` #2 (LLM-agnostic) +
> #9 (vault-only secrets) + `docs/V3_BUILD_SEQUENCE.md` Part 1.4 #6
> ("TRON's own LLM provider routes through `shared/llm/`").

## What changed

`verify/tron/infra/llm/client.py` is now a **thin SHIM** over
`shared/llm/`:

- The TRON `Provider` enum is preserved (so TRON agents that import it
  keep working) **and extended** with `BEDROCK` / `VERTEX` / `QWEN` /
  `VLLM` so all seven v3 providers are reachable per-bundle without
  TRON-side code changes.
- `LLMClient.complete()` translates TRON's `LLMRequest` into
  `shared.llm.LLMRequest`, calls `shared.llm.call_async`, and
  translates the response back. No per-provider HTTP / SDK code lives
  in the shim.
- API-key kwargs (`anthropic_key=` / `openai_key=`) are accepted for
  backward compatibility but **silently ignored**. Per V3 #9
  (vault-only secrets), credentials flow exclusively through
  `shared.secrets` into the `shared/llm/providers/*` adapters.
- TRON-side concerns kept in the shim:
  - Per-provider circuit breaker (open after N consecutive failures)
  - Optional Redis response cache (`LLM_CACHE_ENABLED=1`)
  - LLM budget gate (`assert_llm_budget_allows_estimated_call`)
  - Usage-ledger persistence (`persist_llm_usage`)
- TRON-side concerns deleted: `_call_anthropic` / `_call_openai` /
  `_call_ollama` (per-provider HTTP code), env-var API-key reads
  (`os.environ.get('ANTHROPIC_API_KEY' …)`), the old per-provider
  retry loop (`shared.llm` adapters retry internally; the shim's
  outer loop is belt-and-braces).

The MCP-side companions `shared/mcp/tools/verify.py` and `iso.py` also
dropped their `_tron_secrets_from_env()` helpers and the
`tron_keys_missing` early-error gate — the gate now lives inside
`shared.llm` (which raises `ProviderConfigError` if no credential is
configured, which the shim re-raises as a clear `ValueError`
pointing at Hub bootstrap).

## Provider → `shared/llm` prefix mapping

The single source of truth is `_PROVIDER_MODEL_PREFIX` in the shim.
It mirrors the locked prefix list in
`shared/llm/providers/__init__.py::_load_builtin_providers`:

| TRON `Provider` | `shared.llm` prefix | Adapter |
|---|---|---|
| `ANTHROPIC` | `claude-`  | `shared/llm/providers/anthropic.py` |
| `OPENAI`    | `gpt-`     | `shared/llm/providers/openai.py` |
| `OLLAMA`    | `ollama:`  | `shared/llm/providers/ollama.py` |
| `BEDROCK`   | `bedrock:` | `shared/llm/providers/bedrock.py` |
| `VERTEX`    | `vertex:`  | `shared/llm/providers/vertex.py` |
| `QWEN`      | `qwen:`    | `shared/llm/providers/qwen.py` |
| `VLLM`      | `vllm:`    | `shared/llm/providers/vllm.py` |

TRON's `Provider` enum value's `.value` string matches the
`shared.llm` adapter `name` field so cross-referencing the two layers
stays mechanical.

## Adding a new provider

1. **Land the adapter under `shared/llm/providers/`**, exposing a
   `ProviderAdapter` subclass with a `model_prefix` and a
   `secret_name` resolved via `shared.secrets`. Register it in
   `shared/llm/providers/__init__.py::_load_builtin_providers`.
   See `shared/llm/providers/base.py` for the contract.
2. **Add the enum value + mapping entry in the shim** —
   `verify/tron/infra/llm/client.py`:
   - Add `MYPROV = "myprov"` to the `Provider` enum.
   - Add `Provider.MYPROV: "myprov:"` to `_PROVIDER_MODEL_PREFIX`.
3. **(Optional) Add per-model cost rows to `MODEL_REGISTRY`** if you
   want the TRON budget gate to price the new models. Cost rows are
   `(Provider, $/1K input, $/1K output)`. Leaving them out means the
   gate treats the call as free until `shared/cost/router.py`
   takes over cross-provider pricing in Wave 1.
4. **Add an enum-coverage row to the parametrize block in
   `verify/tron/tests/test_llm_client_shim.py`** so the new provider's
   routing is exercised on every CI run.
5. **No TRON-agent edits required.** Agents pick a provider via
   `ISOConfig.model_provider` + `ISOConfig.model_name`; the new
   provider is now selectable per-bundle.

## Why this matters

- **V3 #2 (LLM-agnostic by architecture)**: routing every LLM call
  through `shared/llm/` is the architectural commitment. The pre-shim
  client maintained a parallel codepath with three providers
  (Anthropic / OpenAI / Ollama) — a strict subset of the seven v3
  providers and a perpetual drift surface. The shim removes the
  parallel codepath.
- **V3 #9 (vault-only secrets)**: env-var API-key reads in the
  pre-shim client (`os.environ.get('ANTHROPIC_API_KEY')` …)
  contradicted the "no env://" rule. The shim removes them; the
  `_get_api_key` path inside `shared/llm/providers/base.py` is the
  single seam where credentials enter (and it pulls from
  `shared.secrets` in Wave 1 per its TODO).
- **Hub-bootstrap fail-closed**: if `shared.llm` is configured but
  has no credential for the resolved provider, the shim raises a
  `ValueError` naming Hub bootstrap so the operator knows exactly
  which knob to turn. Config errors do NOT trip the circuit breaker
  (otherwise a misconfigured Hub becomes self-poisoning).

## Standalone TRON deploys (G-8 in REQ-INIT-8)

TRON's standalone deployment path still works:

- The shim imports `shared.llm` lazily (inside `_call_shared_llm`).
- If `shared.llm` is not importable (e.g. running just `verify/`
  without the Spine umbrella), the shim falls back to a permissive
  exception-class tuple in `_resolve_shared_llm_exception_classes`
  so module import doesn't blow up.
- Standalone TRON callers must wire their own credentials into a
  `shared.secrets`-compatible source before the first LLM call.
  Pre-FIX1 standalone deploys that relied on `ANTHROPIC_API_KEY` /
  `OPENAI_API_KEY` env vars need to migrate to vault references
  (see `verify/.env.vault-refs` for the Spine pattern).

## References

- Shim source: `verify/tron/infra/llm/client.py`
- Unified call surface: `shared/llm/client.py`
- Provider adapters: `shared/llm/providers/{anthropic,openai,bedrock,vertex,ollama,qwen,vllm}.py`
- Tests: `verify/tron/tests/test_llm_client_shim.py`
- MCP-side scrub: `shared/mcp/tools/verify.py` + `shared/mcp/tools/iso.py`
- Design decisions: `docs/V3_DESIGN_DECISIONS.md` #2, #9
- Build sequence: `docs/V3_BUILD_SEQUENCE.md` Part 1.4 #6
- Subsystem boundary: `verify/SUBSYSTEM_BOUNDARY.md`
