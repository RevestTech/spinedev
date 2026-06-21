"""Canned intake turn scripts for autonomous / golden-path runs."""

from __future__ import annotations

from typing import Any

_PROFILES: dict[str, list[str]] = {
    "cli": [
        (
            "Greenfield CLI todo app in Python. Single-file MVP with add/list/complete "
            "commands. Solo developer on laptop."
        ),
        (
            "Success: run `python todo.py add \"buy milk\"` then `list` shows it; "
            "`done 1` marks complete. Stdlib only, optional JSON persistence."
        ),
        (
            "Out of scope: accounts, cloud sync, web UI, packaging to PyPI. "
            "Ship in one session today."
        ),
        (
            "No budget/deadline beyond today. Top risk is scope creep — keep one file. "
            "You have enough context — end intake with [INTAKE_COMPLETE] on its own line."
        ),
    ],
    "website": [
        (
            "Greenfield marketing website MVP. Stack: Next.js 14 App Router, TypeScript, "
            "Tailwind CSS. Solo founder, deployable with `npm run dev` on localhost."
        ),
        (
            "Success criteria: a responsive landing page with hero headline, three feature "
            "cards, and a primary CTA button linking to a real /contact page you also build. "
            "Include package.json with a dev script. Must bind to process.env.PORT."
        ),
        (
            "Out of scope: auth, CMS, backend API, payments, database. No external APIs. "
            "Keep to 5-12 files — ship in one session today."
        ),
        (
            "No budget beyond today. Top risk is scope creep — landing + contact only. "
            "You have enough context — end intake with [INTAKE_COMPLETE] on its own line."
        ),
    ],
    "jellybeans": [
        (
            "I am a customer who wants a website about jelly beans — fun, colorful, "
            "family-friendly. Stack: Next.js 14 App Router, TypeScript, Tailwind CSS. "
            "Deployable with `npm run dev` on localhost. Solo founder on a laptop."
        ),
        (
            "Success: landing page hero about jelly beans, three feature cards (flavors, "
            "history, fun facts), primary CTA to a /contact page. Contact page has a "
            "simple form UI (no backend). package.json with dev script; bind to "
            "process.env.PORT."
        ),
        (
            "Out of scope: e-commerce, accounts, CMS, database, payments, external APIs. "
            "5-12 files max — ship in one session today."
        ),
        (
            "No budget beyond today. Top risk is scope creep — jelly bean marketing site "
            "only. You have enough context — end intake with [INTAKE_COMPLETE] on its own "
            "line."
        ),
    ],
}


def prompts_for_project(metadata: dict[str, Any] | None) -> list[str]:
    """Pick intake script from metadata or fall back to description-first."""
    md = metadata or {}
    profile = str(md.get("golden_path_profile") or "cli").strip().lower()
    canned = _PROFILES.get(profile, _PROFILES["cli"])
    description = str(md.get("description") or "").strip()
    if description and profile == "cli" and not md.get("golden_path_profile"):
        return [description, *canned[1:]]
    return list(canned)


def next_intake_message(
    metadata: dict[str, Any] | None,
    *,
    turn_index: int,
) -> str:
    """Return the user message for turn ``turn_index`` (1-based)."""
    prompts = prompts_for_project(metadata)
    if turn_index <= len(prompts):
        return prompts[turn_index - 1]
    return (
        "Confirm intake is complete. Reply with [INTAKE_COMPLETE] on its own line "
        "so the system can draft the PRD."
    )


__all__ = ["next_intake_message", "prompts_for_project"]
