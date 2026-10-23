"""Render every screen to a PNG (documentation and visual review helper).

    .venv\\Scripts\\python.exe scripts\\capture_screens.py [output-dir]

Runs the real window offscreen with seeded demo data, so the images match what
a user sees without touching the real application database.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Offscreen keeps the script usable in a headless CI run, but it has no font
# database, so text renders as boxes. For documentation screenshots run it with
# QT_QPA_PLATFORM=windows to get real font rendering.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from smartsort.app.bootstrap import create_context  # noqa: E402
from smartsort.app.config import paths  # noqa: E402
from smartsort.app.i18n import set_language  # noqa: E402


def seed(context, destination: Path) -> None:
    context.settings.destination_dir = str(destination)
    repository = context.repos.operations
    now = datetime.now(timezone.utc)
    samples = [
        ("holiday-photo.jpg", "images", "Downloads\\holiday-photo.jpg", "organized", 2),
        ("invoice-2026.pdf", "documents", "Downloads\\invoice-2026.pdf", "organized", 9),
        ("podcast-ep12.mp3", "audio", "Downloads\\podcast-ep12.mp3", "organized", 26),
        ("project-assets.zip", "archives", "Downloads\\project-assets.zip", "organized", 51),
        ("setup-x64.exe", "installers", "Downloads\\setup-x64.exe", "organized", 74),
        ("screen-recording.mp4", "videos", "Downloads\\screen-recording.mp4", "organized", 96),
        ("notes.unknownext", "other", "Downloads\\notes.unknownext", "skipped", 120),
        ("locked-installer.msi", "installers", "Downloads\\locked-installer.msi", "failed", 140),
    ]
    for name, category, source, status, minutes in samples:
        repository.add(
            origin="browser",
            category=category,
            original_path=f"C:\\Users\\user\\{source}",
            final_path=str(destination / "2026-10-21" / category.title() / name)
            if status == "organized"
            else "",
            status=status,
            size_bytes=1_240_000 if status == "organized" else 0,
            download_id=f"demo-{minutes}",
            error="permission_denied: access denied" if status == "failed" else None,
            message="file_still_downloading" if status == "skipped" else "moved_by_rename",
        )
    # Spread the timestamps out so the history looks like a real session instead
    # of every row sharing one instant.
    with context.db.transaction() as connection:
        for _name, _category, _source, _status, minutes in samples:
            connection.execute(
                "UPDATE operations SET organized_at = ? WHERE download_id = ?",
                ((now - timedelta(minutes=minutes)).isoformat(timespec="seconds"), f"demo-{minutes}"),
            )


def seed_downloads(directory: Path) -> None:
    """A believable Downloads folder, including two files that cannot move."""
    directory.mkdir(parents=True, exist_ok=True)
    samples = [
        ("holiday-photo.jpg", 1_820_000),
        ("invoice-2026.pdf", 420_000),
        ("podcast-ep12.mp3", 2_400_000),
        ("project-assets.zip", 3_100_000),
        ("setup-x64.exe", 1_250_000),
        ("screen-recording.mp4", 2_050_000),
        ("notes.unknownext", 12_000),
        ("big-archive.7z.crdownload", 900_000),
        (".partial-download", 4_000),
    ]
    for name, size in samples:
        path = directory / name
        if not path.exists():
            path.write_bytes(b"\0" * size)


def main(argv: list[str]) -> int:
    output = Path(argv[0]) if argv else PROJECT_ROOT / "docs" / "screens"
    output.mkdir(parents=True, exist_ok=True)

    # A fresh scratch directory per run: never delete an existing one, so the
    # script is safe to run repeatedly and cannot touch anything outside
    # .pytest-tmp/.
    scratch = PROJECT_ROOT / ".pytest-tmp" / f"screens-{os.getpid()}-{int(time.time())}"
    scratch.mkdir(parents=True, exist_ok=True)
    data_dir = scratch / "data"
    destination = scratch / "SmartSort"
    destination.mkdir(parents=True, exist_ok=True)
    downloads = scratch / "Downloads"
    seed_downloads(downloads)
    os.environ["SMARTSORT_DATA_DIR"] = str(data_dir)

    app = QApplication.instance() or QApplication([])

    from smartsort.app.ui.controller import AppController
    from smartsort.app.ui.main_window import MainWindow

    context = create_context(data_dir, setup_logs=False)
    seed(context, destination)
    set_language(context.settings.language)

    controller = AppController(context)
    controller.start()
    window = MainWindow(controller)
    window.resize(1100, 760)
    window.show()

    pages = [
        ("dashboard", "01-dashboard.png"),
        ("settings", "02-settings.png"),
        ("history", "03-history.png"),
        ("categories", "04-categories.png"),
        ("about", "05-about.png"),
    ]
    for key, filename in pages:
        window.navigate(key)
        app.processEvents()
        window.grab().save(str(output / filename))
        print(f"wrote {output / filename}")

    # The scan dialog is modal, so build it and fill the table directly rather
    # than going through exec().
    from smartsort.app.ui.scan_dialog import ScanDialog
    from smartsort.app.ui.theme import palette_for

    dialog = ScanDialog(controller, window, directory=str(downloads))
    dialog.apply_palette(palette_for(context.settings.theme))
    dialog._populate(controller.scan_folder(str(downloads)))
    dialog.resize(940, 620)
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(output / "06-scan.png"))
    print(f"wrote {output / '06-scan.png'}")
    dialog.reject()

    window.quit_application()
    context.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
