# `build/kg/extractors/` — per-language AST → graph config

Implements `STORY-6.2.2` (schema) and `STORY-6.2.3` (v1 default configs). Each
YAML here declares how a single language's tree-sitter AST projects into Spine
KG nodes and edges. The parser runtime (`build/kg/parsers/`, built in
`STORY-6.2.1`) is language-agnostic — these configs are its entire language
model.

## Why declarative config

REQ-INIT-6 FR-3: "new languages added by dropping a grammar + extractor config
— no Spine source change". An org bundle ships `kotlin.yaml`, installs
`tree-sitter-kotlin`, and Kotlin is in the graph — no plugin entrypoint, no
recompile. Replaces TRON's hand-written parsers under `verify/tron/parsers/`
(migration: `STORY-8.2.4`), each of which required a new Python file + tests
+ indexer wiring per language.

## How the runtime consumes these configs

```
for file in changed_files:
    cfg = pick_extractor(file.path, EXTRACTORS)        # by file_filters globs
    if cfg.test_file_detection.matches(file.path):
        promote_module_to_test_file()
    tree = tree_sitter.parse(file.bytes, cfg.grammar)
    for ast_node in walk(tree.root, follow=cfg.children_recurse):
        for r in cfg.node_extractors:
            if r.matches(ast_node) and not r.skip_if.matches(ast_node):
                emit_kg_node(r, ast_node, scope_stack)
        for r in cfg.edge_extractors:
            if r.matches(ast_node):
                emit_kg_edge(r, ast_node, scope_stack)
    flush_to_outbox()                                  # → V2 SQL inserts
```

Rows land in `spine_kg.kg_node` / `spine_kg.kg_edge`
(`db/flyway/sql/V2__spine_kg_schema.sql`). The indexer handles `node_id`
stability, `valid_from`/`valid_to` snapshots, and embedding.

## Adding a new language — 5-step recipe

1. **Install the grammar.** Add `tree_sitter_<lang>` to the indexer venv, pin
   a version. Missing grammar → indexer warns and skips files; never crashes.
2. **Write `<lang>.yaml`.** Start from `_schema.yaml`; copy the nearest existing
   config (Python OO, Bash procedural, Markdown docs) and adapt `ast_type` names
   from the grammar's `node-types.json`.
3. **Drop it here.** Indexer enumerates this directory at startup — no central
   registry to edit.
4. **Cold-index.** `spine-kg cold-index --lang <lang>` parses the whole repo
   with only the new extractor so failures surface fast.
5. **Verify.** `select count(*) from spine_kg.kg_node where properties->>'language' = '<lang>'`
   and spot-check edges. Compare to manual `grep` for coverage sanity.

## The hard part — `from_resolver` / `to_resolver`

Most edges are trivial. `CALLS` and `REFERENCES` are not: the `to` side is a
symbol that needs scope-chain resolution. Strategies:

- `enclosing_function` / `enclosing_module` — walk the scope stack to find the
  nearest matching kg_node. Standard for `from_resolver`.
- `current_node` — the AST node was itself emitted as a kg_node; reuse its id.
  Used for `DEFINES`, `CONTAINS`, `EXTENDS`.
- `symbol_lookup:<field>` — read a name from a named AST field; resolve in (a)
  current scope chain, (b) imported symbols, (c) module-qualified names across
  the repo. Misses anchor at synthetic `ExternalSymbol` nodes so the edge
  always has a target.
- `import_target:<field>` — language-specific import path resolution (Python
  dotted, JS/TS specifiers, Bash file paths).
- `literal_text:<field>` — raw source text. Markdown URLs, Bash command names.
- `pattern:<regex>` — scan a text node, one edge per match. Markdown's
  Spine-ID cite scan uses this — recommended for embedded references.

Resolution is **best-effort static**. Dynamic dispatch (Python `getattr`, JS
`obj[name]()`, Bash variable-named commands) cannot be resolved at parse time;
the call site still emits as an unresolved CALLS edge so queries surface it.

## Test-file detection → `TESTS` / `COVERS` edges

`test_file_detection` is read by the parser core but consumed by `STORY-6.2.4`.
On match, kind is upgraded (`File`→`TestFile`, `Function`→`TestCase`) and the
indexer's test-mapping pass emits `TESTS` / `COVERS` edges by overlapping
`impact_radius` with the test's call graph.

## V1 language set

| File | Status | Covers |
|---|---|---|
| `python.yaml` | Primary | Daemons, indexer, MCP tools |
| `typescript.yaml` | Primary | Dashboard, future UI (TS + JS) |
| `bash.yaml` | Primary | All `lib/*.sh` daemons + tests |
| `markdown.yaml` | Primary | PRD, BACKLOG, ADRs, role prompts, memory |
| `go.yaml` / `rust.yaml` / `sql.yaml` | Backlog | `STORY-6.2.3` follow-on |

## Cross-references

- REQ-INIT-6 §6.5 FR-1 (catalog), FR-3 (tree-sitter), FR-4 (doc parser).
- `db/flyway/sql/V2__spine_kg_schema.sql` + `.README.md` — destination tables.
- `verify/tron/parsers/` — legacy parsers, migrated by `STORY-8.2.4`.
- `docs/BACKLOG.md` — `EPIC-6.2`, `STORY-6.2.1`, `STORY-6.2.4`.
