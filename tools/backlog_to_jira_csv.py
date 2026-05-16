#!/usr/bin/env python3
"""Convert docs/BACKLOG.md to a bulk-importable CSV for Jira / Linear / GitHub Issues.

Implements STORY-5.3.1. See docs/research/COMPETITIVE_LANDSCAPE.md for *why*.

Markdown shape (state machine):
    ## INIT-N — <title>                                          -> Initiative
    ### EPIC-N.M — <title>                                       -> Epic (parent=INIT-N)
    - `STORY-N.M.K` · `status` · `priority` · `size` — <body>    -> Story (parent=EPIC-N.M)
The "**Tier:** N" line under an INIT header becomes a `tier-N` label, inherited by children.
The "## Sprint Plan" table maps story IDs to `Sprint K`.

Stdlib only (csv + re + argparse + pathlib). Python 3.11+.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

STATUS_MAP = {"Backlog": "To Do", "In Design": "To Do", "In Progress": "In Progress",
              "Done": "Done", "Won't Do": "Won't Do", "—": "To Do"}
PRIORITY_MAP = {"P0": "Highest", "P1": "High", "P2": "Medium", "P3": "Low", "—": "Medium"}
SIZE_TO_POINTS = {"XS": 1, "S": 2, "M": 5, "L": 13, "XL": 21}


@dataclass
class Item:
    issue_type: str          # Initiative / Epic / Story
    key: str                 # INIT-1 / EPIC-1.2 / STORY-1.2.3
    summary: str
    description: str = ""
    status: str = "Backlog"
    priority: str = "—"
    size: str = ""
    parent: str = ""
    labels: list[str] = field(default_factory=list)
    sprint: str = ""

    @property
    def init_num(self) -> str:
        return self.key.split("-", 1)[1].split(".", 1)[0]


INIT_RE = re.compile(r"^## (INIT-\d+)\s*[—-]\s*(.+?)\s*$")
EPIC_RE = re.compile(r"^### (EPIC-\d+\.\d+)\s*[—-]\s*(.+?)\s*$")
STORY_RE = re.compile(
    r"^-\s*`(STORY-\d+\.\d+\.\d+)`"
    r"\s*·\s*`?([^`·]+?)`?"
    r"\s*·\s*`?([^`·]+?)`?"
    r"\s*·\s*`?([^`·]+?)`?"
    r"\s*[—-]\s*(.+)$"
)
TIER_RE = re.compile(r"\*\*Tier:\*\*\s*([^·\n]+)")
SPRINT_HDR_RE = re.compile(r"^### Sprint\s*(\d+)")
SPRINT_ROW_RE = re.compile(r"^\|\s*`?(STORY-\d+\.\d+\.\d+)")


def parse_backlog(text: str) -> tuple[list[Item], dict[str, str]]:
    """Walk the markdown once; return (items, story->sprint map)."""
    items: list[Item] = []
    story_sprint: dict[str, str] = {}
    cur_init: Item | None = None
    cur_epic: Item | None = None
    init_buf: list[str] = []
    epic_buf: list[str] = []
    cur_sprint: str | None = None
    in_sprint_table = False

    def flush_meta(item: Item | None, buf: list[str]) -> None:
        if item and buf:
            item.description = "\n".join(buf).strip()
            m = TIER_RE.search(item.description)
            if m and item.issue_type == "Initiative":
                tier = m.group(1).strip().rstrip("·").strip()
                if tier:
                    item.labels.append(f"tier-{tier.lower().replace(' ', '-')}")
        buf.clear()

    for raw in text.splitlines():
        line = raw.rstrip()

        sp_hdr = SPRINT_HDR_RE.match(line)
        if sp_hdr:
            cur_sprint, in_sprint_table = f"Sprint {sp_hdr.group(1)}", False
            continue
        if cur_sprint and line.startswith("|") and "Story" in line and "What" in line:
            in_sprint_table = True
            continue
        if cur_sprint and in_sprint_table:
            sp_row = SPRINT_ROW_RE.match(line)
            if sp_row:
                story_sprint[sp_row.group(1)] = cur_sprint
                continue
            if not line.startswith("|"):
                in_sprint_table = False

        m = INIT_RE.match(line)
        if m:
            flush_meta(cur_epic, epic_buf)
            flush_meta(cur_init, init_buf)
            cur_epic = None
            cur_init = Item("Initiative", m.group(1), m.group(2).strip(),
                            status="In Progress", priority="P0")
            items.append(cur_init)
            continue

        m = EPIC_RE.match(line)
        if m:
            flush_meta(cur_epic, epic_buf)
            cur_epic = Item("Epic", m.group(1), m.group(2).strip(),
                            status="In Progress",
                            priority=cur_init.priority if cur_init else "—",
                            parent=cur_init.key if cur_init else "")
            items.append(cur_epic)
            continue

        m = STORY_RE.match(line)
        if m:
            key, status, priority, size, body = (s.strip() for s in m.groups())
            items.append(Item(
                "Story", key, _summary(body), description=body,
                status=status if status in STATUS_MAP else "Backlog",
                priority=priority if priority in PRIORITY_MAP else "—",
                size=size if size in SIZE_TO_POINTS else "",
                parent=cur_epic.key if cur_epic else (cur_init.key if cur_init else ""),
            ))
            continue

        if cur_epic is not None and line and not line.startswith(("##", "###", "- ")):
            epic_buf.append(line)
        elif cur_init is not None and cur_epic is None and line and not line.startswith(("##", "###", "- ")):
            init_buf.append(line)

    flush_meta(cur_epic, epic_buf)
    flush_meta(cur_init, init_buf)
    return items, story_sprint


def _summary(body: str) -> str:
    head = body.split(". ", 1)[0].strip()
    head = re.sub(r"\*\(Done [^)]+\)\*", "", head).strip().rstrip(".")
    return head[:120] + ("…" if len(head) > 120 else "")


def enrich(items: list[Item], story_sprint: dict[str, str]) -> list[Item]:
    """Attach inherited tier labels, sprint tags, type labels."""
    by_key = {it.key: it for it in items}
    for it in items:
        if it.issue_type in ("Epic", "Story"):
            parent_init = by_key.get(f"INIT-{it.init_num}")
            if parent_init:
                for lbl in parent_init.labels:
                    if lbl.startswith("tier-") and lbl not in it.labels:
                        it.labels.append(lbl)
        if it.issue_type == "Story":
            sprint = story_sprint.get(it.key)
            if sprint:
                it.sprint = sprint
                it.labels.append(sprint.lower().replace(" ", "-"))
        it.labels.append(it.issue_type.lower())
    return items


def _points(size: str) -> str:
    return str(SIZE_TO_POINTS.get(size, "")) if size else ""


def jira_row(it: Item) -> dict[str, str]:
    # Jira convention: space-separated labels; External ID = stable Spine key for re-import.
    return {"Issue Type": it.issue_type, "Issue Key": it.key, "Summary": it.summary,
            "Description": it.description, "Status": STATUS_MAP.get(it.status, "To Do"),
            "Priority": PRIORITY_MAP.get(it.priority, "Medium"), "Parent": it.parent,
            "Labels": " ".join(it.labels), "Story Points": _points(it.size),
            "Sprint": it.sprint, "External ID": it.key}


def linear_row(it: Item) -> dict[str, str]:
    # Linear convention: comma-separated labels; Identifier doubles as external ID.
    return {"Title": it.summary, "Description": it.description,
            "Status": STATUS_MAP.get(it.status, "Backlog"),
            "Priority": PRIORITY_MAP.get(it.priority, "Medium"),
            "Estimate": _points(it.size), "Labels": ",".join(it.labels),
            "Parent Issue": it.parent, "Cycle": it.sprint, "Identifier": it.key}


def github_row(it: Item) -> dict[str, str]:
    parts = [it.description]
    if it.parent:  parts.append(f"\nParent: `{it.parent}`")
    if it.sprint:  parts.append(f"Sprint: {it.sprint}")
    if it.size:    parts.append(f"Size: {it.size} ({SIZE_TO_POINTS.get(it.size, '?')} pts)")
    return {"title": f"[{it.key}] {it.summary}",
            "body": "\n".join(p for p in parts if p),
            "labels": ",".join(it.labels + [f"priority-{it.priority.lower()}"]),
            "state": "closed" if it.status == "Done" else "open"}


FORMATS = {
    "jira":   (jira_row,   ["Issue Type", "Issue Key", "Summary", "Description", "Status",
                            "Priority", "Parent", "Labels", "Story Points", "Sprint", "External ID"]),
    "linear": (linear_row, ["Title", "Description", "Status", "Priority", "Estimate",
                            "Labels", "Parent Issue", "Cycle", "Identifier"]),
    "github": (github_row, ["title", "body", "labels", "state"]),
}


def apply_filters(items: list[Item], args: argparse.Namespace) -> list[Item]:
    out: list[Item] = []
    epic_init = args.epic_filter.split(".")[0] if args.epic_filter else None
    for it in items:
        if args.init_filter is not None and it.init_num != str(args.init_filter):
            continue
        if args.epic_filter and not (
            it.key == f"EPIC-{args.epic_filter}"
            or it.key.startswith(f"STORY-{args.epic_filter}.")
            or (it.issue_type == "Initiative" and it.key == f"INIT-{epic_init}")
        ):
            continue
        if it.status == "Done" and not args.include_done:
            continue
        if it.status == "Won't Do" and not args.include_wont_do:
            continue
        out.append(it)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--backlog", type=Path, default=Path("docs/BACKLOG.md"))
    p.add_argument("--output", type=Path, default=Path("backlog.csv"))
    p.add_argument("--init-filter", type=int, default=None, help="Only emit items under INIT-N.")
    p.add_argument("--epic-filter", type=str, default=None, help="Only emit items under EPIC-N.M.")
    p.add_argument("--include-done", action="store_true", help="Include Done items (default: skip).")
    p.add_argument("--include-wont-do", action="store_true", help="Include Won't Do items (default: skip).")
    p.add_argument("--format", choices=sorted(FORMATS), default="jira")
    args = p.parse_args(argv)

    if not args.backlog.exists():
        print(f"backlog file not found: {args.backlog}", file=sys.stderr)
        return 2

    text = args.backlog.read_text(encoding="utf-8")
    items, story_sprint = parse_backlog(text)
    items = enrich(items, story_sprint)
    items = apply_filters(items, args)

    row_fn, headers = FORMATS[args.format]
    with args.output.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=headers, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        for it in items:
            w.writerow(row_fn(it))

    counts: dict[str, int] = {"Initiative": 0, "Epic": 0, "Story": 0}
    for it in items:
        counts[it.issue_type] = counts.get(it.issue_type, 0) + 1
    print(f"wrote {sum(counts.values())} rows to {args.output} "
          f"({counts['Initiative']} initiatives, {counts['Epic']} epics, {counts['Story']} stories) "
          f"format={args.format}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
