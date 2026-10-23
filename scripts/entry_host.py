"""PyInstaller entry point for the browser native messaging host.

This executable is intentionally tiny and console-based: Chrome and Edge launch
it directly, so it must never allocate a window and must never write anything to
stdout except framed messages.
"""

from __future__ import annotations

import multiprocessing
import sys

from smartsort.app.browser.native_host import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
