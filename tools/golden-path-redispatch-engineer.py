#!/usr/bin/env python3
"""Re-run engineer PRODUCE_CODE and enqueue code_approval for a stuck project."""

from __future__ import annotations

import asyncio
import os
import sys

REPO_ROOT = os.environ.get(
    "SPINE_REPO_ROOT",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)


async def main() -> None:
    project_uuid = os.environ.get("PROJECT_UUID", "").strip()
    if not project_uuid:
        print("usage: PROJECT_UUID=<uuid> python3 tools/golden-path-redispatch-engineer.py", file=sys.stderr)
        sys.exit(64)

    from shared.api.app import create_app
    from shared.api.routes._post_ack import _load_project_full, _orchestrate_hub_role

    app = create_app()
    async with app.router.lifespan_context(app):
        project = await _load_project_full(project_uuid)
        if not project:
            print(f"project not found: {project_uuid}", file=sys.stderr)
            sys.exit(1)

        print(f"[redispatch-engineer] project={project_uuid} phase={project.get('current_phase')}")
        handled = await _orchestrate_hub_role(
            kind="sprint_plan_approval",
            project=project,
            actor="founder",
            approval_card_kind="code_approval",
        )
        if not handled:
            print("[redispatch-engineer] orchestrator did not handle dispatch", file=sys.stderr)
            sys.exit(2)
        print("[redispatch-engineer] done — check decision queue for code_approval")


if __name__ == "__main__":
    asyncio.run(main())
