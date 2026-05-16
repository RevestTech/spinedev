"""Tree-sitter runtime: consume YAML extractor configs from
`build/kg/extractors/`; emit `(nodes, edges)` matching `spine_kg.kg_node`
/ `kg_edge` from V2. Language-agnostic — all behaviour comes from YAML.
Synthetic tokens from `_schema.yaml` (`__file_root__`, `__self__`,
`__is_async__`, `__heading_level__`, `__match__`, `__relpath_dotted__`,
`__filename__`, `__infer_from_path__`) are interpreted here.
`tree_sitter` is lazy-imported; a missing grammar degrades to "file-root
only + warning" (REQ-INIT-6 FR-3)."""

from __future__ import annotations

import hashlib
import importlib
import logging
import re
import subprocess
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("spine.kg.parser_runtime")
EXTRACTORS_DIR = Path(__file__).resolve().parents[1] / "extractors"


@dataclass
class ExtractorConfig:
    language: str
    raw: dict
    include_globs: list[str] = field(default_factory=list)
    exclude_globs: list[str] = field(default_factory=list)
    grammars: list[dict] = field(default_factory=list)
    node_extractors: list[dict] = field(default_factory=list)
    edge_extractors: list[dict] = field(default_factory=list)
    test_path_patterns: list[re.Pattern] = field(default_factory=list)
    test_name_patterns: list[re.Pattern] = field(default_factory=list)


