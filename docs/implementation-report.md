# SmartSort — implementation report

Version 1.0.0 · built and verified on Windows with Python 3.13.14, PySide6 6.12.0,
pytest 9.1.1, PyInstaller 6.22.3.

This report states what was built, what was actually executed, and what is still
not proven. Nothing below is marked as passing on the strength of code existing.

---

## 1. Features implemented

### Download detection

- **Chrome and Edge extension** (one Manifest V3 codebase, loaded unpacked into
  either browser) listens to `chrome.downloads.onCreated` / `onChanged` and
  reports `download_completed`, `download_cancelled` and `download_interrupted`.
- **Native messaging host** (`smartsort-host.exe`) speaks the browser's
  4-byte-length-prefixed JSON protocol on stdin/stdout and forwards each message
  to the running desktop application over a **named pipe**.
- **Only completed downloads are organized.** `started`, `progress`,
  `interrupted` and `cancelled` events are recorded as no-ops, never as moves.
- **In-progress files are never touched**: `.crdownload`, `.part`, `.partial`,
  `.download`, `.opdownload`, `.tmp` are refused by the organizer even if a
  browser claims completion.
- **Fallback folder watcher** for browsers without the extension: polls a folder,
  requires the file size to stay unchanged for a configurable settle window,
  ignores temporary suffixes, dotfiles and anything already inside the
  destination.
- **Double-processing is impossible.** Every organized file records two dedupe
  keys — `dl:<browser>:<downloadId>` and `path:<sha256 of normalised path>` — so a
  browser event and the watcher reporting the same file resolve to `duplicate`.

### Organization

- Destination is any local drive, chosen in the UI, validated with a write probe
  before it is saved.
- Layout `<destination>\YYYY-MM-DD\<Category>\file.ext`, created on demand.
- The date comes from the **download completion timestamp** reported by the
  browser (falling back to file mtime when there is none), converted to local
  time, never from the file's creation date.
- Classification is a deterministic extension lookup. Compound suffixes such as
  `tar.gz` match before `gz`. Unknown or ambiguous extensions go to `Other`.
  Archives are never extracted and downloads are never opened or executed.
- **Never overwrites.** Conflicts resolve to `photo (1).jpg`, `photo (2).jpg`, …
  and the rename is performed by the OS with exclusive-create semantics, so two
  simultaneous downloads cannot claim the same name.
- **The source is never lost.** Same volume: atomic `os.rename`. Cross volume:
  write to a uniquely named temp file with `xb`, `fsync`, verify the byte count,
  copy metadata, atomically rename into place, and only then unlink the source.
- Recursive organization is impossible: a file already inside the destination is
  reported as `already_in_destination` and left alone.

### History, undo, recovery

- Every attempt — organized, skipped, failed, duplicate — is written to SQLite
  with original path, final path, category, size, timestamps, status, error code
  and message.
- History survives restart, is searchable by filename or path, and filters by
  status and category.
- **Undo** verifies the organized file still exists, checks the original location
  is available and writable, detects a conflict, asks for confirmation, restores
  without overwriting (renaming if the user chooses), and marks the operation
  undone. If any check fails it reports why and leaves the organized file intact
  — it never deletes a file to "clean up" a failed undo.

### Interface

Five screens, all text translatable, English default, Persian with full
right-to-left layout:

| Screen | Contents |
| --- | --- |
| Dashboard | Status, pause/resume, today/total/moved/failed tiles, destination, recent activity, browser connection state |
| Settings | Destination, four automation toggles, fallback watcher with poll/settle intervals, start with Windows, language, theme |
| History | Searchable, filterable table, Undo / Open location / Copy path, details panel |
| Rules & categories | Enable/disable categories, edit extension lists, restore defaults |
| About & diagnostics | Version, license, data folder, extension ID field, install/remove integration, open extension folder, log and DB paths, export diagnostics, back up settings and history |

No work runs on the UI thread that could block it; undo runs on a worker thread.
Long operations report through a status bar and tray notifications.

