"""Low-level, crash-safe filesystem operations.

The two hard requirements are:

* never overwrite an existing file, and
* never destroy the source file unless the destination is verified.

Everything here is synchronous and blocking; callers run it off the UI thread.
"""

from __future__ import annotations

import errno
import logging
import os
import shutil
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_TEMP_PREFIX = ".smartsort-"
_TEMP_SUFFIX = ".part"

# Windows error codes we care about.
_ERROR_DISK_FULL = 112
_ERROR_HANDLE_DISK_FULL = 39
_ERROR_ACCESS_DENIED = 5
_ERROR_SHARING_VIOLATION = 32
_ERROR_LOCK_VIOLATION = 33


class MoveError(Exception):
    """A move failed. The source file is preserved whenever possible."""

    def __init__(self, code: str, message: str, *, source_preserved: bool = True):
        super().__init__(message)
        self.code = code
        self.message = message
        self.source_preserved = source_preserved


@dataclass
class MoveOutcome:
    final_path: Path
    mode: str  # "rename" | "copy"
    warning: str | None = None


def long_path(path: Path | str) -> str:
    """Return a path string usable beyond MAX_PATH on Windows."""
    raw = os.fspath(path)
    if raw.startswith("\\\\?\\"):
        return raw
    absolute = os.path.abspath(raw)
    if len(absolute) < 240:
        return absolute
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def is_within(child: Path | str, parent: Path | str) -> bool:
    """True when ``child`` is ``parent`` or lives inside it.

    Both paths are compared after ``resolve()`` so that ``..`` segments, short
    names and symlinks cannot be used to escape the check.
    """
    try:
        child_resolved = Path(child).resolve(strict=False)
        parent_resolved = Path(parent).resolve(strict=False)
    except (OSError, RuntimeError):
        return False
    if child_resolved == parent_resolved:
        return True
    try:
        child_resolved.relative_to(parent_resolved)
    except ValueError:
        return False
    return True


# -- protected locations ---------------------------------------------------
# A compromised browser extension can name any path it likes. These directories
# are never a legitimate download target, so a move out of them is refused
# before anything is read or written.
_PROTECTED_ENV_VARS = (
    "SystemRoot",
    "windir",
    "ProgramFiles",
    "ProgramFiles(x86)",
    "ProgramData",
)


def protected_roots() -> list[Path]:
    """Directories a download can never legitimately live in."""
    candidates: list[Path] = []
    for name in _PROTECTED_ENV_VARS:
        value = os.environ.get(name)
        if value:
            candidates.append(Path(value))
    system_drive = os.environ.get("SystemDrive", "C:")
    candidates.append(Path(f"{system_drive}\\Windows"))

    roots: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=False)
        except (OSError, RuntimeError):
            continue
        if resolved not in roots:
            roots.append(resolved)
    return roots


def is_protected_location(path: Path | str) -> bool:
    """True when ``path`` sits inside a Windows system or program directory."""
    return any(is_within(path, root) for root in protected_roots())


def same_volume(a: Path | str, b: Path | str) -> bool:
    """Best-effort check whether two paths live on the same filesystem."""
    try:
        dev_a = os.stat(os.path.dirname(os.path.abspath(os.fspath(a)))).st_dev
    except OSError:
        try:
            dev_a = Path(a).stat().st_dev
        except OSError:
            dev_a = None
    try:
        dev_b = os.stat(os.path.abspath(os.fspath(b))).st_dev
    except OSError:
        dev_b = None
    if dev_a is None or dev_b is None:
        return False
    return dev_a == dev_b


def is_locked(path: Path | str) -> bool:
    """Heuristic: can this file be renamed right now?

    Renaming a file to its own name is a cheap, side-effect free way to ask the
    OS whether any other process holds it open without sharing. This is how we
    avoid touching files that a browser is still writing.
    """
    raw = long_path(path)
    try:
        os.rename(raw, raw)
    except FileNotFoundError:
        return True
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EPERM):
            return True
        if getattr(exc, "winerror", None) in (_ERROR_SHARING_VIOLATION, _ERROR_LOCK_VIOLATION):
            return True
        return False
    return False


