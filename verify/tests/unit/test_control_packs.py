"""Built-in compliance reference control packs."""

from tron.standards.control_packs import (
    format_packs_for_prompt,
    list_pack_ids,
    load_pack,
)


def test_list_pack_ids_includes_shipped_packs():
    ids = list_pack_ids()
    assert "soc2_reference" in ids
    assert "hipaa_reference" in ids
    assert "iso27001_reference" in ids


def test_load_pack_has_themes():
    p = load_pack("soc2_reference")
    assert p["id"] == "soc2_reference"
    assert isinstance(p.get("themes"), list)
    assert len(p["themes"]) >= 1


def test_format_packs_for_prompt_merges():
    text = format_packs_for_prompt(["soc2_reference", "unknown_pack"])
    assert "SOC 2" in text or "soc2" in text.lower()
    assert "cpa" in text.lower() or "not legal" in text.lower() or "not a" in text.lower()
