"""Unit tests for the migration subsystem (Wave 5 Squad F).

Per ADR-F-003 (see ``migration/README.md``) every external surface is
mocked — no live Postgres, no real Vault, no GitHub/Linear API calls.
The round-trip test is deterministic by construction.
"""