def free_space(path: Path | str) -> int:
    try:
        return shutil.disk_usage(os.path.abspath(os.fspath(path))).free
    except OSError:
        return -1


def safe_move(
    source: Path,
    target_dir: Path,
    filename: str,
    *,
    max_attempts: int = 2000,
) -> MoveOutcome:
    """Move ``source`` into ``target_dir`` as ``filename`` without overwriting.

    Same-volume moves use an atomic ``os.rename`` which fails (rather than
    overwrites) when the target exists. Cross-volume moves copy to a temporary
    file inside the destination directory, verify the byte count, atomically
    rename the temporary file into place, and only then unlink the source.
    """
    source = Path(source)
    target_dir = Path(target_dir)
    if not source.exists():
        raise MoveError("source_missing", f"source file does not exist: {source}")
    if source.is_dir():
        raise MoveError("source_not_a_file", f"source is a directory: {source}")

    target_dir.mkdir(parents=True, exist_ok=True)

    if same_volume(source, target_dir):
        try:
            return _rename_into(source, target_dir, filename, max_attempts)
        except _CrossDevice:
            logger.info("rename reported EXDEV, falling back to copy: %s", source)

    return _copy_then_rename(source, target_dir, filename, max_attempts)


class _CrossDevice(Exception):
    pass


def _rename_into(
    source: Path, target_dir: Path, filename: str, max_attempts: int
) -> MoveOutcome:
    from .conflict_resolver import iter_candidates

    for candidate in iter_candidates(target_dir, filename, max_attempts):
        try:
            os.rename(long_path(source), long_path(candidate))
        except FileExistsError:
            continue
        except OSError as exc:
            if exc.errno == errno.EXDEV:
                raise _CrossDevice() from exc
            raise _translate_error(exc, source) from exc
        return MoveOutcome(final_path=candidate, mode="rename")
    raise MoveError(
        "conflict_exhausted",
        f"could not find a free file name for {filename}",
    )


def _copy_then_rename(
    source: Path, target_dir: Path, filename: str, max_attempts: int
) -> MoveOutcome:
    from .conflict_resolver import iter_candidates

    try:
        size = source.stat().st_size
    except OSError as exc:
        raise MoveError("source_unreadable", f"cannot stat source: {exc}") from exc

    available = free_space(target_dir)
    if 0 <= available < size:
        raise MoveError(
            "disk_full",
            f"not enough free space on the destination ({available} bytes free,"
            f" {size} bytes needed)",
        )

    temp_path = target_dir / f"{_TEMP_PREFIX}{uuid.uuid4().hex}{_TEMP_SUFFIX}"
    copied = 0
    try:
        with open(long_path(source), "rb") as src_handle:
            # "xb" guarantees we never clobber an existing file.
            with open(long_path(temp_path), "xb") as dst_handle:
                while True:
                    chunk = src_handle.read(1024 * 1024)
                    if not chunk:
                        break
                    dst_handle.write(chunk)
                    copied += len(chunk)
                dst_handle.flush()
                os.fsync(dst_handle.fileno())
    except OSError as exc:
        _silent_unlink(temp_path)
        raise _translate_error(exc, source) from exc

    if copied != size:
        _silent_unlink(temp_path)
        raise MoveError(
            "copy_incomplete",
            f"copied {copied} of {size} bytes; source kept",
        )

    try:
        shutil.copystat(long_path(source), long_path(temp_path))
    except OSError:
        logger.debug("copystat failed for %s", temp_path, exc_info=True)

    final_path: Path | None = None
    for candidate in iter_candidates(target_dir, filename, max_attempts):
        try:
            os.rename(long_path(temp_path), long_path(candidate))
        except FileExistsError:
            continue
        except OSError as exc:
            _silent_unlink(temp_path)
            raise _translate_error(exc, source) from exc
        final_path = candidate
        break

    if final_path is None:
        _silent_unlink(temp_path)
        raise MoveError(
            "conflict_exhausted",
            f"could not find a free file name for {filename}",
        )

    warning = None
    try:
        os.unlink(long_path(source))
    except OSError as exc:
        # The destination copy is complete and verified, so we keep it and tell
        # the user that the source could not be removed.
        warning = f"source_not_removed: {exc}"
        logger.warning("could not remove source after copy: %s (%s)", source, exc)

    return MoveOutcome(final_path=final_path, mode="copy", warning=warning)


