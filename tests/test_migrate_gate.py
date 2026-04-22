"""TRON_AUTO_MIGRATE gate for startup migrations."""

from __future__ import annotations

import os
import pytest

from tron.infra.db import migrate as migrate_mod


def test_run_sync_migrations_skipped_when_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("TRON_AUTO_MIGRATE", "false")
    monkeypatch.setattr(migrate_mod, "_alembic_ini_path", lambda: tmp_path / "missing.ini")

    called: list[str] = []

    def fake_upgrade(_cfg, _rev):  # noqa: ANN001
        called.append("upgrade")

    monkeypatch.setattr(migrate_mod.command, "upgrade", fake_upgrade)
    migrate_mod.run_sync_migrations("postgresql://u:p@localhost:5432/tron")
    assert called == []


def test_run_sync_migrations_no_ini_skips_upgrade(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("TRON_AUTO_MIGRATE", "true")
    monkeypatch.setattr(migrate_mod, "_alembic_ini_path", lambda: tmp_path / "nope.ini")

    called: list[str] = []

    def fake_upgrade(_cfg, _rev):  # noqa: ANN001
        called.append("upgrade")

    monkeypatch.setattr(migrate_mod.command, "upgrade", fake_upgrade)
    migrate_mod.run_sync_migrations("postgresql://u:p@localhost:5432/tron")
    assert called == []


def test_run_sync_migrations_sets_database_url_for_upgrade(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    ini = tmp_path / "alembic.ini"
    ini.write_text("[alembic]\nscript_location = alembic\n", encoding="utf-8")
    monkeypatch.setenv("TRON_AUTO_MIGRATE", "on")
    monkeypatch.setattr(migrate_mod, "_alembic_ini_path", lambda: ini)

    captured: dict[str, str | None] = {}

    def fake_upgrade(_cfg, _rev):  # noqa: ANN001
        captured["db_url"] = os.environ.get("DATABASE_URL")

    monkeypatch.setattr(migrate_mod.command, "upgrade", fake_upgrade)
    url = "postgresql://tron:secret@db:5432/tron"
    migrate_mod.run_sync_migrations(url)
    assert captured["db_url"] == url
    assert "DATABASE_URL" not in os.environ
