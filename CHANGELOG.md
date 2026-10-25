# Changelog

All notable changes to SmartSort are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Content-based duplicate detection**, off by default. When enabled, every
  download is hashed with SHA-256 before it moves and compared against the files
  already sorted; an identical file is left where it is and recorded as
  `content_duplicate`, with the path of the existing copy kept in the history.
  A duplicate is only reported when the earlier file is still on disk, and an
  undone operation stops counting. Hashing is skipped entirely while the setting
  is off, so nothing gets slower for users who do not want it.
- **User-defined categories.** The Rules & categories screen can now add a
  category with its own name and extensions, and rename or delete the ones you
  created. Names are validated against the Windows folder rules (reserved device
  names, `<>:"/\|?*`, trailing dots, length), because the name becomes a folder.
  Built-in categories stay fixed so files already sorted are never split across
  two folders, and a new category is appended last — an extension that another
  category already claims keeps going there, and the app says which one when
  that happens.
- **Continuous integration.** The suite now runs on `windows-latest` for Python
  3.10 and 3.13 on every push and pull request.
- The About screen shows a link to the project page, which previously pointed at
  a placeholder domain and was not displayed anywhere.

### Fixed

- `migrations.apply(conn, target=…)` applied migrations past the requested
  target; the parameter only guarded against a database that was too new. A
  caller asking for version 1 got version 2. Found by the new upgrade test.

## [1.0.0] — 2026-10-22

First public release. Windows 10/11, 64-bit, no administrator rights required.

### Added

- **Automatic organization of completed downloads** into
  `<destination>\YYYY-MM-DD\<Category>\`, with the date taken from the download
  completion time rather than the file's creation time.
- **Deterministic extension-based classification** into Images, Videos, Audio,
  Documents, Archives, Installers, Code, Fonts and Other. Compound suffixes such
  as `tar.gz` match before `gz`. Archives are never extracted and downloads are
  never opened or executed.
- **Chrome and Edge integration** through one Manifest V3 extension and a native
  messaging host (`smartsort-host.exe`) that talks to the app over a named pipe.
- **Fallback folder watcher** for browsers without the extension: polls a folder
  and requires the file size to stay unchanged for a configurable settle window.
- **History with undo.** Every attempt — organized, skipped, failed, duplicate —
  is recorded with both paths, size, timestamps and an error code. Undo verifies
  the file still exists and the original location is writable before restoring,
  and never deletes anything to "clean up" a failed undo.
- **Never overwrites.** Conflicts resolve to `photo (1).jpg`, `photo (2).jpg`, …
  and the rename is performed by the OS with exclusive-create semantics.
- **Cross-volume moves** copy to a temporary file with `xb`, `fsync`, verify the
  byte count, atomically rename into place, and only then unlink the source.
- **Scan an existing folder** — a read-only preview of what would happen to files
  already in Downloads, with per-file opt-out, then a batch organize.
- **Five screens** (Dashboard, Settings, History, Rules & categories, About &
  diagnostics), English by default, Persian with a full right-to-left layout.
- **Tray integration**, close-to-tray, single-instance enforcement, optional
  start with Windows (one `HKCU` Run value), rotating logs, diagnostics export and
  a settings/history backup.
- **Two release artifacts:** a portable zip that keeps its data beside the
  executable, and a per-user installer with shortcuts and a standalone
  uninstaller.

### Security

- The bridge carries **length-prefixed JSON, never pickle**, with a 2 MiB cap and
  a connection limit.
- Authentication is an **HMAC challenge/response** over a 32-byte token written
  with an ACL restricted to the current user.
- All browser input is **type-checked, length-limited and path-validated** before
  it can reach the organizer; traversal, NUL bytes, device paths and relative
  paths are rejected.
- The native messaging registration is **pinned to the extension ID you actually
  loaded**, so another extension cannot drive the app.
- **No network calls of any kind.** Nothing is uploaded; there is no telemetry,
  no analytics and no update check.
- The uninstaller keeps settings and history unless explicitly asked to delete
  them, its default button is the non-destructive one, and a confirmation dialog
  that fails to appear aborts the uninstall.

### Known limitations

- Binaries are **unsigned**, so Windows SmartScreen warns on first run.
- A browser extension **cannot redirect a download before it is saved**; SmartSort
  moves the file after the browser reports completion.
- The MV3 service worker is suspended when idle, so the popup can show
  "not connected" while everything still works.
- The folder watcher is a heuristic: a download that stalls for longer than the
  settle window can be moved while still incomplete.
- The extension has not been loaded into a real browser profile as part of an
  automated test; `docs/manual-acceptance.md` is the checklist for that.