### Windows integration

- Tray icon with Show / Pause / Quit, close-to-tray, optional start with Windows
  (HKCU `Run` value `SmartSort`, opt-in, removed on uninstall).
- Single instance enforced with `QLocalServer`; a second launch raises the
  existing window instead of starting a rival organizer.
- Rotating logs (2 MB × 3), diagnostics export as a zip, database backup.
- Registry writes are HKCU-only and limited to SmartSort-owned values.

---

## 2. Files created

86 source files. Line counts are actual.

```
smartsort/app/
    core/            8 files   1,442 lines   classifier, organizer, conflict resolver,
                                             file ops, undo, download manager,
                                             folder scanner
    browser/         6 files   1,066 lines   protocol, validation, native host,
                                             bridge server, registry, manifest builder
    storage/         5 files     768 lines   database, migrations, models, repositories
    services/        4 files     523 lines   folder watcher, startup, logging/diagnostics
    config/          4 files     423 lines   defaults, typed settings, paths (portable mode)
    ui/             13 files   3,516 lines   theme, widgets, branding, workers, controller,
                                             dashboard, settings, history, categories, about,
                                             scan dialog, main window
    (app root)       4 files     872 lines   main, bootstrap, i18n
                                             ─────────
                                             8,610 lines

browser_extension/                 526 lines   manifest.json, background.js,
                                               popup.html, popup.js, icons/
scripts/                          3,540 lines   install_windows.ps1, uninstall_windows.ps1,
                                               register_native_host.ps1, build_windows.ps1,
                                               run_dev.ps1, smartsort-host.cmd,
                                               entry_gui.py, entry_host.py,
                                               generate_icons.py, verify_packaged.py,
                                               capture_screens.py,
                                               installer_app.py (GUI installer, 607),
                                               uninstall_app.py (335),
                                               build_release.py (225)
tests/                          3,223 lines   20 test modules (see §4)
docs/                                          architecture.md, security.md,
                                               installation.md,
                                               troubleshooting.md, privacy.md,
                                               manual-acceptance.md, implementation-report.md,
                                               screens/*.png
```

Root files: `README.md`, `LICENSE` (MIT + third-party notice), `pyproject.toml`,
`requirements.txt`, `requirements-dev.txt`, `smartsort.spec`, `.gitignore`,
`assets/smartsort.ico`, `assets/smartsort-256.png`.

### Changes made in this final pass

| File | Change |
| --- | --- |
| `smartsort/app/ui/categories_page.py` | Category column was clipped (`Documents`, `Installers` truncated). Column 0 switched from `ResizeToContents` to `Interactive` and sized from font metrics. |
| `smartsort/app/ui/theme.py` | Added stylesheets for disabled inputs, spin-box arrows, disabled primary buttons and disabled checkboxes, so a disabled control no longer looks active. |
| `smartsort/app/main.py` | **Bug fix.** `--data-dir` was applied *after* the maintenance branch returned, so `--print-paths`, `--register-host` and `--unregister-host` silently ignored it and used the real profile. The override now happens before any path is resolved. |
| `tests/integration/test_cli.py` | New. 4 tests covering `--version`, `--print-paths`, the `--data-dir` regression, and launcher resolution. |
| `scripts/capture_screens.py` | No longer deletes a scratch directory (uses a unique one per run); timestamps in the demo data are now spread out instead of all identical. |
| `docs/manual-acceptance.md` | New. The checklist for the parts that need a real browser. |
| `docs/screens/*.png` | Regenerated with the real Windows platform plugin; the previous set was rendered offscreen without a font database and showed boxes. |
| `README.md` | Screenshot table, link to the manual checklist, corrected test count. |

### Changes made in the packaging pass

