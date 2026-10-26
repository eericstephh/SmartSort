# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for SmartSort.

Produces a single portable folder containing two executables that share one
runtime:

    dist/SmartSort/SmartSort.exe        windowed desktop application
    dist/SmartSort/smartsort-host.exe   console native messaging host
    dist/SmartSort/browser_extension/   the Chrome/Edge extension

Build with:

    pyinstaller --noconfirm --clean smartsort.spec
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

PROJECT_ROOT = Path(SPECPATH).resolve()

# docs/ is bundled for offline reading, but docs/media holds the tutorial video,
# which is a download-and-share asset: shipping it inside the application would
# add ~5 MB twice (the app folder and _internal) for something nobody opens from
# there. Every other documentation file is still included.
DOCS_DIR = PROJECT_ROOT / "docs"
DOCS_DATAS = [
    (str(path), str(path.parent.relative_to(PROJECT_ROOT)))
    for path in sorted(DOCS_DIR.rglob("*"))
    if path.is_file() and "media" not in path.relative_to(DOCS_DIR).parts
]

datas = [
    (str(PROJECT_ROOT / "assets" / "smartsort.ico"), "assets"),
    (str(PROJECT_ROOT / "browser_extension"), "browser_extension"),
    (str(PROJECT_ROOT / "LICENSE"), "."),
    (str(PROJECT_ROOT / "README.md"), "."),
    (str(PROJECT_ROOT / "CHANGELOG.md"), "."),
    *DOCS_DATAS,
]

hiddenimports = [
    "PySide6.QtNetwork",
    "PySide6.QtSvg",
    *collect_submodules("smartsort"),
]

excludes = [
    "tkinter",
    "unittest",
    "pydoc_data",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtQuick",
    "PySide6.QtQml",
    "PySide6.Qt3DCore",
    "PySide6.QtMultimedia",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtPdf",
    "PySide6.QtTest",
    "pytest",
]

gui_analysis = Analysis(
    [str(PROJECT_ROOT / "scripts" / "entry_gui.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

host_analysis = Analysis(
    [str(PROJECT_ROOT / "scripts" / "entry_host.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=collect_submodules("smartsort.app.browser"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes + ["PySide6"],
    noarchive=False,
)

gui_pyz = PYZ(gui_analysis.pure, gui_analysis.zipped_data)
host_pyz = PYZ(host_analysis.pure, host_analysis.zipped_data)

gui_exe = EXE(
    gui_pyz,
    gui_analysis.scripts,
    [],
    exclude_binaries=True,
    name="SmartSort",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_ROOT / "assets" / "smartsort.ico"),
)

host_exe = EXE(
    host_pyz,
    host_analysis.scripts,
    [],
    exclude_binaries=True,
    name="smartsort-host",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_ROOT / "assets" / "smartsort.ico"),
)

collection = COLLECT(
    gui_exe,
    gui_analysis.binaries,
    gui_analysis.datas,
    host_exe,
    host_analysis.binaries,
    host_analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SmartSort",
)
