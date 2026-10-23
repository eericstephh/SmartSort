"""PyInstaller entry point for the desktop application.

PyInstaller needs a real script (not a package module) so that absolute
imports resolve; the package itself keeps relative imports.
"""

from __future__ import annotations

import multiprocessing
import sys

from smartsort.app.main import main

if __name__ == "__main__":
    # Required for frozen builds on Windows so that any helper process does not
    # re-run the GUI.
    multiprocessing.freeze_support()
    sys.exit(main())
