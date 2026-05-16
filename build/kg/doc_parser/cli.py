"""``spine doc-parse`` CLI — STORY-6.3.1/2/3 wrapper.

Subcommands: ``parse <file> [--type …]`` (JSON of nodes/edges);
``reindex [--root docs/]`` (walk + parse + JSON summary); ``validate
<file>`` (parse + report extracted counts); ``references <file>`` (list
embedded Spine IDs). Exit codes mirror the indexer CLI: 0 success/no-op,
1 work done with errors, 2 fatal config error. Called by humans during
development and by the indexer integration follow-up story.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from .markdown_parser import ParsedDoc, parse_markdown
from .role_prompt_parser import parse_memory_md, parse_playbook, parse_role_prompt
from .spine_doc_parser import (parse_adr, parse_changelog, parse_prd, parse_req,
                               parse_roadmap, parse_trd, parser_for_path)
from .spine_id_resolver import extract_references, resolve_references

log = logging.getLogger("spine.kg.doc_parser.cli")

_PARSERS = {"req": parse_req, "prd": parse_prd, "trd": parse_trd,
            "roadmap": parse_roadmap, "adr": parse_adr,
            "changelog": parse_changelog, "role": parse_role_prompt,
            "memory": parse_memory_md, "playbook": parse_playbook,
            "markdown": parse_markdown}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    args = _build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except FileNotFoundError as e:
        log.error("not found: %s", e); return 2
    except RuntimeError as e:
        log.error("fatal: %s", e); return 2


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spine doc-parse",
                                description="Spine KG document parser")
    sub = p.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("parse", help="Parse one doc → JSON")
    pr.add_argument("file"); pr.add_argument("--repo", default="spine")
    pr.add_argument("--type", default=None, choices=sorted(_PARSERS))
    re_ = sub.add_parser("reindex", help="Walk and parse every .md")
    re_.add_argument("--root", default="docs"); re_.add_argument("--repo", default="spine")
    re_.add_argument("--dry-run", action="store_true")
    va = sub.add_parser("validate", help="Parse cleanly + report extracted")
    va.add_argument("file"); va.add_argument("--type", default=None, choices=sorted(_PARSERS))
    rf = sub.add_parser("references", help="List embedded Spine IDs")
    rf.add_argument("file"); rf.add_argument("--resolve", action="store_true")
    return p


def _dispatch(args: argparse.Namespace) -> int:
    if args.cmd == "parse":
        return _emit(_parse_one(Path(args.file), args.type, args.repo))
    if args.cmd == "reindex":
        return _reindex(Path(args.root), args.repo, args.dry_run)
    if args.cmd == "validate":
        doc = _parse_one(Path(args.file), args.type, "spine")
        return _validate(doc)
    if args.cmd == "references":
        return _references(Path(args.file), args.resolve)
    return 2


def _parse_one(fp: Path, type_hint: str | None, repo: str) -> ParsedDoc:
    content = fp.read_text(encoding="utf-8")
    if type_hint:
        return _PARSERS[type_hint](content, str(fp), repo=repo)
    return parser_for_path(str(fp))(content, str(fp), repo=repo)

def _emit(doc: ParsedDoc) -> int:
    print(json.dumps({"doc_path": doc.doc_path, "text_hash": doc.text_hash,
        "subtype": doc.document_node.subtype,
        "nodes": [n.model_dump() for n in doc.all_nodes],
        "edges": [e.model_dump() for e in doc.all_edges],
        "counts": {"nodes": len(doc.all_nodes), "edges": len(doc.all_edges)}},
        indent=2, default=str)); return 0

def _reindex(root: Path, repo: str, dry_run: bool) -> int:
    n_nodes = n_edges = files = errors = 0
    for fp in sorted(root.rglob("*.md")):
        if any(p in fp.parts for p in ("node_modules", ".git", "_archived")):
            continue
        try:
            doc = _parse_one(fp, None, repo)
        except Exception as e:  # noqa: BLE001
            log.warning("parse failure %s: %s", fp, e); errors += 1; continue
        files += 1
        n_nodes += len(doc.all_nodes); n_edges += len(doc.all_edges)
    print(json.dumps({"files": files, "nodes": n_nodes, "edges": n_edges,
                      "errors": errors, "dry_run": dry_run}, indent=2))
    return 1 if errors else 0

def _validate(doc: ParsedDoc) -> int:
    print(json.dumps({"doc_path": doc.doc_path,
        "subtype": doc.document_node.subtype, "headings": len(doc.headings),
        "links": len(doc.links), "references": len(doc.references),
        "custom_nodes": len(doc.custom_nodes),
        "custom_edges": len(doc.custom_edges),
        "text_hash": doc.text_hash}, indent=2)); return 0

def _references(fp: Path, do_resolve: bool) -> int:
    refs = extract_references(fp.read_text(encoding="utf-8"))
    if do_resolve: refs = resolve_references(refs)
    print(json.dumps([r.model_dump() for r in refs], indent=2)); return 0

if __name__ == "__main__":
    sys.exit(main())