def load_extractors(extractors_dir: Path | None = None) -> dict[str, ExtractorConfig]:
    out: dict[str, ExtractorConfig] = {}
    for path in sorted((extractors_dir or EXTRACTORS_DIR).glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        raw = yaml.safe_load(path.read_text())
        grammars = raw.get("grammars") or ([raw["grammar"]] if raw.get("grammar") else [])
        ff = raw.get("file_filters") or {}; tfd = raw.get("test_file_detection") or {}
        out[raw["language"]] = ExtractorConfig(
            language=raw["language"], raw=raw,
            include_globs=list(ff.get("include_globs") or []),
            exclude_globs=list(ff.get("exclude_globs") or []),
            grammars=grammars,
            node_extractors=list(raw.get("node_extractors") or []),
            edge_extractors=list(raw.get("edge_extractors") or []),
            test_path_patterns=[re.compile(p) for p in (tfd.get("path_patterns") or [])],
            test_name_patterns=[re.compile(p) for p in (tfd.get("name_patterns") or [])])
    return out


def pick_extractor(rel_path: str, configs: dict[str, ExtractorConfig]) -> ExtractorConfig | None:
    for cfg in configs.values():
        if any(fnmatch(rel_path, p) for p in cfg.exclude_globs):
            continue
        if any(fnmatch(rel_path, p) for p in cfg.include_globs):
            return cfg
    return None


# ─── tree-sitter loader (lazy + CLI fallback probe) ──────────────────

_LANG_CACHE: dict[str, Any] = {}


def _load_language(grammar: dict):
    pkg = grammar["package"]; fn = grammar.get("language_function", "language")
    key = f"{pkg}.{fn}"
    if key in _LANG_CACHE:
        return _LANG_CACHE[key]
    try:
        from tree_sitter import Language
        lo = getattr(importlib.import_module(pkg), fn)()
        obj = lo if hasattr(lo, "name") else Language(lo)
    except Exception as e:  # noqa: BLE001
        log.warning("tree_sitter grammar %s unavailable: %s", pkg, e); obj = None
    _LANG_CACHE[key] = obj
    return obj


def _ts_parse(source: bytes, language) -> Any | None:
    try:
        from tree_sitter import Parser
        p = Parser(); p.language = language
        return p.parse(source).root_node
    except Exception as e:  # noqa: BLE001
        log.warning("tree_sitter parse failed: %s", e); return None


def _cli_available() -> bool:
    try:
        subprocess.run(["tree-sitter", "--version"], check=True, capture_output=True, timeout=5)
        return True
    except Exception:  # noqa: BLE001
        return False


# ─── parse_file — the only entrypoint the indexer calls ──────────────


def parse_file(file_path: Path, rel_path: str, cfg: ExtractorConfig,
               repo: str, commit_sha: str) -> tuple[list[dict], list[dict]]:
    try:
        source = file_path.read_bytes()
    except OSError as e:
        log.warning("cannot read %s: %s", file_path, e); return [], []
    grammar = _pick_grammar(file_path, cfg)
    lang = _load_language(grammar) if grammar else None
    root = _ts_parse(source, lang) if lang else None
    if root is None:
        if grammar and not _cli_available():
            log.debug("no parser for %s; emitting file-root only", rel_path)
        return _file_root_only(cfg, rel_path, repo, commit_sha), []
    ctx = _Ctx(cfg, rel_path, repo, commit_sha, source, [])
    _emit_file_root(ctx); _walk(root, ctx)
    return ctx.nodes, ctx.edges


def _pick_grammar(file_path: Path, cfg: ExtractorConfig) -> dict | None:
    for g in cfg.grammars:
        exts = g.get("extensions")
        if exts is None or file_path.suffix in exts:
            return g
    return cfg.grammars[0] if cfg.grammars else None


def _file_root_only(cfg: ExtractorConfig, rel_path: str, repo: str, commit_sha: str) -> list[dict]:
    rule = next((r for r in cfg.node_extractors if r.get("ast_type") == "__file_root__"), None)
    if rule is None:
        return []
    name = _synth_name(rule.get("name_field", "__relpath__"), rel_path)
    return [_make_node(cfg, rule, name, rel_path, repo, commit_sha, props={"degraded": "true"})]


# ─── AST walk ────────────────────────────────────────────────────────


@dataclass
class _Ctx:
    cfg: ExtractorConfig
    rel_path: str
    repo: str
    commit_sha: str
    source: bytes
    scope: list[dict]
    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    by_id: dict[str, dict] = field(default_factory=dict)


def _emit_file_root(ctx: _Ctx) -> None:
    rule = next((r for r in ctx.cfg.node_extractors if r.get("ast_type") == "__file_root__"), None)
    if rule is None:
        return
    name = _synth_name(rule.get("name_field", "__relpath__"), ctx.rel_path)
    n = _make_node(ctx.cfg, rule, name, ctx.rel_path, ctx.repo, ctx.commit_sha)
    ctx.nodes.append(n); ctx.by_id[n["node_id"]] = n
    ctx.scope.append({"kind": n["type"], "node": n})


def _walk(node: Any, ctx: _Ctx) -> None:
    ntype = getattr(node, "type", None)
    if not ntype:
        return
    pushed = False
    for rule in ctx.cfg.node_extractors:
        if rule.get("ast_type") == ntype and not _skip(rule, node):
            kg = _emit_node(node, rule, ctx)
            if kg:
                ctx.scope.append({"kind": kg["type"], "node": kg}); pushed = True
            break
    for rule in ctx.cfg.edge_extractors:
        if rule.get("ast_type") == ntype:
            _emit_edge(node, rule, ctx)
    for child in getattr(node, "children", []) or []:
        _walk(child, ctx)
    if pushed:
        ctx.scope.pop()


def _skip(rule: dict, node: Any) -> bool:
    for s in rule.get("skip_if", []) or []:
        if "parent_ast_type" in s:
            parent = getattr(node, "parent", None)
            if parent and getattr(parent, "type", None) == s["parent_ast_type"]:
                return True
    return False


def _emit_node(ast_node: Any, rule: dict, ctx: _Ctx) -> dict | None:
    name = _field_text(ast_node, rule.get("name_field", ""), ctx.source) or "<anonymous>"
    encl = ctx.scope[-1]["node"]["name"] if ctx.scope else ""
    module = ctx.scope[0]["node"]["name"] if ctx.scope else ctx.rel_path
    qname = (rule.get("qualified_name") or "{module}.{name}").format(
        module=module, enclosing_scope=encl, name=name)
    props: dict[str, str] = {}
    for spec in rule.get("properties") or []:
        v = _apply_transform(ast_node, spec, ctx.source)
        if v is not None:
            props[spec["property_key"]] = v
    nid = f"{ctx.cfg.language}:{rule['node_kind'].lower()}:{qname}"
    n = _make_node(ctx.cfg, rule, name, ctx.rel_path, ctx.repo, ctx.commit_sha,
                   node_id=nid, props=props)
    ctx.nodes.append(n); ctx.by_id[nid] = n
    return n


def _emit_edge(ast_node: Any, rule: dict, ctx: _Ctx) -> None:
    src = _resolve_from(rule.get("from_resolver", ""), ctx)
    if src is None:
        return
    for tgt in _resolve_to(rule.get("to_resolver", ""), ast_node, ctx):
        ctx.edges.append({"from_node_id": src["node_id"], "to_node_id": tgt,
                          "type": rule["edge_kind"], "commit_sha": ctx.commit_sha,
                          "properties": {}})


def _resolve_from(strategy: str, ctx: _Ctx) -> dict | None:
    if not ctx.scope:
        return None
    if strategy == "enclosing_module":
        return ctx.scope[0]["node"]
    if strategy == "enclosing_function":
        for f in reversed(ctx.scope):
            if f["kind"] in ("Function", "Method"):
                return f["node"]
        return ctx.scope[0]["node"]
    if strategy == "current_node":
        return ctx.scope[-1]["node"]
    return ctx.scope[0]["node"]


def _resolve_to(strategy: str, ast_node: Any, ctx: _Ctx) -> list[str]:
    """Best-effort. Misses anchor at synthetic ExternalSymbol so edges always
    have a target (see extractors/README.md §resolution)."""
    if strategy.startswith("pattern:"):
        pat = re.compile(strategy.split(":", 1)[1])
        text = _node_text(ast_node, ctx.source) or ""
        return [_external_id(ctx.cfg.language, m.group(1) if m.groups() else m.group(0))
                for m in pat.finditer(text)]
    if ":" in strategy:
        fld = strategy.split(":", 1)[1].split("+")[0].strip()
        name = (_field_text(ast_node, fld, ctx.source)
                or _node_text(ast_node, ctx.source) or "").strip().strip('"\'')
        if not name:
            return []
        for nid, n in ctx.by_id.items():
            if n.get("name") == name:
                return [nid]
        return [_external_id(ctx.cfg.language, name)]
    return []


# ─── helpers ─────────────────────────────────────────────────────────


def _make_node(cfg: ExtractorConfig, rule: dict, name: str, rel_path: str,
               repo: str, commit_sha: str, *, node_id: str | None = None,
               props: dict | None = None) -> dict:
    nid = node_id or f"{cfg.language}:{rule['node_kind'].lower()}:{name}:{rel_path}"
    p = dict(props or {}); p.setdefault("language", cfg.language)
    return {"node_id": nid, "type": rule["node_kind"], "subtype": rule.get("subtype"),
            "repo": repo, "commit_sha": commit_sha, "path": rel_path, "name": name,
            "properties": p}


def _external_id(language: str, symbol: str) -> str:
    return f"{language}:externalsymbol:{symbol}"


def _synth_name(field_name: str, rel_path: str) -> str:
    if field_name == "__relpath_dotted__":
        return rel_path.replace("/", ".").rsplit(".", 1)[0]
    if field_name == "__filename__":
        return Path(rel_path).name
    return rel_path


def _field_text(node: Any, fld: str, source: bytes) -> str | None:
    if not fld or fld.startswith("__"):
        return None
    try:
        c = node.child_by_field_name(fld) if hasattr(node, "child_by_field_name") else None
        return _node_text(c, source) if c else None
    except Exception:  # noqa: BLE001
        return None


def _node_text(node: Any, source: bytes) -> str | None:
    if node is None:
        return None
    s, e = getattr(node, "start_byte", None), getattr(node, "end_byte", None)
    return None if s is None or e is None else source[s:e].decode("utf-8", errors="replace")


def _apply_transform(node: Any, spec: dict, source: bytes) -> str | None:
    fld = spec.get("source_field", ""); tr = spec.get("transform", "stringify")
    if fld == "__self__":
        text = _node_text(node, source)
    elif fld == "__is_async__":
        text = "true" if "async" in (_node_text(node, source) or "") else "false"
    elif fld.startswith("__"):
        return None
    else:
        text = _field_text(node, fld, source)
    if text is None:
        return None
    if tr == "hash":
        return hashlib.sha256(text.encode()).hexdigest()[:16]
    if tr == "first_line":
        return text.splitlines()[0] if text else ""
    if tr == "line_range":
        s = getattr(node, "start_point", (0, 0))[0]; e = getattr(node, "end_point", (0, 0))[0]
        return f"{s + 1}-{e + 1}"
    return text
