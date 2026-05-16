"""``spine memory`` CLI — STORY-4.2.2 / STORY-4.2.3.

recall / index / playbook (recall|promote) / stats / eviction-candidates.
Always emits JSON to stdout for easy piping.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from .lesson_indexer import index_role_memory
from .lesson_store import (DEFAULT_DB_URL, _psql,
                           format_for_prompt_injection, recall_lessons)
from .playbook_store import PlaybookStore, promote_to_playbook


def _db() -> str:
    return (os.environ.get("SPINE_DB_URL")
            or os.environ.get("DATABASE_URL") or DEFAULT_DB_URL)

def _emit(obj: object) -> None:
    print(json.dumps(obj, default=str, indent=2))


def _cmd_recall(a: argparse.Namespace) -> int:
    r = recall_lessons(a.role, a.query, a.project_id, a.top_k,
                       not a.no_cross_project)
    _emit({"query": r.query, "latency_ms": round(r.latency_ms, 2),
           "embeddings_generated": r.embeddings_generated,
           "lessons": [l.model_dump() for l in r.lessons],
           "prompt_injection": format_for_prompt_injection(r.lessons)}); return 0


def _cmd_index(a: argparse.Namespace) -> int:
    path = (Path(a.memory_path) if a.memory_path
            else Path("teams") / a.role / "memory.md")
    r = index_role_memory(a.role, path, a.project_id, "project")
    _emit(r.model_dump()); return 0


def _cmd_playbook_recall(a: argparse.Namespace) -> int:
    r = PlaybookStore().recall(a.role, a.query, top_k=a.top_k)
    _emit({"query": r.query, "latency_ms": round(r.latency_ms, 2),
           "lessons": [l.model_dump() for l in r.lessons]})
    return 0


def _cmd_playbook_promote(a: argparse.Namespace) -> int:
    p = promote_to_playbook(int(a.lesson_id), a.rationale)
    _emit({"lesson_id": int(a.lesson_id), "playbook_path": str(p)}); return 0


def _cmd_stats(a: argparse.Namespace) -> int:
    where = f"WHERE role = '{a.role}'" if a.role else ""
    sql = ("SELECT role, scope, COUNT(*), SUM(retrieval_count), "
           "MAX(last_retrieved) FROM spine_memory.v_lesson_freshness "
           f"{where} GROUP BY role, scope ORDER BY role, scope;")
    rows = [{"role": p[0], "scope": p[1], "lessons": int(p[2] or 0),
             "total_recalls": int(p[3] or 0), "last_recall": p[4] or None}
            for p in (ln.split("\x1f") for ln in _psql(sql, _db()).splitlines())
            if len(p) >= 5]
    _emit({"stats": rows}); return 0


def _cmd_eviction(a: argparse.Namespace) -> int:
    w = ["valid_to IS NULL", "retrieval_count = 0",
         f"created_at < now() - INTERVAL '{int(a.age_days)} days'"]
    if a.role:
        w.append(f"role = '{a.role}'")
    sql = ("SELECT id, role, scope, lesson_text, "
           "EXTRACT(EPOCH FROM (now() - created_at))/86400.0 "
           f"FROM spine_memory.lesson WHERE {' AND '.join(w)} "
           "ORDER BY 5 DESC LIMIT 200;")
    rows = [{"id": int(p[0]), "role": p[1], "scope": p[2],
             "lesson_text": p[3], "age_days": round(float(p[4]), 1)}
            for p in (ln.split("\x1f") for ln in _psql(sql, _db()).splitlines())
            if len(p) >= 5]
    _emit({"candidates": rows, "age_days_threshold": int(a.age_days)})
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spine-memory")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("recall"); r.add_argument("--role", required=True)
    r.add_argument("--query", required=True); r.add_argument("--project-id")
    r.add_argument("--top-k", type=int, default=5)
    r.add_argument("--no-cross-project", action="store_true")
    r.set_defaults(fn=_cmd_recall)
    i = sub.add_parser("index"); i.add_argument("--role", required=True)
    i.add_argument("--memory-path"); i.add_argument("--project-id")
    i.set_defaults(fn=_cmd_index)
    pb = sub.add_parser("playbook")
    psub = pb.add_subparsers(dest="pcmd", required=True)
    pr = psub.add_parser("recall"); pr.add_argument("--role", required=True)
    pr.add_argument("--query", required=True)
    pr.add_argument("--top-k", type=int, default=5)
    pr.set_defaults(fn=_cmd_playbook_recall)
    pp = psub.add_parser("promote"); pp.add_argument("--lesson-id", required=True)
    pp.add_argument("--rationale", required=True)
    pp.set_defaults(fn=_cmd_playbook_promote)
    s = sub.add_parser("stats"); s.add_argument("--role")
    s.set_defaults(fn=_cmd_stats)
    e = sub.add_parser("eviction-candidates"); e.add_argument("--role")
    e.add_argument("--age-days", type=int, default=90)
    e.set_defaults(fn=_cmd_eviction)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
