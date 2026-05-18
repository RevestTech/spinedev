"""Evidence exporters — push batches to GRC vendors.

Day 1 (real implementations, per V3 #24):
  * ``vanta``       — HTTP POST to Vanta evidence API
  * ``drata``       — HTTP POST to Drata evidence API
  * ``secureframe`` — HTTP POST to Secureframe evidence API

v1.1+ (stubs with config + auth wired; ``send()`` raises
``NotImplementedError("v1.1+")``):
  * ``tugboat``      — Tugboat Logic
  * ``strikegraph``  — Strike Graph
  * ``thoropass``    — Thoropass

All exporter credentials route through ``shared.secrets.get_secret``;
the vault path convention is::

    evidence/<vendor>/api_key       # bearer token / API key
    evidence/<vendor>/api_url       # optional URL override

Per #9 the value is read fresh on every export, never cached on the
exporter instance, and dropped as soon as the HTTP request returns.
"""
from __future__ import annotations

from evidence.exporters._base import BaseExporter, EVIDENCE_VAULT_PREFIX

__all__ = ["BaseExporter", "EVIDENCE_VAULT_PREFIX"]