| File | Change |
| --- | --- |
| `smartsort/app/config/paths.py` | Portable mode: a `portable.txt` file next to a frozen executable moves the data folder to `<exe_dir>\data`. Env override still wins; a source checkout is never portable. |
| `scripts/installer_app.py` | New. PySide6 GUI installer — per-user destination, optional desktop/Start-menu shortcuts (COM `IShellLinkW` via `ctypes`, no pywin32), HKCU uninstall entry, zip-slip-safe extraction, `/S` and `/D=` switches, Persian UI when the Windows UI language is Persian. |
| `scripts/uninstall_app.py` | New. Standalone uninstaller with no Qt dependency (8 MB instead of 40 MB). Removes shortcuts, the `Run` value, both native-host keys and the uninstall entry, optionally purges user data, then deletes the install folder after moving itself to `%TEMP%`. The default button keeps user data, and a failed confirmation dialog aborts instead of uninstalling. |
| `scripts/build_release.py` | New. Builds the uninstaller, stages the payload, packs the setup executable and the portable zip, and prints size + SHA-256 for both. |
| `tests/unit/test_paths.py` | New. 4 tests for the portable marker, the `%LOCALAPPDATA%` fallback, the env override and the source-checkout case. |
| `tests/unit/test_release_scripts.py` | New. 7 tests for switch normalisation, the uninstaller's refusal to delete shallow or foreign folders, and the installer's zip-slip rejection. |
| `docs/installation.md` | Rewritten install section: A1 portable, A2 installer, A3 destination, A4 startup, A5 verify; uninstall section now documents the Yes/No/Cancel prompt, `/S`, `/S /PURGE` and "delete the folder" for portable. |
| `README.md` | Two-artifact install section, `build_release.py`, and the portable data-folder note in the storage table. |

---

## 3. Architecture decisions

**Named pipe, not a local HTTP server.** The requirement was to avoid exposing an
unrestricted local HTTP server. The host connects to
`\\.\pipe\smartsort-bridge-v2` with `multiprocessing.connection`, authenticated by
a shared key file (`bridge.token`, 32 bytes from `os.urandom`, ACL-restricted to
the current user) and HMAC challenge/response. There is no TCP port to scan, no
CORS surface, and no request parsing to get wrong. Cost: the host must be
launched by the browser and cannot be reached from a web page, which is exactly
the intent.

The pipe carries **length-prefixed JSON, never pickle**. `Connection.send` /
`recv` would pickle the payload, and unpickling attacker-controlled data is
remote code execution; `send_bytes` / `recv_bytes` keep the authenticated
handshake and remove that primitive. `recv_bytes` is given a 2 MiB cap so a
hostile client cannot force an unbounded allocation. The pipe name is versioned
(`-v2`) so a stale host binary fails loudly with "app not running" instead of
silently speaking the old format.

**One-shot `sendNativeMessage`, not a persistent port.** Manifest V3 service
workers are suspended after roughly 30 seconds. A long-lived port would be torn
down constantly and downloads completed during suspension would be missed. Each
event is a single request/response, so the worker can be suspended at any moment
without losing a message.

**Two dedupe keys per file.** Either the browser event or the watcher can arrive
first, and both can fire for the same file. Writing both keys inside the same
transaction as the operation row makes the second reporter a no-op. This was
cheaper and more reliable than trying to coordinate the two sources in memory.

**Polling watcher, not `ReadDirectoryChangesW`.** Polling behaves predictably on
local, USB and SMB paths, where change notifications are unreliable or
unsupported. The settle window (size unchanged for N seconds) is also the only
practical way to decide a download stopped growing. The known weakness is
documented in §5.

**SQLite with WAL and explicit migrations.** One connection guarded by an
`RLock`, `BEGIN IMMEDIATE` for every write, and `PRAGMA user_version` driving
stepwise migrations. This gives crash safety and a schema that can be upgraded
without data loss, at the cost of serialising writes — which is irrelevant for
a download organizer.

**No-overwrite is enforced by the OS, not by checking first.** A
check-then-write race is possible with two simultaneous downloads. `os.rename`
onto an existing file fails on Windows, and temp files are created with mode
`xb`, so the guarantee holds under concurrency rather than merely usually.