def _silent_unlink(path: Path) -> None:
    try:
        os.unlink(long_path(path))
    except OSError:
        logger.debug("could not clean up %s", path, exc_info=True)


def _translate_error(exc: OSError, source: Path) -> MoveError:
    winerror = getattr(exc, "winerror", None)
    if exc.errno == errno.ENOSPC or winerror in (_ERROR_DISK_FULL, _ERROR_HANDLE_DISK_FULL):
        return MoveError("disk_full", f"destination is full: {exc}")
    if exc.errno in (errno.EACCES, errno.EPERM) or winerror in (
        _ERROR_ACCESS_DENIED,
        _ERROR_SHARING_VIOLATION,
        _ERROR_LOCK_VIOLATION,
    ):
        return MoveError("permission_denied", f"access denied moving {source}: {exc}")
    if exc.errno == errno.ENOENT:
        return MoveError("source_missing", f"source disappeared: {exc}")
    if isinstance(exc, OSError) and exc.errno == errno.ENAMETOOLONG:
        return MoveError("path_too_long", f"path too long: {exc}")
    return MoveError("io_error", f"{type(exc).__name__}: {exc}")


def restore_move(source: Path, target: Path) -> MoveOutcome:
    """Move ``source`` back to the exact path ``target`` (used by undo)."""
    source = Path(source)
    target = Path(target)
    if not source.exists():
        raise MoveError("source_missing", f"file is no longer at {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if same_volume(source, target.parent):
        try:
            os.rename(long_path(source), long_path(target))
        except FileExistsError as exc:
            raise MoveError("target_exists", f"{target} already exists") from exc
        except OSError as exc:
            if exc.errno == errno.EXDEV:
                pass
            else:
                raise _translate_error(exc, source) from exc
        else:
            return MoveOutcome(final_path=target, mode="rename")
    return _copy_to_exact(source, target)


def _copy_to_exact(source: Path, target: Path) -> MoveOutcome:
    size = source.stat().st_size
    available = free_space(target.parent)
    if 0 <= available < size:
        raise MoveError("disk_full", "not enough free space to restore the file")
    temp_path = target.parent / f"{_TEMP_PREFIX}{uuid.uuid4().hex}{_TEMP_SUFFIX}"
    try:
        with open(long_path(source), "rb") as src_handle:
            with open(long_path(temp_path), "xb") as dst_handle:
                shutil.copyfileobj(src_handle, dst_handle, 1024 * 1024)
                dst_handle.flush()
                os.fsync(dst_handle.fileno())
    except OSError as exc:
        _silent_unlink(temp_path)
        raise _translate_error(exc, source) from exc
    try:
        os.rename(long_path(temp_path), long_path(target))
    except FileExistsError as exc:
        _silent_unlink(temp_path)
        raise MoveError("target_exists", f"{target} already exists") from exc
    except OSError as exc:
        _silent_unlink(temp_path)
        raise _translate_error(exc, source) from exc
    warning = None
    try:
        os.unlink(long_path(source))
    except OSError as exc:
        warning = f"source_not_removed: {exc}"
    return MoveOutcome(final_path=target, mode="copy", warning=warning)


def file_is_stable(path: Path, settle_seconds: float, now: float) -> bool:
    """Not used directly; kept for callers that only need a mtime check."""
    try:
        info = path.stat()
    except OSError:
        return False
    if info.st_size <= 0:
        return False
    if not stat.S_ISREG(info.st_mode):
        return False
    return (now - info.st_mtime) >= settle_seconds
