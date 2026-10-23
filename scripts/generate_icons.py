"""Generate the extension and application icons.

Run with the project virtualenv:

    .venv\\Scripts\\python.exe scripts\\generate_icons.py

The icons are drawn with QPainter (offscreen) so no binary design tool is
required, then written as PNG files plus a multi-size Windows ``.ico``.
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from smartsort.app.ui.branding import _draw  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)
EXTENSION_SIZES = (16, 32, 48, 128)


def png_bytes(size: int) -> bytes:
    pixmap = _draw(size)
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    pixmap.save(buffer, "PNG")
    data = bytes(buffer.data())
    buffer.close()
    return data


def write_png(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_bytes(size))


def write_ico(path: Path, sizes: tuple[int, ...] = SIZES) -> None:
    """Build an .ico container with embedded PNG images."""
    images = [(size, png_bytes(size)) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    directory = b""
    offset = 6 + 16 * len(images)
    entries = []
    for size, data in images:
        entries.append(
            struct.pack(
                "<BBBBHHII",
                0 if size >= 256 else size,
                0 if size >= 256 else size,
                0,
                0,
                1,
                32,
                len(data),
                offset,
            )
        )
        offset += len(data)
    directory = b"".join(entries)
    payload = b"".join(data for _size, data in images)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + directory + payload)


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841

    extension_dir = PROJECT_ROOT / "browser_extension" / "icons"
    for size in EXTENSION_SIZES:
        write_png(extension_dir / f"icon{size}.png", size)

    assets_dir = PROJECT_ROOT / "assets"
    write_png(assets_dir / "smartsort-256.png", 256)
    write_ico(assets_dir / "smartsort.ico")

    print(f"wrote {len(EXTENSION_SIZES)} extension icons to {extension_dir}")
    print(f"wrote assets/smartsort.ico and assets/smartsort-256.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
