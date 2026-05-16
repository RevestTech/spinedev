"""Spine reproducible builds (EPIC-3.2 / STORY-3.2.1, 3.2.2, 3.2.3).

Run manifest capture + replay + diff. A Spine directive run should be
recreatable from `directive + REQ + role-version + model-version`, the
same way `docker build` is recreatable from a Dockerfile + base image.

Public surface:
    RunManifest, capture_manifest, save_manifest, load_manifest   (manifest)
    ReplayResult, replay                                          (replay)
    ManifestDiff, OutputDiff, diff_manifests, diff_outputs        (diff)
"""
from shared.reproducibility.manifest import (RunManifest, capture_manifest,
                                             load_manifest, save_manifest)
from shared.reproducibility.replay import ReplayResult, replay
from shared.reproducibility.diff import (ManifestDiff, OutputDiff,
                                         diff_manifests, diff_outputs)

__all__ = ["RunManifest", "capture_manifest", "save_manifest", "load_manifest",
           "ReplayResult", "replay", "ManifestDiff", "OutputDiff",
           "diff_manifests", "diff_outputs"]
