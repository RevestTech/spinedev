# shared/llm — Single LLM Call Surface

**Status:** Wave 0 (V3 BUILD-NEW) — every Wave 1+ feature that calls an LLM uses this module.

**Why this exists:** V3 Decision #2 (LLM-agnostic by architecture). Routes across Anthropic / OpenAI / Bedrock / Vertex / Ollama / Qwen / vLLM. Customer chooses. Spine never marries one provider.

**What this is NOT:**
- Not a model selector (that's `shared/cost/router.py` — it produces `model_id` strings we accept).
- Not a cost ledger (that's `shared/cost/router.py` reading our `Usage`).
- Not an audit emitter (the caller's daemon owns audit writes).
- Not a phase / severity gate (that's `shared/validation/`).

---

## Public API

```python
from shared.llm import (
    call, call_async, stream_async,            # entry points
    LLMRequest, LLMResponse, Message,           # request/response models
    ToolCall, Usage,                            # auxiliary models
    get_provider, register_provider,            # registry surface (advanced)
    RetryPolicy, retry_async,                   # retry surface (advanced)
)

# Sync call (CLI / script)
resp = call(LLMRequest(
    model="claude-sonnet-4-6",
    messages=[Message(role="user", content="Hello")],
    max_tokens=512,
))
print(resp.content, resp.usage)

# Async call (FastAPI / daemons)
resp = await call_async(request)

# Streaming
async for chunk in stream_async(request):
    print(chunk.content, end="", flush=True)
```

---

## Provider Matrix

| Provider | Routing Prefix | Wire Protocol | Streaming | Tools | Prompt Cache | Auth (Wave 0) | Auth (Wave 1) |
|---|---|---|---|---|---|---|---|
| Anthropic | `claude-*` | SDK (`anthropic`) | Yes | Yes | **Yes** | `ANTHROPIC_API_KEY` env | vault `llm/anthropic_api_key` |
| OpenAI | `gpt-*` | SDK (`openai`) | Yes | Yes | No (auto) | `OPENAI_API_KEY` env | vault `llm/openai_api_key` |
| AWS Bedrock | `bedrock:*` | SDK (`boto3` Converse) | Yes | Yes | No | boto3 default chain | vault-minted STS via `llm/bedrock_role_arn` |
| GCP Vertex | `vertex:*` | SDK (`google-cloud-aiplatform`) | Yes | Yes | No (Wave 1+) | ADC + `GOOGLE_CLOUD_PROJECT` | vault SA key `llm/vertex_service_account` |
| Ollama | `ollama:*` | HTTP (`httpx`) | Yes | Yes | No | None (local) | None |
| Qwen / DashScope | `qwen:*` | HTTP (`httpx`, OpenAI-compat) | Yes | Yes | No | `DASHSCOPE_API_KEY` env | vault `llm/dashscope_api_key` |
| Self-hosted vLLM | `vllm:*` | HTTP (`httpx`, OpenAI-compat) | Yes | Yes | No | `VLLM_API_KEY` env (optional) | vault `llm/vllm_api_key` (optional) |

**Routing rule:** longest matching prefix wins. Unknown prefix → `UnknownProviderError`. No implicit defaults.

**Endpoints / regions:**
- Ollama: `OLLAMA_HOST` env (default `http://localhost:11434`)
- Qwen: `DASHSCOPE_BASE_URL` env (default international endpoint)
- vLLM: `VLLM_BASE_URL` env (default `http://localhost:8000/v1`)
- Vertex: `GOOGLE_CLOUD_PROJECT` + `GOOGLE_CLOUD_REGION` env
- Bedrock: standard AWS env / `~/.aws/config`

---

## Auth Posture (per V3 #2 + #9)

**Vault-only is the production target.** Per V3 #9 (no env-secrets), every provider credential MUST come from `shared/secrets/` via vault adapters (OpenBao / HashiCorp Vault / AWS Secrets Manager / Azure Key Vault / GCP Secret Manager / Infisical / 1Password).

**Wave 0 behavior:** `ProviderAdapter._get_api_key()` tries `shared.secrets.get_secret(name)` first (soft import — module may not exist yet), then falls back to the documented env var for local dev / testing.

**Wave 1 MUST replace this with vault-only.** Tracking marker: search for `TODO Wave 1: replace with shared.secrets.get_secret` in `providers/base.py`. Production deployments will fail-closed when env-var fallback is removed — this is intentional per #9.

**Never** check API keys into the repo. **Never** log API keys. **Never** pass keys via `LLMRequest` (the model is deliberately not extensible there).

---

## Prompt Caching (Anthropic)

The Anthropic adapter absorbs the prompt-cache logic from `shared/cost/prompt_cache.py` (which Wave 1 deletes per V3 triage row). Pass `cache_breakpoints=[indices]` on the request:

```python
req = LLMRequest(
    model="claude-sonnet-4-6",
    system="You are an expert reviewer ... [stable long prefix]",
    messages=[Message(role="user", content=long_turn_0), ...],
    cache_breakpoints=[0],  # cache the system prompt + turn 0
)
```

**Contract preserved from legacy code:**
- At most 4 breakpoints per call (Anthropic SDK limit).
- Breakpoint indices `>= 0`, `< len(messages)`; deduped + sorted.
- When `cache_breakpoints` is non-empty AND a system prompt is set, the system prompt is automatically marked cacheable (the largest single win).
- `Usage.cache_read_tokens` + `Usage.cache_write_tokens` populated from response.

**Other providers ignore `cache_breakpoints`** silently. Check `get_provider(model).supports_prompt_caching` if you need to branch.

---

## Retry Policy

Hand-rolled (no `tenacity` dep). Default policy:
- 5 attempts (initial + 4 retries)
- Exponential backoff with full jitter (base 1.0s, multiplier 2.0, max 30.0s)
- Honors `retry_after_seconds` attribute on exceptions
- Retries: 429, 5xx, connection errors, timeouts, `*RateLimit*`/`*Timeout*`/`*Overloaded*` exception classes
- Never retries: 401, 403, 400, 422, `NonRetryableError`

Override per-call via `retry_async(policy=RetryPolicy(...))` decorator inside an adapter; the public `call`/`call_async` does NOT take a policy arg in Wave 0 (Wave 1 may add via `request.retry`).

---

## Streaming Contract

Every adapter's `stream_async` yields `LLMResponse` chunks where:
- `content` is a **delta** string (not cumulative).
- `usage` is populated on the final chunk (or whichever chunks the provider reports it on).
- `finish_reason` on the final chunk is the authoritative one.

`call_async(request)` with `request.stream=True` collapses the stream via `shared.llm.streaming.aggregate()` for callers that want a single response. Use `stream_async()` directly to consume deltas.

---

## Dependencies

Listed here (NOT modifying `pyproject.toml` per Wave 0 scope). Install per provider you actually use:

| Provider | Pip Package | Notes |
|---|---|---|
| Anthropic | `anthropic >= 0.39` | Required for `claude-*` |
| OpenAI | `openai >= 1.50` | Required for `gpt-*` |
| Bedrock | `boto3 >= 1.34` | Required for `bedrock:*` |
| Vertex | `google-cloud-aiplatform >= 1.70` | Required for `vertex:*` |
| Ollama / Qwen / vLLM | `httpx >= 0.27` | Single shared HTTP dep |

Wave 1 wires these into `pyproject.toml` extras: `pip install spine[anthropic,openai]` etc.

---

## Extending (Customer Plugins)

```python
from shared.llm import register_provider, ProviderAdapter

class MyProvider(ProviderAdapter):
    name = "myprovider"
    model_prefix = "myprov:"
    supports_streaming = True
    async def call_async(self, request): ...
    async def stream_async(self, request): ...

register_provider("myprov:", lambda: MyProvider())
```

Customer plugins should register at import-time of their integration module. The registry uses longest-prefix-wins, so you can override built-ins by registering a more specific prefix (e.g. `bedrock:custom:` overrides `bedrock:` for matching models).

---

## Testing

All tests use mocks — no real LLM API calls:

```bash
python3 -m pytest shared/llm/tests/
```

Test files:
- `test_request.py` — Pydantic model validation
- `test_client_routing.py` — prefix routing matrix (all 7 providers)
- `test_anthropic_cache.py` — preserves the prompt-cache payload contract

---

## Wave 1+ Roadmap

- **Vault wiring** (#9): remove env-var fallback in `_get_api_key`.
- **Multimodal `Message.content`**: discriminated union of text/image/file blocks.
- **`response_format=`** for JSON mode / structured outputs.
- **Cost-projection hook** so the cost ledger sees every call (currently caller's daemon does this).
- **Vertex context caching** (Anthropic-on-Vertex inherits prompt cache).
- **Cross-LLM consensus** (`shared/validation/cross_llm.py`) refactored to call through this surface instead of inline SDK calls. Provider Literal extends to all 7 providers.
- **Bedrock prompt caching** for model families that ship it.

---

**Document control:**
- Wave 0 owner: Agent B
- Locked signatures: `LLMRequest`, `LLMResponse`, `Message`, `ToolCall`, `Usage`, `call`, `call_async`, `stream_async`, `get_provider`, `register_provider`
- Routing prefix list (#2 lock): `claude-` / `gpt-` / `bedrock:` / `vertex:` / `ollama:` / `qwen:` / `vllm:`
