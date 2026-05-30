"""Per-layer checks for the 12-layer agent-stack audit (V3 B10).

Each module under this package implements ONE layer's check function
matching the contract in :class:`verify.agent_audit.twelve_layer.LayerCheck`.
Splitting layers into one-file-per-layer keeps the main `twelve_layer`
module short and lets future instrumentation work proceed in parallel
without touching shared state.

Wiring into ``DEFAULT_CHECKS`` happens in :mod:`verify.agent_audit.twelve_layer`
itself — never edit that wiring from inside this package; flag a request
upstream instead.
"""
