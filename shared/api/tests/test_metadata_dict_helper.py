"""Tests for ``shared.api.routes.projects._metadata_dict``.

Regression coverage for the Hub 500 the user hit on 2026-05-30 when
DELETE /api/v2/projects/{uuid} crashed with::

    ValueError: dictionary update sequence element #0 has length 1; 2
    is required

The fix routes archive / restore / delete through a tolerant helper;
this test pins the four shapes the helper has to handle.
"""
from __future__ import annotations

from shared.api.routes.projects import _metadata_dict


def test_dict_passes_through_as_a_new_copy() -> None:
    src = {"a": 1, "nested": {"b": 2}}
    out = _metadata_dict(src)
    assert out == src
    # Helper must return a NEW dict so subsequent mutations don't
    # leak back into the original row payload.
    out["a"] = 99
    assert src["a"] == 1


def test_json_string_is_parsed() -> None:
    raw = '{"phase": "intake", "intake_done": false}'
    out = _metadata_dict(raw)
    assert out == {"phase": "intake", "intake_done": False}


def test_invalid_json_string_yields_empty_dict() -> None:
    out = _metadata_dict("not-valid-json{{{")
    assert out == {}


def test_none_yields_empty_dict() -> None:
    assert _metadata_dict(None) == {}


def test_list_json_string_yields_empty_dict() -> None:
    # JSON parses fine but isn't a mapping — must not return the list.
    out = _metadata_dict('["a", "b"]')
    assert out == {}


def test_integer_payload_yields_empty_dict() -> None:
    # Defensive: any non-(dict|str) payload yields an empty dict.
    assert _metadata_dict(42) == {}