**`pathlib` throughout, with a `\\?\` prefix only at the syscall boundary.**
Long paths are a real Windows failure mode. Paths are kept as `Path` objects and
extended only when a filesystem call is about to be made, so the rest of the code
never has to think about the prefix.

**PyInstaller `onedir`, not `onefile`.** Two executables share one `_internal`
tree. Onefile would unpack 120 MB to a temp directory on every launch — several
seconds of delay for a program that is supposed to sit in the tray. `onedir`
starts immediately and makes the layout inspectable.

**i18n as plain dictionaries, not `QTranslator`.** The UI has a few hundred
strings and one non-English language. A dictionary plus a `t()` function is
readable, diffable, and testable (`tests/unit/test_i18n.py` asserts the two
catalogues have identical key sets). `QTranslator` would add `.ts`/`.qm` tooling
for no benefit at this size.

**Portable mode is a marker file, not a build flag.** Two builds of the same
code would drift. Instead `paths.py` checks for `portable.txt` beside a frozen
executable, so one binary serves both artifacts: the zip ships the marker, the
installer does not. The decision is testable (`tests/unit/test_paths.py`) and
reversible by the user deleting one file.

**The uninstaller moves itself before deleting.** On Windows a running image
cannot be deleted, and a process cannot delete its own working directory. The
uninstaller therefore `os.replace`s its own executable into a fresh `%TEMP%`
folder and `chdir`s there, then deletes the install tree. This avoids spawning a
copy and waiting on a handle, which is the usual source of "uninstall leaves a
folder behind" bugs. The uninstaller also resolves its target path *before*
detaching, so a relative `--target` still works afterwards.

**`onefile` for the setup executable, `onedir` for the application.** The
installer runs once and can afford a few seconds of self-extraction; the
application starts many times a day and cannot. The payload is embedded with
`--add-data` and extracted from `sys._MEIPASS` at install time.

**The uninstaller's destructive answer is not the default.** The first version
used a plain Yes/No/Cancel message box, where Enter selects *Yes* — "remove the
app and delete settings and history". Testing caught it deleting a data folder
with no human present. The default button is now *No*, and a message box that
fails to appear (return value 0) is treated as a cancel instead of as consent.
Both cases are covered by tests.

**The uninstaller is built without Qt.** It only needs a `MessageBoxW` and some
file operations, so it is compiled with `--exclude-module PySide6`: 8 MB instead
of 40 MB, and no chance of a Qt import failure standing between the user and a
successful uninstall.

---

## 4. Tests executed and actual results

```
293 passed in 54.36s
```

Run with `.venv\Scripts\python.exe -m pytest -q`. Every filesystem test uses a
temporary directory; the real Downloads folder is never touched.

| Module | Tests | Covers |
| --- | --- | --- |
| `unit/test_classifier.py` | 39 | Extension mapping, compound suffixes, unknown → Other, case, leading dots, configurable lists |
| `unit/test_conflict_resolver.py` | 22 | `name (1)` sequence, illegal characters, reserved device names, trailing dots, length limits |
| `unit/test_fileops.py` | 18 | Same-volume rename, cross-volume copy/verify, permission denied, disk full, locked file, path too long, missing source |
| `unit/test_organizer.py` | 26 | Date folders, category folders, completion date, dedupe, no-overwrite, already-in-destination, zero-byte, temp suffixes, paused state, auto-organize off |
| `unit/test_database.py` | 14 | Schema creation, migration idempotence, transaction rollback, persistence across reopen, settings round-trip |
| `unit/test_undo.py` | 9 | Successful undo, missing organized file, missing original directory, conflict, cancel vs rename, unknown operation |
| `unit/test_download_manager.py` | 14 | Completed-only handling, ignored event kinds, pause/resume, manual organize |
| `unit/test_monitor.py` | 9 | Stability window, temp suffixes ignored, destination subtree ignored, forget/reset |
| `unit/test_i18n.py` | 8 | Catalogue key parity, RTL flag, formatting, no missing keys |
| `security/test_message_validation.py` | 36 | Schema allow-list, oversized messages, malformed JSON, bad extension IDs, path traversal, NUL bytes, device paths, relative paths |
| `security/test_path_safety.py` | 9 | Destination containment, `..` escape, symlink escape, absolute path requirement, protected system directories |
| `security/test_diagnostics_redaction.py` | 5 | `%USERPROFILE%` substitution in logs, JSON and the exported DB copy; the live DB is never modified; token ACL is user-only |
| `integration/test_native_messaging.py` | 16 | Framing round-trip, truncated frame, zero-length, oversized, real pipe connection, real host subprocess, app-not-running error, no pickle on the wire, connection cap |
| `integration/test_browser_flow.py` | 10 | Controller end-to-end with mocked browser events, settings changes, history queries, extension allow-list enforcement (omitted ID, wrong ID, registered ID) |
| `integration/test_ui_smoke.py` | 7 | Every window and page constructs, navigates and renders |
| `integration/test_cli.py` | 7 | `--version`, `--print-paths`, `--data-dir` regression, launcher resolution, `--scan` preview moves nothing, `--scan` without a destination fails clearly, registration pins the allow-list |
| `unit/test_folder_scanner.py` | 18 | Read-only scanning, temp/hidden/empty/in-destination/protected filters, recursive walk, newest-first order, preview matches the real move |
| `integration/test_scan_dialog.py` | 6 | Dialog population, pre-selection, filter, select-none, batch organize, idempotence |
| `unit/test_paths.py` | 4 | `portable.txt` marker switches the data folder, `%LOCALAPPDATA%` fallback, env override wins, a source checkout is never portable |
| `unit/test_release_scripts.py` | 13 | `/S` and `/D=` switch normalisation, uninstaller refuses shallow/foreign/system folders, installer rejects zip-slip payloads, `/S` keeps user data, `/PURGE` deletes it, a failed or cancelled dialog removes nothing, the version string is identical in all five places |
| `unit/test_startup_service.py` | 3 | The Run key command for a frozen build and for a source checkout, including the working directory and `pythonw.exe` preference |

### Packaged build verification

`scripts/verify_packaged.py` starts the **real** `SmartSort.exe`, drives the
**real** `smartsort-host.exe` over the **real** named pipe, and inspects the
result. Actual output of the final run:

```
1. starting the packaged application
   bridge is listening
