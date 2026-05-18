# Spine — Voice (SCAFFOLD)

> **Status:** v1.0 scaffold. Per V3 design decision **#29 (Voice /
> phone = SCAFFOLD for v1.0)** the v1.0 ship date includes:
>
> 1. a **voice-integration interface** (which decisions can be
>    voice-approved + which roles can be voice-reached) — implemented
>    at `shared/api/routes/voice.py`;
> 2. a **Twilio webhook receiver** with real signature validation but
>    stubbed call routing — implemented at
>    `voice/twilio_adapter.py`;
> 3. **no actual voice flows** — deferred to v1.1+ on customer demand.

---

## v1.0 — what actually ships

| Surface | Where | Realness |
|---|---|---|
| Voice-integration catalogue | `GET /api/v2/voice/catalog` (in `shared/api/routes/voice.py`) | Real — defines voice-approvable decisions + voice-reachable roles |
| Twilio webhook receiver | `POST /api/v2/voice/webhook/twilio` | Real signature validation; stubbed TwiML response |
| Twilio adapter | `voice/twilio_adapter.py` | Constructor + config wiring real; `route_call()` raises `NotImplementedError("v1.1+")` |
| Vault wiring | `notify/twilio/{account_sid,auth_token,from_number}` | Real — same vault paths used by `shared/notify/channels.SMSChannel` |

**Explicit v1.0 framing for the website:** *"v1.0 = Twilio scaffold +
Hub voice-catalogue; actual phone flows = v1.1+ on demand."*

---

## v1.1+ — actual voice-flow plan

Activation trigger: a customer asks for a voice flow (most likely
*"Master CTO callable for incidents"* per the **#29** narrative).

### Likely first flow — Master CTO callable for incidents

1. **Inbound call hits** `/api/v2/voice/webhook/twilio`.
2. Receiver validates Twilio signature (already real in v1.0).
3. `voice.twilio_adapter.route_call(params)` (v1.1+) inspects the
   dialed number / caller ID against the **voice-reachable roles**
   catalogue and the **on-call schedule** in `devops/` (per **#11** —
   Operate subsystem).
4. Replies with TwiML directing Twilio to either:
   * `<Say>` an LLM-generated incident briefing (TTS via Twilio's
     `Polly.Joanna` voice) and `<Gather>` DTMF for approve / page-out;
   * `<Dial>` to a human on-call number (failover to PagerDuty per
     **#6** if the AI role can't reach the right decision);
   * `<Hangup>` with audit trail entry if caller-ID is not
     allowed-listed.
5. DTMF response → `POST /voice_approve_decision` MCP tool (registered
   with `requires_citation=True` per **#12** — Cite-or-Refuse).

### Other likely v1.1+ flows

| Flow | Trigger |
|---|---|
| Daily briefing voice push | Cron — `shared/notify` channel `voice` fans out |
| Outbound approval call | Critical decision card with severity=critical and channel preference=voice |
| Compliance voice attestation | Vanta/Drata workflow (per **#24**) requesting verbal sign-off |

---

## Why scaffold-only on Day 1

Per the **#29 decision rationale** in `docs/V3_DESIGN_DECISIONS.md`:

* Voice is **high-stakes** — wrong TwiML can hang up on a CTO during an
  incident, and Twilio bills per second of call time. Shipping without
  customer-validated flows is a misuse of the channel.
* The **integration surface** (this scaffold) is the hard part. Once
  the contract exists, v1.1+ flows are bash-and-LLM work.
* Real signature validation in v1.0 means **the moment a customer asks
  for a flow we are 1-2 days from delivering it**, not 4-6 weeks.

---

## Directory layout

```
voice/
├── __init__.py             ← package marker + VOICE_ROUTING_AVAILABLE flag
├── README.md               ← this file
├── twilio_adapter.py       ← signature helper (real) + route_call() stub (v1.1+)
└── tests/
    ├── __init__.py
    ├── conftest.py
    └── test_voice_scaffold.py
```

---

## How v1.1+ teams pick this up

1. Read this README + `docs/V3_DESIGN_DECISIONS.md` #29.
2. Confirm a customer voice-flow request is on the backlog
   (`docs/PRD.md` v1.1+ section).
3. Populate vault paths:
   * `notify/twilio/account_sid`
   * `notify/twilio/auth_token`
   * `notify/twilio/from_number`
   * `voice/twilio/incident_call_number` (NEW for v1.1+)
4. Implement `voice.twilio_adapter.route_call(params) -> str` returning
   TwiML XML; remove the `NotImplementedError("v1.1+")` guard.
5. Register `voice_approve_decision` as an MCP tool in
   `shared/mcp/tools/voice.py` **with `requires_citation=True`** per
   **#12**.
6. Flip `VOICE_ROUTING_AVAILABLE` in `voice/__init__.py` to `True`.
7. Add a feature flag `channel_voice` to
   `shared/api/middleware/feature_flag.KNOWN_FEATURE_FLAGS` and gate
   `/api/v2/voice/webhook/twilio` behind it (currently always-on per
   the scaffold contract).

---

## References

* `docs/V3_DESIGN_DECISIONS.md` #29 (Voice = SCAFFOLD for v1.0 via Twilio)
* `docs/V3_DESIGN_DECISIONS.md` #12 (Cite-or-Refuse for verify-class)
* `docs/V3_DESIGN_DECISIONS.md` #9 (Vault-only secrets)
* `docs/V3_BUILD_SEQUENCE.md` Wave 6 Stream I
* `shared/api/routes/voice.py` (the voice-integration interface)
* `shared/notify/channels.py` `SMSChannel` / `WhatsAppChannel` (Twilio
  cousin scaffolds shipped in Wave 1)
