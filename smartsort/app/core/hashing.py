"""Content hashing used by duplicate detection.

A hash is an optimisation, never a requirement: if the file cannot be read the
caller still has to move it, so every error is logged and turned into ``None``
rather than raised. Hashing happens before the move, while the file is still at
its source path.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# One megabyte keeps memory flat on a 4 GB download while staying sequential
# enough that the read is limited by the disk, not by the loop.
CHUNK_SIZE = 1024 * 1024


def sha256_file(path: str | Path, *, chunk_size: int = CHUNK_SIZE) -> str | None:
    """Return the SHA-256 hex digest of ``path``, or ``None`` if unreadable."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            while True:
                block = handle.read(chunk_size)
                if not block:
                    break
                digest.update(block)
    except OSError as exc:
        logger.warning("cannot hash %s: %s", path, exc)
        return None
    return digest.hexdigest()