2. asking the packaged native host for a ping
   response: {'ok': True, 'app': 'SmartSort', 'version': '1.0.0', 'ready': True,
              'paused': False, 'destination': '...\\SmartSortDest', 'protocolVersion': 1}
3. reporting a completed download through the host
   response: {'ok': True, 'status': 'organized', 'message': 'moved_by_rename',
              'finalPath': '...\\SmartSortDest\\2026-10-21\\Images\\holiday-photo.jpg',
              'category': 'images', 'operationId': 1}
   moved to: 2026-10-21\Images\holiday-photo.jpg
4. verifying the operation was persisted
   history row #1 recorded

PASS - packaged build works end to end
```

Registry round-trip, also executed against the packaged executable:

```
$ SmartSort.exe --register-host aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
registered chrome: HKCU\Software\Google\Chrome\NativeMessagingHosts\com.smartsort.host
registered edge:   HKCU\Software\Microsoft\Edge\NativeMessagingHosts\com.smartsort.host

$ SmartSort.exe --unregister-host
removed HKCU\Software\Google\Chrome\NativeMessagingHosts\com.smartsort.host
removed HKCU\Software\Microsoft\Edge\NativeMessagingHosts\com.smartsort.host
deleted ...\native-host\com.smartsort.host.json
```

### Release artifacts

`scripts/build_release.py` produces two files from the same `dist/SmartSort`
tree. Both were built and then executed, not merely produced.

**Portable zip.** Unzipped to a clean folder and run from there:

```
$ SmartSort.exe --print-paths
data_dir:   ...\portable-v2\SmartSort\data
logs_dir:   ...\portable-v2\SmartSort\data\logs
database:   ...\portable-v2\SmartSort\data\smartsort.db
manifest:   ...\portable-v2\SmartSort\data\native-host\com.smartsort.host.json
token:      ...\portable-v2\SmartSort\data\bridge.token
```

Running `--scan` afterwards created `data\smartsort.db`, `data\logs\` and
`data\bridge.token`, confirming that the marker moves *all* state and not just
the path reported by `--print-paths`.

**Installer.** `SmartSort-Setup-1.0.0.exe /S --no-shortcuts /D=<temp>` was
executed against a throwaway folder:

- exit code 0, 263 files extracted, including `uninstall.exe`.
- All ten `HKCU\...\Uninstall\SmartSort` values written and read back
  (DisplayName, DisplayVersion, Publisher, DisplayIcon, InstallLocation,
  UninstallString, QuietUninstallString, EstimatedSize, NoModify, NoRepair).
- The installed copy reports `%LOCALAPPDATA%\SmartSort` as its data folder —
  i.e. it is **not** portable, which is the intended difference between the two
  artifacts.
- `uninstall.exe /S` afterwards returned 0, deleted the folder, removed the
  registry entry and left `%LOCALAPPDATA%\SmartSort` in place. The data folder
  was verified separately with `LOCALAPPDATA` redirected to a temporary folder
  holding a `smartsort.db`: after `/S` the database was still there, after
  `/S /PURGE` it was gone.

**Uninstaller self-deletion.** It moves itself to `%TEMP%` with `os.replace`
before deleting, so the image file is not locked, and it `chdir`s out of the
target so the directory is not held as a working directory. Both were found the
hard way: the first build failed with `WinError 32` when the shell had started it
from inside the install folder.

### What is *not* proven

The extension has never been loaded into a real browser profile, and no real
download has been completed through it. That requires a human at a browser.
`docs/manual-acceptance.md` is the checklist for it. Every layer the extension
talks to — framing, validation, the pipe, the organizer, the database — is
covered by the tests above, but the browser-to-extension hop is not.

---

## 5. Remaining limitations

1. **The extension cannot redirect a download before it is saved.** A browser
   extension has no such API. SmartSort moves the file after the browser reports
   completion. This is a browser restriction, not an omission. If you want the
   browser to write directly into the destination, change the download location
   in the browser settings yourself; SmartSort will never change it for you.
2. **The browser shows "not connected" when idle.** MV3 service workers are
   suspended after ~30 s. The status pill means "the worker is awake right now",
   not "the extension is broken". Completed downloads are still reported when the
   worker wakes.
3. **The fallback watcher is a heuristic.** A download that stalls for longer
   than the settle window could be moved while still incomplete. The extension
   path does not have this weakness because it uses the browser's own completion
   event. Use the extension when you can.
4. **Undo is best effort.** If the original folder was deleted, the drive was
   removed, or the file was moved again by you, undo reports the problem rather
   than guessing. It never deletes the organized copy.
5. **Binaries are unsigned.** Windows SmartScreen warns on first run. Signing is
   described in `docs/installation.md`.
6. **One destination at a time.** Per-category destinations were not requested
   and are not implemented; categories choose a subfolder, not a drive.
7. **No cloud sync, no multi-user profiles, no archive extraction, no content
   inspection.** Deliberate: all four would require either network access or
   reading file contents, both of which conflict with the privacy requirement.

---

## 6. Build instructions

Prerequisites: Windows 10/11 64-bit, Python 3.10+ (3.13 used here).

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Then either the wrapper script:

```powershell
.\scripts\build_windows.ps1
```

or PyInstaller directly:

```powershell
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean smartsort.spec
Copy-Item browser_extension dist\SmartSort\browser_extension -Recurse
Copy-Item docs dist\SmartSort\docs -Recurse
```

`build_release.py` re-syncs `docs\`, `README.md`, `CHANGELOG.md` and `LICENSE`
into the build folder before packing, so the artifacts cannot ship stale
documentation. `-Clean` on the wrapper script removes `build\` and `dist\` first.
The build takes about 2–5 minutes and is not signed.

Verify the result:

```powershell
.venv\Scripts\python.exe scripts\verify_packaged.py
```

---

## 7. Launch instructions

**Packaged build:**

```powershell
.\dist\SmartSort\SmartSort.exe
```

**From source:**

```powershell
.\scripts\run_dev.ps1
```

Useful flags:

| Flag | Effect |
| --- | --- |
| `--minimized` | Start hidden in the tray |
| `--data-dir <path>` | Use a different data directory (works with the maintenance flags too) |
| `--version` | Print the version and exit |
| `--print-paths` | Print data, database, log and manifest locations |
| `--register-host <ID>` | Register the native host for one or more extension IDs |
| `--unregister-host` | Remove the native host registration |
| `--scan <folder>` | Preview what would happen to the files in a folder, then exit. Read-only. |
| `--scan-recursive` | Include subfolders when used with `--scan` |

First run: click **Change** on the Dashboard and pick a destination, leave
**Automatic organization** on, then optionally connect a browser.

---

## 8. Browser installation instructions

1. Open `chrome://extensions` or `edge://extensions` and enable **Developer
   mode**.
