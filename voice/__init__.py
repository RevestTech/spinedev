"""Spine voice subsystem — SCAFFOLD per V3 design decision #29.

v1.0 ships:

* a **voice-integration interface** at ``shared/api/routes/voice.py``
  (declares which decisions are voice-approvable and which roles are
  voice-reachable), and
* a **Twilio webhook receiver** with **real** signature validation (per
  #9 — vault-only secrets) but **stubbed call routing** (returns
  ``NotImplementedError("v1.1+")`` from
  :mod:`voice.twilio_adapter`).

v1.1+ adds the actual voice flows — the most likely first flow is
*"Master CTO callable for critical incidents"* per the #29 narrative in
``docs/V3_DESIGN_DECISIONS.md``.

See ``voice/README.md`` for the v1.1+ build plan.
"""

from __future__ import annotations

#: Module version — bumps when the scaffold contract changes (NOT when
#: v1.1+ implementations land; those live in their own version).
__version__ = "0.1.0-scaffold"

#: Whether real voice-call routing is available. Always ``False`` in
#: v1.0; set to ``True`` when ``voice/twilio_adapter.py`` ships actual
#: TwiML production + DTMF capture (v1.1+).
VOICE_ROUTING_AVAILABLE: bool = False


__all__ = ["__version__", "VOICE_ROUTING_AVAILABLE"]
