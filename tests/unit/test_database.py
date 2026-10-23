"""Persistence, migrations and transactions."""

from __future__ import annotations

from pathlib import Path

import pytest

from smartsort.app.config.defaults import SCHEMA_VERSION
from smartsort.app.storage.database import Database
from smartsort.app.storage.repositories import Repositories, utc_now_iso


def test_schema_version_is_current(db: Database) -> None:
    assert db.scalar("PRAGMA user_version") == SCHEMA_VERSION


def test_migrations_are_idempotent(db: Database) -> None:
    from smartsort.app.storage import migrations

    before = migrations.current_version(db.connection)
    assert migrations.apply(db.connection) == before


def test_categories_are_seeded(repos: Repositories) -> None:
    categories = repos.categories.list_all()
    ids = [category.id for category in categories]
    assert ids == ["images", "videos", "documents", "audio", "archives", "installers", "other"]
    images = repos.categories.get("images")
    assert images is not None
    assert "jpg" in images.extensions
    assert images.enabled is True


def test_default_settings_are_seeded(settings) -> None:
    assert settings.auto_organize is True
    assert settings.use_date_folders is True
    assert settings.destination_dir == ""
    assert settings.language == "en"


def test_settings_roundtrip(settings) -> None:
    settings.set("destination_dir", "E:\\SmartSort")
    settings.set("auto_organize", False)
    assert settings.destination_dir == "E:\\SmartSort"
    assert settings.auto_organize is False


def test_settings_are_persisted_across_reopen(data_dir: Path, settings) -> None:
    settings.set("destination_dir", "D:\\Target")
    settings.set_many({"watch_enabled": True, "watch_settle_seconds": 5.0})

    database = Database(data_dir / "test.db").open()
    try:
        reopened = Repositories(database)
        assert reopened.settings.get("destination_dir") == "D:\\Target"
        assert reopened.settings.get("watch_enabled") is True
        assert reopened.settings.get("watch_settle_seconds") == 5.0
    finally:
        database.close()


def test_operations_survive_restart(data_dir: Path, repos: Repositories) -> None:
    operation_id = repos.operations.add(
        origin="browser",
        category="images",
        original_path="C:\\Downloads\\a.jpg",
        final_path="E:\\SmartSort\\2026-10-21\\Images\\a.jpg",
        status="organized",
        size_bytes=42,
    )

    database = Database(data_dir / "test.db").open()
    try:
        reopened = Repositories(database)
        operation = reopened.operations.get(operation_id)
        assert operation is not None
        assert operation.final_path.endswith("a.jpg")
        assert operation.status == "organized"
        assert reopened.operations.count() == 1
    finally:
        database.close()


def test_transaction_rolls_back(db: Database, repos: Repositories) -> None:
    with pytest.raises(RuntimeError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO operations (origin, category, original_path, final_path,"
                " organized_at, status) VALUES ('test','other','a','b',?, 'organized')",
                (utc_now_iso(),),
            )
            raise RuntimeError("boom")
    assert repos.operations.count() == 0


def test_processed_items_are_deduplicated(repos: Repositories) -> None:
    repos.processed.add("dl:chrome:1", kind="download", download_id="1", browser="chrome")
    repos.processed.add("dl:chrome:1", kind="download", download_id="1", browser="chrome")
    assert repos.processed.exists("dl:chrome:1") is True
    assert repos.processed.count() == 1


def test_processed_items_prune(repos: Repositories) -> None:
    repos.processed.add("old", kind="path")
    removed = repos.processed.prune(older_than_days=0)
    assert removed == 0
    assert repos.processed.exists("old")


def test_backup_creates_a_usable_copy(db: Database, tmp_path: Path, repos: Repositories) -> None:
    repos.operations.add(
        origin="manual",
        category="other",
        original_path="a",
        final_path="b",
        status="organized",
    )
    target = tmp_path / "backup.db"
    db.backup_to(target)
    assert target.exists()

    copy = Database(target).open()
    try:
        assert Repositories(copy).operations.count() == 1
    finally:
        copy.close()


def test_integrity_check(db: Database) -> None:
    assert db.integrity_check() == "ok"


def test_stats_counts_today(repos: Repositories) -> None:
    repos.operations.add(
        origin="browser",
        category="images",
        original_path="a",
        final_path="b",
        status="organized",
        size_bytes=100,
    )
    repos.operations.add(
        origin="browser",
        category="images",
        original_path="c",
        final_path="",
        status="failed",
    )
    stats = repos.operations.stats()
    assert stats["organized_total"] == 1
    assert stats["organized_today"] == 1
    assert stats["failed_total"] == 1
    assert stats["bytes_today"] == 100


def test_search_filters(repos: Repositories) -> None:
    repos.operations.add(
        origin="browser",
        category="videos",
        original_path="C:\\Downloads\\movie.mp4",
        final_path="E:\\v.mp4",
        status="organized",
    )
    repos.operations.add(
        origin="browser",
        category="images",
        original_path="C:\\Downloads\\photo.png",
        final_path="",
        status="failed",
    )
    assert len(repos.operations.search(text="movie")) == 1
    assert len(repos.operations.search(status="failed")) == 1
    assert len(repos.operations.search(category="videos")) == 1
    assert len(repos.operations.search()) == 2
