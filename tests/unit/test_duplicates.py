"""Content-based duplicate detection.

The feature is opt-in, so the first two tests pin the default behaviour: with
the setting off nothing changes and no file is ever read twice.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from smartsort.app.core.organizer import Organizer
from smartsort.app.storage.models import OrganizeRequest
from smartsort.app.storage.repositories import Repositories
from tests.conftest import make_file


def request(path: Path, **kwargs) -> OrganizeRequest:
    kwargs.setdefault("origin", "browser")
    return OrganizeRequest(source_path=str(path), **kwargs)


def test_identical_files_both_move_when_disabled(
    organizer: Organizer, configured, downloads_dir: Path
) -> None:
    first = make_file(downloads_dir, "report.pdf", b"same-bytes")
    second = make_file(downloads_dir, "report-copy.pdf", b"same-bytes")

    assert organizer.organize(request(first)).status == "organized"
    assert organizer.organize(request(second)).status == "organized"
    assert not second.exists()


def test_no_hash_is_computed_when_disabled(
    organizer: Organizer, configured, repos: Repositories, downloads_dir: Path
) -> None:
    source = make_file(downloads_dir, "report.pdf", b"same-bytes")
    result = organizer.organize(request(source))

    operation = repos.operations.get(result.operation_id)
    assert operation is not None
    assert operation.content_hash is None


def test_identical_content_is_skipped_when_enabled(
    organizer: Organizer,
    configured,
    repos: Repositories,
    downloads_dir: Path,
    destination: Path,
) -> None:
    configured.set("skip_duplicate_content", True)
    first = make_file(downloads_dir, "report.pdf", b"same-bytes")
    second = make_file(downloads_dir, "report-copy.pdf", b"same-bytes")

    assert organizer.organize(request(first)).status == "organized"
    result = organizer.organize(request(second))

    assert result.status == "content_duplicate"
    assert result.message == "content_already_exists"
    # The point of the feature: the second copy is left where it is.
    assert second.exists()
    assert not (destination / "2026-10-21" / "Documents" / "report-copy.pdf").exists()


def test_the_duplicate_row_records_the_other_copy(
    organizer: Organizer,
    configured,
    repos: Repositories,
    downloads_dir: Path,
) -> None:
    configured.set("skip_duplicate_content", True)
    first = make_file(downloads_dir, "report.pdf", b"same-bytes")
    second = make_file(downloads_dir, "report-copy.pdf", b"same-bytes")

    organizer.organize(request(first))
    result = organizer.organize(request(second))

    operation = repos.operations.get(result.operation_id)
    assert operation is not None
    assert operation.status == "content_duplicate"
    assert operation.content_hash == hashlib.sha256(b"same-bytes").hexdigest()
    assert operation.duplicate_of is not None
    assert operation.duplicate_of.endswith("report.pdf")


def test_different_content_still_moves(
    organizer: Organizer, configured, downloads_dir: Path
) -> None:
    configured.set("skip_duplicate_content", True)
    first = make_file(downloads_dir, "report.pdf", b"first-bytes")
    second = make_file(downloads_dir, "other.pdf", b"second-bytes")

    assert organizer.organize(request(first)).status == "organized"
    assert organizer.organize(request(second)).status == "organized"
    assert not second.exists()


def test_a_deleted_original_does_not_block_the_new_copy(
    organizer: Organizer, configured, downloads_dir: Path
) -> None:
    """The history row outlives the file; only a file that exists counts."""
    configured.set("skip_duplicate_content", True)
    first = make_file(downloads_dir, "report.pdf", b"same-bytes")
    second = make_file(downloads_dir, "report-copy.pdf", b"same-bytes")

    result = organizer.organize(request(first))
    Path(result.final_path).unlink()

    assert organizer.organize(request(second)).status == "organized"
    assert not second.exists()


def test_a_skipped_duplicate_is_not_reprocessed_forever(
    organizer: Organizer, configured, downloads_dir: Path
) -> None:
    """The watcher polls every two seconds; a skip must not write a row each time."""
    configured.set("skip_duplicate_content", True)
    first = make_file(downloads_dir, "report.pdf", b"same-bytes")
    second = make_file(downloads_dir, "report-copy.pdf", b"same-bytes")

    organizer.organize(request(first))
    assert organizer.organize(request(second)).status == "content_duplicate"

    again = organizer.organize(request(second))
    assert again.status == "duplicate"
    assert again.message == "already_processed"


def test_an_undone_copy_is_not_treated_as_present(
    organizer: Organizer, configured, repos: Repositories, downloads_dir: Path
) -> None:
    """Undo moves the file back, so the destination no longer holds the content."""
    configured.set("skip_duplicate_content", True)
    first = make_file(downloads_dir, "report.pdf", b"same-bytes")
    second = make_file(downloads_dir, "report-copy.pdf", b"same-bytes")

    result = organizer.organize(request(first))
    assert result.operation_id is not None
    repos.operations.mark_undone(result.operation_id, "restored")
    # The file is deliberately left on disk: the row alone must stop counting.

    assert organizer.organize(request(second)).status == "organized"
