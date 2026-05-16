# `build/kg/doc_parser/` — Spine KG document parser

Implements `STORY-6.3.1` (markdown parser), `STORY-6.3.2` (REQ/PRD/TRD/
Roadmap parsers), `STORY-6.3.3` (role-prompt + `memory.md` parser) in
`docs/BACKLOG.md`, satisfying REQ-INIT-6 FR-4.

Parallel to `build/kg/indexer/parser_runtime.py` (code AST → KG). This
module walks markdown documents and emits the doc half of the graph:
`Document`, `Heading`, `Requirement`, `AcceptanceCriterion`,
`Initiative`/`Epic`/`Story`, `Role`, `Constraint`, `MemoryLesson`,
`Release` nodes plus `LINKS_TO` / `CITES` / `SUPERSEDES` /
`DECIDED_BY` / `PART_OF` / `DERIVED_FROM` / `OWNED_BY` / `TOUCHES`
edges into `spine_kg.kg_node` and `spine_kg.kg_edge` (V2 schema).

## Why doc parsing

FR-4 makes the doc layer a first-class graph citizen: heading nodes let
queries jump to the right section in O(1); inline links become
`LINKS_TO` edges so the graph models cross-doc navigation; and every
embedded Spine ID (`INIT-N`, `EPIC-N.M`, `STORY-N.M.K`, `REQ-INIT-N`,
`ADR-N`, `FR-N`, `FR-N.M`) becomes a typed `CITES` edge against the
target Spine-flow node. End result: "show every doc that cites
STORY-6.3.1" is a single index lookup.

## Per-doc-type parsers

| Doc type | Parser | Extras beyond markdown |
|---|---|---|
| Generic `.md` | `parse_markdown` | Heading + LINKS_TO + CITES |
| `REQ-*.md` / `docs/PRD.md` | `parse_req` / `parse_prd` | `Requirement` (FR/NFR) + `AcceptanceCriterion` |
| `TRD-*.md` | `parse_trd` | `Requirement` (NFR + FR) |
| `BACKLOG.md` / `*roadmap.md` | `parse_roadmap` | `Initiative` → `Epic` → `Story` with PART_OF |
| `ADR-*.md`, `docs/decisions/*` | `parse_adr` | `SUPERSEDES` edges |
| `CHANGELOG.md` | `parse_changelog` | `Release` nodes per version |
| `lib/role-prompts/*.md` | `parse_role_prompt` | `Role` + `Constraint` nodes |
| `teams/<role>/memory.md` | `parse_memory_md` | `MemoryLesson` (scope=`project`) + TOUCHES |
| `playbook/<role>/lessons.md` | `parse_playbook` | `MemoryLesson` (scope=`cross_project`) |

Path-based dispatch lives in `spine_doc_parser.parser_for_path`. To add
a new doc type: write `parse_<type>` here, return a `ParsedDoc`, and
extend `parser_for_path` with a heuristic.

## Spine-ID extraction

`spine_id_resolver` owns the regex + KG lookup. Patterns (ordered for
longest-prefix-wins):

| Kind | Regex | Target type |
|---|---|---|
| `req_init` | `REQ-INIT-N` | `Document` (subtype REQ) |
| `story` | `STORY-N.M.K` | `Story` |
| `epic` | `EPIC-N.M` | `Epic` |
| `init` | `INIT-N` | `Initiative` |
| `adr` | `ADR-N` | `Document` (subtype ADR) |
| `epic_fr` | `FR-N.M` | `Requirement` |
| `fr` | `FR-N` | `Requirement` |

`extract_references` returns unresolved hits (line + kind + target type).
`resolve_references` then runs one batched `psql` `SELECT name, node_id
FROM spine_kg.kg_node WHERE name IN (…) AND valid_to IS NULL` to map
each ID to a real node. Unresolved refs flow through
`external_node_id` so the edge is still insertable and gets repointed
when the real target is later indexed.

## Integration with the indexer

Today: the indexer's `parser_runtime.parse_file` handles every file via
tree-sitter (markdown extractor at `build/kg/extractors/markdown.yaml`).
The follow-up integration story routes `.md` files to this module
instead — the output shapes (`NodeData` / `EdgeData`) already mirror
`parser_runtime`'s `dict` payloads so the indexer's psql INSERT path is
unchanged.

Until then, `cli.py` provides standalone access:

    python -m build.kg.doc_parser.cli parse docs/PRD.md
    python -m build.kg.doc_parser.cli reindex --root docs/ --dry-run
    python -m build.kg.doc_parser.cli validate lib/role-prompts/architect.md
    python -m build.kg.doc_parser.cli references docs/BACKLOG.md --resolve

Exit codes match the indexer CLI (0 success, 1 errors during work, 2
config / fatal).

## How to add a new doc type

1. Write `parse_<type>(content, doc_path, **kw) -> ParsedDoc` in
   `spine_doc_parser.py` (call `parse_markdown` for the heading / link
   / cite base, then overlay your subtype-specific child nodes/edges).
2. Add a path heuristic to `parser_for_path`.
3. Register the type slug in `cli._PARSERS` so `--type <slug>` works.
4. No DB migration needed — `spine_kg.kg_node.type` is an open string.

## Cross-references

- `STORY-6.3.1` / `6.3.2` / `6.3.3` — this implementation.
- `db/flyway/sql/V2__spine_kg_schema.sql` — node / edge schema.
- `build/kg/indexer/parser_runtime.py` — parallel structure for code.
- `build/kg/extractors/markdown.yaml` — the tree-sitter extractor this
  replaces for `.md` files (kept for documentation; indexer routing
  switch is a follow-up).
- `docs/PRD.md` REQ-INIT-6 §6.5 FR-4 — the spec.
