# `build/bridge/` — v1 markdown report parser (bridge shell retired)

> **Status:** v1 dispatcher/collector shell scripts removed (2026-05-23). Hub v3
> uses `build/runtime/hub_role_runner.py` for role execution. This package
> keeps `report_parser.py` for parsing legacy markdown reports into
> `BuildArtifact`-shaped dicts (imports, migration tooling).

## What remains

| File | Role |
| --- | --- |
| `__init__.py` | Package marker |
| `report_parser.py` | Markdown report → typed artifact dict (used by `enrich_artifact.py`) |
| `bridge_README.md` | This file |

## Removed (v1 file-bus bridge)

`v1_dispatcher.sh` and `v1_report_collector.sh` bridged the v2 orchestrator to
v1 bash daemons under `.planning/orchestration/`. Wave 6 retired those
daemons; Hub dogfood runs roles in-container via `hub_role_runner`.

See `docs/_archived/v1-PROTOCOL.md` for the historical file-bus contract.