2. Choose **Load unpacked** and select the `browser_extension` folder — either
   `dist\SmartSort\browser_extension` from the packaged build, or the
   `browser_extension` folder in the repository. The app's **Open extension
   folder** button reveals the right one.
3. Copy the 32-character extension ID the browser assigns.
4. In SmartSort, open **About & diagnostics**, paste the ID into **Extension ID**,
   and click **Install browser integration**. Alternatively:

   ```powershell
   .\scripts\register_native_host.ps1 -ExtensionId <PASTE_ID_HERE>
   ```

5. Restart the browser, then open the extension popup. It should report
   **Connected**.
6. To remove it: press **Remove browser integration** in the app, or run
   `.\scripts\register_native_host.ps1 -Unregister`, then remove the extension
   from the browser.

The extension ID differs on every machine because the browser derives it from the
folder path, which is why it must be pasted rather than being built in.

---

## 9. Location of the packaged Windows build

```
<repository root>\dist\SmartSort\
```

```
SmartSort.exe            2.5 MB    desktop application (windowed)
smartsort-host.exe       2.3 MB    browser native messaging host (console)
browser_extension\                 Chrome/Edge extension, load unpacked
docs\                              documentation, readable without running the app
README.md  LICENSE  CHANGELOG.md
_internal\                         runtime, Qt libraries, bundled copies of the above
```

