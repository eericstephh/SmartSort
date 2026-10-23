"""Build the two release artifacts.

    dist/SmartSort-<version>-portable.zip   unzip anywhere, keep your data with it
    dist/SmartSort-Setup-<version>.exe      per-user installer, no admin rights

The application folder itself (``dist/SmartSort``) is produced by
``build_windows.ps1`` / ``smartsort.spec``. This script adds the uninstaller,
packs the payload and drives PyInstaller for the setup executable.

It also stages ``release/`` — the exact set of files to attach to a GitHub
release, with a checksum file and the release notes taken from ``CHANGELOG.md``.

    python scripts/build_release.py
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST = PROJECT_ROOT / "dist"
APP_DIR = DIST / "SmartSort"
BUILD = PROJECT_ROOT / "build" / "release"
RELEASE_DIR = PROJECT_ROOT / "release"
CHANGELOG = PROJECT_ROOT / "CHANGELOG.md"

APP_NAME = "SmartSort"
APP_VERSION = "1.0.0"
PORTABLE_MARKER = "portable.txt"

PORTABLE_ZIP = DIST / f"{APP_NAME}-{APP_VERSION}-portable.zip"
SETUP_EXE = DIST / f"{APP_NAME}-Setup-{APP_VERSION}.exe"


def log(message: str) -> None:
    print(f"[release] {message}", flush=True)


def human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_pyinstaller(args: list[str], *, work: str) -> None:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--log-level",
        "WARN",
        "--workpath",
        str(BUILD / work),
        "--specpath",
        str(BUILD / work),
    ]
    command.extend(args)
    log(f"PyInstaller ({work}) …")
    completed = subprocess.run(command, cwd=str(PROJECT_ROOT), check=False)
    if completed.returncode != 0:
        raise SystemExit(f"PyInstaller failed for {work}")


def build_uninstaller() -> Path:
    target = BUILD / "uninstall.exe"
    if target.exists():
        target.unlink()
    run_pyinstaller(
        [
            "--onefile",
            "--windowed",
            "--name",
            "uninstall",
            "--icon",
            str(PROJECT_ROOT / "assets" / "smartsort.ico"),
            "--distpath",
            str(BUILD),
            "--exclude-module",
            "PySide6",
            "--exclude-module",
            "tkinter",
            "--exclude-module",
            "pytest",
            str(PROJECT_ROOT / "scripts" / "uninstall_app.py"),
        ],
        work="pyi-uninstall",
    )
    if not target.is_file():
        raise SystemExit("the uninstaller was not produced")
    log(f"uninstaller: {human(target.stat().st_size)}")
    return target


def zip_tree(root: Path, archive: Path, *, arc_root: str = "") -> None:
    if archive.exists():
        archive.unlink()
    files = [path for path in root.rglob("*") if path.is_file()]
    log(f"compressing {len(files)} files into {archive.name} …")
    started = time.time()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in files:
            relative = path.relative_to(root).as_posix()
            bundle.write(path, arcname=f"{arc_root}/{relative}" if arc_root else relative)
    log(f"  {human(archive.stat().st_size)} in {time.time() - started:.0f}s")


def stage_payload(uninstaller: Path) -> Path:
    # A fresh directory per run: never delete the previous staging tree, so the
    # script is safe to re-run and cannot touch anything it did not create.
    staging = BUILD / f"payload-{time.strftime('%H%M%S')}"
    app_root = staging / APP_NAME
    app_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(APP_DIR, app_root, dirs_exist_ok=True)
    shutil.copy2(uninstaller, app_root / "uninstall.exe")
    archive = BUILD / "payload.zip"
    # No top-level folder: the installer extracts the payload straight into the
    # install directory.
    zip_tree(app_root, archive)
    return archive


def build_installer(payload: Path) -> Path:
    if SETUP_EXE.exists():
        SETUP_EXE.unlink()
    # Absolute: PyInstaller resolves --add-data relative to the spec directory.
    payload = payload.resolve()
    run_pyinstaller(
        [
            "--onefile",
            "--windowed",
            "--name",
            SETUP_EXE.stem,
            "--icon",
            str(PROJECT_ROOT / "assets" / "smartsort.ico"),
            "--distpath",
            str(DIST),
            "--add-data",
            f"{payload};.",
            "--exclude-module",
            "tkinter",
            "--exclude-module",
            "pytest",
            "--exclude-module",
            "PySide6.QtNetwork",
            "--exclude-module",
            "PySide6.QtQml",
            "--exclude-module",
            "PySide6.QtQuick",
            "--exclude-module",
            "PySide6.QtTest",
            "--exclude-module",
            "PySide6.QtPdf",
            "--exclude-module",
            "PySide6.QtSvg",
            str(PROJECT_ROOT / "scripts" / "installer_app.py"),
        ],
        work="pyi-setup",
    )
    if not SETUP_EXE.is_file():
        raise SystemExit("the setup executable was not produced")
    return SETUP_EXE


def build_portable() -> Path:
    staging = BUILD / f"portable-{time.strftime('%H%M%S')}" / APP_NAME
    staging.mkdir(parents=True, exist_ok=True)
    shutil.copytree(APP_DIR, staging, dirs_exist_ok=True)
    # The uninstaller belongs to an installation, not to a portable copy.
    stray = staging / "uninstall.exe"
    if stray.exists():
        stray.unlink()
    (staging / PORTABLE_MARKER).write_text(
        "This file makes SmartSort portable.\n"
        "While it exists, the database, logs and bridge token are kept in the\n"
        "'data' folder next to the executable instead of %LOCALAPPDATA%.\n"
        "Delete it to go back to the normal per-user location.\n",
        encoding="utf-8",
    )
    zip_tree(staging, PORTABLE_ZIP, arc_root=APP_NAME)
    return PORTABLE_ZIP


def sync_bundled_docs() -> None:
    """Copy the documentation into the build folder before packing.

    PyInstaller bundles ``docs/`` at build time, so a README edited afterwards
    would ship stale. Doing it here means the artifacts always match the
    repository, wherever the app folder came from.
    """
    targets = [APP_DIR]
    internal = APP_DIR / "_internal"
    if internal.is_dir():
        targets.append(internal)

    for folder in targets:
        for name in ("README.md", "CHANGELOG.md", "LICENSE"):
            source = PROJECT_ROOT / name
            if source.is_file():
                shutil.copy2(source, folder / name)
        docs_target = folder / "docs"
        if (PROJECT_ROOT / "docs").is_dir():
            shutil.copytree(PROJECT_ROOT / "docs", docs_target, dirs_exist_ok=True)


def release_notes() -> str:
    """The CHANGELOG section for this version, ready to paste into GitHub."""
    if not CHANGELOG.is_file():
        return f"SmartSort {APP_VERSION}\n"
    text = CHANGELOG.read_text(encoding="utf-8")
    marker = f"## [{APP_VERSION}]"
    start = text.find(marker)
    if start < 0:
        return f"SmartSort {APP_VERSION}\n"
    following = text.find("\n## [", start + len(marker))
    section = text[start:] if following < 0 else text[start:following]
    return section.strip() + "\n"


def stage_release(artifacts: list[Path]) -> Path:
    """Copy the artifacts into release/ with checksums and release notes."""
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for artifact in artifacts:
        target = RELEASE_DIR / artifact.name
        shutil.copy2(artifact, target)
        lines.append(f"{sha256(target)}  {target.name}")
    # newline="\n": a CRLF checksum file breaks `sha256sum -c`, which is the
    # first thing anyone runs against a download.
    (RELEASE_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )
    (RELEASE_DIR / f"RELEASE_NOTES-{APP_VERSION}.md").write_text(
        release_notes(), encoding="utf-8", newline="\n"
    )
    return RELEASE_DIR


def main() -> int:
    if not (APP_DIR / "SmartSort.exe").is_file():
        print(
            "error: dist/SmartSort/SmartSort.exe is missing.\n"
            "       Run .\\scripts\\build_windows.ps1 first.",
            file=sys.stderr,
        )
        return 2

    BUILD.mkdir(parents=True, exist_ok=True)
    started = time.time()

    sync_bundled_docs()
    uninstaller = build_uninstaller()
    payload = stage_payload(uninstaller)
    setup = build_installer(payload)
    portable = build_portable()
    release = stage_release([portable, setup])

    print("")
    log(f"done in {time.time() - started:.0f}s")
    for path in (portable, setup):
        print(f"  {path.name:38} {human(path.stat().st_size):>10}  sha256 {sha256(path)[:16]}…")
    print("")
    print("Portable: unzip and run SmartSort.exe. Data stays in the 'data' subfolder.")
    print("Setup:    run the executable; it installs for the current user only.")
    print("")
    print(f"GitHub release ready in {release}")
    for item in sorted(release.iterdir()):
        print(f"  {item.name}")
    print("")
    print("Publish with:")
    print(f'  gh release create v{APP_VERSION} "{release}"/* --title "SmartSort {APP_VERSION}" '
          f'--notes-file "{release / f"RELEASE_NOTES-{APP_VERSION}.md"}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
