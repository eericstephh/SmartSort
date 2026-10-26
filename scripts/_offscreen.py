"""Shared helpers for the offscreen rendering scripts.

Both ``capture_screens.py`` and ``make_demo_video.py`` build the real window
without a display, and both need two things that the offscreen platform does
not provide on its own: a font database and a scratch folder whose path does
not contain the account name of whoever ran the script.
"""

from __future__ import annotations

import os
from pathlib import Path

# The offscreen platform does not enumerate the system font database here, so
# every glyph would be drawn as a box. The files themselves are still readable,
# so they are registered by hand before any widget is built.
FONT_FILES = (
    "segoeui.ttf",
    "segoeuib.ttf",
    "segoeuisl.ttf",
    "segoeuil.ttf",
    "tahoma.ttf",
    "tahomabd.ttf",
)

# Screenshots and video frames end up in documentation, so every path they show
# has to be neutral: C:\Users\<name>\... would publish a real account name.
NEUTRAL_ROOT = Path("C:/SmartSortDemo")
MARKER = ".smartsort-demo"


def register_fonts() -> int:
    """Register the system fonts that Qt failed to enumerate.

    Returns the number of families available afterwards. Raises when none
    could be loaded, because rendering would silently produce boxes.
    """
    from PySide6.QtGui import QFontDatabase

    folder = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in FONT_FILES:
        path = folder / name
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))

    families = len(QFontDatabase.families())
    if not families:
        raise SystemExit("no fonts could be registered; text would render as boxes")
    return families


def neutral_scratch(tag: str, *, clean: bool = False) -> Path:
    """Return a scratch folder under :data:`NEUTRAL_ROOT`.

    ``clean=True`` reuses the root itself, so the paths on screen stay short
    (``C:\\SmartSortDemo\\Organized`` rather than one containing a timestamp).
    That means the folder has to be cleared, which is only acceptable because
    these scripts stamp a marker file into it: an existing folder without the
    marker is somebody else's and the script stops instead of deleting it.
    """
    import shutil
    import time

    if clean:
        if NEUTRAL_ROOT.exists():
            contents = list(NEUTRAL_ROOT.iterdir())
            if contents and not (NEUTRAL_ROOT / MARKER).is_file():
                raise SystemExit(
                    f"{NEUTRAL_ROOT} exists and was not created by these scripts;"
                    " move it aside or delete it yourself first"
                )
            shutil.rmtree(NEUTRAL_ROOT, ignore_errors=True)
        NEUTRAL_ROOT.mkdir(parents=True, exist_ok=True)
        (NEUTRAL_ROOT / MARKER).write_text(
            "Scratch folder for the SmartSort documentation scripts.\n"
            "It is safe to delete.\n",
            encoding="utf-8",
        )
        return NEUTRAL_ROOT

    folder = NEUTRAL_ROOT / f"{tag}-{os.getpid()}-{int(time.time())}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder
