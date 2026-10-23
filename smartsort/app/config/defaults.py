"""Static defaults for SmartSort.

Everything in this module is pure data so that it can be imported by the
storage layer (migrations), the core engine and the tests without pulling in
Qt or Windows-specific modules.
"""

from __future__ import annotations

APP_NAME = "SmartSort"
APP_VERSION = "1.0.0"
APP_PUBLISHER = "SmartSort Project"
APP_DESCRIPTION = "Local-first download organizer for Windows"
APP_HOMEPAGE = "https://example.invalid/smartsort"

# Identifier used by the browser native messaging registry entries.
NATIVE_HOST_NAME = "com.smartsort.host"

# Named pipe used between the native messaging host process and the desktop app.
# A named pipe is per-machine but access controlled by the OS and additionally
# authenticated with a shared HMAC key, so it is never a network listener.
#
# v2 changed the payload encoding from pickle to length-prefixed JSON. The name
# is versioned so a stale host binary cannot silently speak the old format: it
# simply finds no pipe and reports "app not running" instead.
PIPE_NAME = r"\\.\pipe\smartsort-bridge-v2"

# Hard cap on one bridge payload. Enforced before any decoding so a hostile
# client cannot make the app allocate an unbounded buffer.
MAX_BRIDGE_BYTES = 2 * 1024 * 1024  # 2 MiB

# Protocol version exchanged between extension <-> host <-> app.
PROTOCOL_VERSION = 1

# Hard limits for anything coming from a browser.
MAX_MESSAGE_BYTES = 1024 * 1024  # 1 MiB
MAX_PATH_LENGTH = 32767
MAX_FILENAME_LENGTH = 255
# Chrome and Edge extension IDs are always 32 characters from [a-p].
EXTENSION_ID_LENGTH = 32

# Database schema version. Bump together with a new migration step.
SCHEMA_VERSION = 1

OTHER_CATEGORY_ID = "other"

# Suffixes that indicate a file is still being written by a download manager or
# browser. These are *hints*: a file with such a suffix is never organized.
TEMP_SUFFIXES: tuple[str, ...] = (
    ".crdownload",  # Chromium / Chrome / Edge
    ".part",        # Firefox and many download managers
    ".partial",     # Internet Explorer / Edge legacy
    ".download",    # Safari / generic
    ".opdownload",  # Opera
    ".tmp",
)

# Prefixes that are never considered user downloads.
IGNORED_PREFIXES: tuple[str, ...] = (".", "~$", "~")

# Built-in categories. ``extensions`` are stored without the leading dot.
CATEGORY_DEFINITIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "images",
        "Images",
        ("jpg", "jpeg", "png", "gif", "bmp", "webp", "svg", "tif", "tiff", "ico", "avif"),
    ),
    (
        "videos",
        "Videos",
        ("mp4", "mkv", "mov", "avi", "webm", "wmv", "m4v", "mpeg", "mpg"),
    ),
    (
        "documents",
        "Documents",
        (
            "pdf", "doc", "docx", "txt", "rtf", "odt",
            "xls", "xlsx", "csv", "ppt", "pptx", "odp", "ods",
        ),
    ),
    (
        "audio",
        "Audio",
        ("mp3", "wav", "flac", "aac", "m4a", "ogg", "opus", "wma"),
    ),
    (
        "archives",
        "Archives",
        ("zip", "7z", "rar", "tar", "gz", "bz2", "xz"),
    ),
    (
        "installers",
        "Installers",
        ("exe", "msi", "msix", "appx"),
    ),
    (
        "other",
        "Other",
        (),
    ),
)

DEFAULT_SETTINGS: dict[str, object] = {
    # Destination
    "destination_dir": "",
    # Behaviour
    "auto_organize": True,
    "use_date_folders": True,
    "use_category_folders": True,
    # Only move files that the browser saved into its own default folder when
    # this policy allows it. When disabled, browser downloads are recorded but
    # left in place.
    "allow_move_from_browser_default": True,
    # Fallback folder watching
    "watch_enabled": False,
    "watch_directory": "",
    "watch_poll_seconds": 2.0,
    "watch_settle_seconds": 3.0,
    # Desktop integration
    "start_with_windows": False,
    "minimize_to_tray": True,
    "close_to_tray": True,
    # Appearance / language
    "language": "en",
    "theme": "light",
    # Browser integration
    "allowed_extension_ids": [],
    "browser_integration_enabled": True,
    # History
    "history_retention_days": 0,  # 0 = keep forever
    # Misc
    "onboarding_completed": False,
    "last_seen_version": "",
}

# Settings keys that may contain secrets are deliberately absent: SmartSort
# never stores credentials.
SECRET_SETTING_KEYS: tuple[str, ...] = ()

# Status values used in the ``operations`` table.
STATUS_ORGANIZED = "organized"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
STATUS_DUPLICATE = "duplicate"
STATUS_UNDONE = "undone"

# Undo states.
UNDO_AVAILABLE = "available"
UNDO_DONE = "undone"
UNDO_BLOCKED = "blocked"
UNDO_UNAVAILABLE = "unavailable"