Total 120 MB. Portable: no installation, no administrator rights, no
`Program Files` writes. Delete the folder to remove it. Application data lives
in `%LOCALAPPDATA%\SmartSort\` and is removed by
`.\scripts\uninstall_windows.ps1 -PurgeData`.

---

## 10. Addendum — scanning files that are already downloaded

Added after the initial report, in response to: *"doesn't it have a way to
search the Downloads folder?"* It did not. Automatic organization only sees
downloads that complete while the app is running; anything downloaded before
that was invisible to it.

**What was added**

- `smartsort/app/core/folder_scanner.py` — `FolderScanner` enumerates a folder
  (optionally recursive), classifies each file, and previews its target. It is
  strictly read-only: no move, no rename, no history row. Files that cannot be
  moved are reported with a stable reason code rather than being silently
  dropped.
- `Organizer.preview()` — returns the target path a file *would* get. It shares
  `_plan()` with the real move, so the preview cannot drift from what
  `organize()` actually does. There is a test asserting exactly that.
- `DownloadManager.organize_manually(path, completed_at)` — now accepts the
  file's own timestamp, so a file downloaded in March lands in the March
  folder instead of today's.
- `AppController.scan_folder()` / `organize_scanned()` — batch organization that
  goes through the normal organizer, so dedupe, conflict naming, history and
  undo apply unchanged. One failure never aborts the batch.
- `smartsort/app/ui/scan_dialog.py` — folder picker, live filter over name and
  category, preview table, select all/none, explicit confirmation showing the
  count and destination, then a result summary. Scanning and moving both run on
  the background worker, so a folder with thousands of files cannot freeze the
  window.
- Dashboard entry point plus a screenshot (`docs/screens/06-scan.png`).

**Deliberate design choices**

- **Read-only until confirmed.** The dialog never moves anything on open or on
  scan. This matters because the target folder is the user's own Downloads.
- **No lock probe during a scan.** Asking "is this file open?" means attempting
  a rename. That would make a scan a write operation and can false-positive on
  read-only files, so it is not done. A file genuinely held open fails later
  with a clear error and keeps its source intact.
- **The date comes from the file's mtime.** There is no browser event for a file
  that was downloaded last week, so its own modified time is the only honest
  signal. The preview shows the resulting folder, so nothing is a surprise.
- **Skips are explained, not hidden.** Greyed row, no checkbox, reason in the
  destination column.
- **Bounded.** A scan stops at 5000 entries and says so, rather than hanging on a
  folder with a hundred thousand files.

**Tests added:** 17 unit (`test_folder_scanner.py`) and 6 integration
(`test_scan_dialog.py`), covering the filters, the recursive walk, newest-first
ordering, that scanning moves nothing and writes no history, that the preview
matches the real move, that a batch records history, and that running the same
batch twice does not duplicate anything.

---

## 11. Review pass before the public release

The whole tree was re-checked before publishing: every module compiled, the
package linted, every relative link in the documentation resolved, the version
string compared across five files, the extension's JavaScript syntax-checked, and
the packaged build run end to end again. What that turned up:

| Finding | Severity | Action |
| --- | --- | --- |
| `command_for_current_install()` wrote a Run value of `"<python> -m smartsort.app.main"`. A Run value has no working directory, so for a source checkout the import failed and "start with Windows" silently did nothing at the next sign-in. | **real bug** | The command now runs `cmd /c cd /d "<root>" && "<pythonw>" -m smartsort.app.main --minimized`, and prefers `pythonw.exe` so no console window flashes. 3 tests. |
| `MAX_EXTENSION_LENGTH = 24` was imported but never used, while the extension ID check hard-coded `{32}` — the constant was both dead and wrong. | misleading | Replaced with `EXTENSION_ID_LENGTH = 32`, now used to build the regex. |
| `verify_packaged.py` reported "the bridge never started" when another SmartSort instance held the single-instance lock — which is exactly what happened during this review, and cost a false alarm. | misleading | On failure it now counts running instances and says which of the two it is. |
| Unused imports in `fileops.py`, `organizer.py`, `native_host.py`, `installer_app.py`; a dead `stamp` variable in `capture_screens.py`; `subprocess.run` without an explicit `check`. | cosmetic | Removed / made explicit. |
| The version string was duplicated in five places with nothing tying them together. | risk | `test_the_version_is_the_same_everywhere` now fails if `pyproject.toml`, `defaults.py`, `installer_app.py`, `uninstall_app.py` or `build_release.py` drift apart. |
| The bundled folder had `browser_extension\` and `docs\` only under `_internal\`, so an unzipped portable copy looked like two executables and an opaque directory. | packaging | `build_windows.ps1` now copies `browser_extension\`, `docs\`, `README.md`, `LICENSE` and `CHANGELOG.md` next to the executable; the spec bundles them too. |

Two things were **not** changed, deliberately: the broad `except Exception` in
the tray and shutdown paths (a crash there is worse than a swallowed log line,
and each one is on a path that already logs), and the `collections.abc` import
style (stylistic only, and the code targets 3.10+ where both work).

