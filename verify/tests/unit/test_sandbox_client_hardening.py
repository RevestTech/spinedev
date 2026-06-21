"""
Regression tests for the sandbox container hardening.

Every kwarg documented in docs/security/SANDBOX_THREAT_MODEL.md must actually
reach ``docker.containers.run``, for both ``run_python`` and ``run_bash``.
If a flag goes missing here, the threat-model doc has lied to somebody.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tron.services.sandbox_client import (
    _ALLOWED_NETWORK_MODES,
    SandboxClient,
    _hardened_run_kwargs,
    _validate_network_mode,
)


# ── Pure-function tests: the hardening helper ─────────────────────────────


class TestHardenedRunKwargs:
    def _kwargs(self, **overrides):
        defaults = dict(
            memory_limit="128m",
            cpu_quota=50_000,
            network_mode="none",
            workdir=None,
            volumes=None,
        )
        defaults.update(overrides)
        return _hardened_run_kwargs(**defaults)

    def test_rootfs_is_read_only(self):
        assert self._kwargs()["read_only"] is True

    def test_tmpfs_is_capped_at_10MiB(self):
        # size=10M must be part of the tmpfs spec — disk-fill guard.
        tmpfs = self._kwargs()["tmpfs"]
        assert "/tmp" in tmpfs
        assert "size=10M" in tmpfs["/tmp"]

    def test_runs_as_non_root(self):
        # 65534:65534 = nobody:nogroup on Debian/Ubuntu.
        assert self._kwargs()["user"] == "65534:65534"

    def test_all_capabilities_dropped(self):
        assert self._kwargs()["cap_drop"] == ["ALL"]

    def test_no_new_privileges(self):
        assert "no-new-privileges:true" in self._kwargs()["security_opt"]

    def test_seccomp_profile_clause_present_when_file_exists(self, tmp_path, monkeypatch):
        # When the configured seccomp profile exists, the security_opt list
        # must include the seccomp= clause so Docker applies the custom
        # filter (stricter than its default).
        from tron.services import sandbox_client as sc

        profile = tmp_path / "seccomp.json"
        profile.write_text('{"defaultAction": "SCMP_ACT_ALLOW"}')
        monkeypatch.setattr(sc, "_SECCOMP_PROFILE_PATH", str(profile))

        opts = self._kwargs()["security_opt"]
        assert any(o.startswith("seccomp=") and str(profile) in o for o in opts)
        # And the no-new-privileges clause is still there.
        assert "no-new-privileges:true" in opts

    def test_seccomp_disabled_via_env_falls_back_to_docker_default(self, monkeypatch):
        # ``TRON_SANDBOX_SECCOMP=disabled`` is the documented escape hatch
        # for debugging — the security_opt list MUST NOT include a
        # seccomp= clause in that mode (Docker then uses its default).
        from tron.services import sandbox_client as sc
        monkeypatch.setattr(sc, "_SECCOMP_PROFILE_PATH", "disabled")

        opts = self._kwargs()["security_opt"]
        assert not any(o.startswith("seccomp=") for o in opts)
        assert "no-new-privileges:true" in opts

    def test_seccomp_missing_file_warns_and_falls_back(self, monkeypatch, caplog):
        import logging as _logging
        from tron.services import sandbox_client as sc
        monkeypatch.setattr(
            sc, "_SECCOMP_PROFILE_PATH", "/definitely/not/here.json"
        )

        with caplog.at_level(_logging.WARNING, logger="tron.services.sandbox_client"):
            opts = self._kwargs()["security_opt"]

        assert not any(o.startswith("seccomp=") for o in opts)
        assert any(
            "seccomp profile not found" in r.message for r in caplog.records
        )

    def test_network_disabled_when_mode_is_none(self):
        k = self._kwargs(network_mode="none")
        assert k["network_mode"] == "none"
        assert k["network_disabled"] is True

    def test_network_enabled_when_mode_is_bridge(self):
        k = self._kwargs(network_mode="bridge")
        assert k["network_mode"] == "bridge"
        # bridge mode deliberately leaves network_disabled False so the
        # allowlist HTTPS audit path can reach out.
        assert k["network_disabled"] is False

    def test_pids_limit_blocks_fork_bombs(self):
        assert self._kwargs()["pids_limit"] == 64

    def test_memswap_matches_memlimit(self):
        # memswap==mem means effectively no swap; memory-bomb worst-case
        # cannot exceed the RAM cap.
        k = self._kwargs(memory_limit="256m")
        assert k["mem_limit"] == "256m"
        assert k["memswap_limit"] == "256m"

    def test_hostname_is_fixed(self):
        # Don't leak the host's hostname into payload logs.
        assert self._kwargs()["hostname"] == "tron-sandbox"

    def test_ipc_is_private(self):
        assert self._kwargs()["ipc_mode"] == "private"

    def test_environment_forces_bytecode_off_and_home_in_tmpfs(self):
        env = self._kwargs()["environment"]
        assert env["PYTHONDONTWRITEBYTECODE"] == "1"
        # HOME in tmpfs: read-only rootfs means ~/.cache writes must land
        # in the writable tmpfs or they fail.
        assert env["HOME"] == "/tmp"

    def test_ulimits_include_fsize_and_nofile(self):
        names = set()
        for u in self._kwargs()["ulimits"]:
            # docker.types.Ulimit has a .name attr; dict fallback has a key.
            names.add(getattr(u, "name", None) or u["name"])
        assert "fsize" in names
        assert "nofile" in names

    def test_remove_is_true(self):
        # Auto-GC on exit — orphan containers would leak payload state.
        assert self._kwargs()["remove"] is True

    def test_workdir_and_volumes_pass_through(self):
        k = self._kwargs(workdir="/work", volumes={"/src": {"bind": "/src", "mode": "ro"}})
        assert k["working_dir"] == "/work"
        assert k["volumes"] == {"/src": {"bind": "/src", "mode": "ro"}}


# ── Network-mode allowlist ─────────────────────────────────────────────────


class TestNetworkModeAllowlist:
    def test_none_and_bridge_accepted(self):
        assert _validate_network_mode("none") == "none"
        assert _validate_network_mode("bridge") == "bridge"

    def test_host_is_rejected(self):
        # host mode shares the service's netns — no isolation.
        with pytest.raises(ValueError, match="allowlist"):
            _validate_network_mode("host")

    def test_container_mode_is_rejected(self):
        # container:<id> shares another container's netns (lateral move).
        with pytest.raises(ValueError, match="allowlist"):
            _validate_network_mode("container:abc")

    def test_made_up_modes_are_rejected(self):
        for bad in ("", "private", "overlay", "something_custom"):
            with pytest.raises(ValueError):
                _validate_network_mode(bad)

    def test_allowlist_is_narrow_by_design(self):
        # Canary: if someone adds a new mode to the allowlist, a reviewer
        # reading the threat model needs to know about it.
        assert _ALLOWED_NETWORK_MODES == frozenset({"none", "bridge"})


# ── End-to-end: the hardening flags reach containers.run for both paths ────


@pytest.fixture
def mock_docker_client():
    """A docker.DockerClient-shaped mock that records ``containers.run`` kwargs."""
    client = MagicMock()

    # Make container.wait and logs behave like a normal exit.
    container = MagicMock()
    container.wait.return_value = {"StatusCode": 0}
    container.logs.return_value = b"hello"
    client.containers.run.return_value = container
    return client


def _hardening_assertions(captured: dict, *, network_mode: str) -> None:
    """Shared assertion bundle for run_python / run_bash callsite parity."""
    assert captured["user"] == "65534:65534"
    assert captured["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in captured["security_opt"]
    assert captured["read_only"] is True
    assert captured["pids_limit"] == 64
    assert captured["ipc_mode"] == "private"
    assert captured["hostname"] == "tron-sandbox"
    assert captured["remove"] is True
    assert captured["tmpfs"]["/tmp"].startswith("size=10M")
    assert captured["environment"]["PYTHONDONTWRITEBYTECODE"] == "1"
    assert captured["network_mode"] == network_mode
    assert captured["network_disabled"] is (network_mode == "none")


@pytest.mark.asyncio
async def test_run_python_applies_all_hardening(mock_docker_client):
    sbx = SandboxClient(docker_client=mock_docker_client)
    await sbx.run_python("print('hi')")

    mock_docker_client.containers.run.assert_called_once()
    _, kwargs = mock_docker_client.containers.run.call_args
    _hardening_assertions(kwargs, network_mode="none")


@pytest.mark.asyncio
async def test_run_bash_applies_all_hardening(mock_docker_client):
    sbx = SandboxClient(docker_client=mock_docker_client)
    await sbx.run_bash("echo hi")

    mock_docker_client.containers.run.assert_called_once()
    _, kwargs = mock_docker_client.containers.run.call_args
    _hardening_assertions(kwargs, network_mode="none")


@pytest.mark.asyncio
async def test_run_python_rejects_host_network(mock_docker_client):
    sbx = SandboxClient(docker_client=mock_docker_client)
    with pytest.raises(ValueError, match="allowlist"):
        await sbx.run_python("print('x')", network_mode="host")
    mock_docker_client.containers.run.assert_not_called()


@pytest.mark.asyncio
async def test_run_bash_rejects_container_mode(mock_docker_client):
    sbx = SandboxClient(docker_client=mock_docker_client)
    with pytest.raises(ValueError, match="allowlist"):
        await sbx.run_bash("echo x", network_mode="container:abc")
    mock_docker_client.containers.run.assert_not_called()
