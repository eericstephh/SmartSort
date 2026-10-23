# Architecture

This document explains how SmartSort is put together, why the boundaries are
where they are, and which trade-offs were made deliberately.

---

## 1. Component map

```
                 ┌──────────────────────────────┐
   Chrome / Edge │  browser_extension/ (MV3)    │
                 │  downloads API → JSON events │
                 └──────────────┬───────────────┘
                                │ 4-byte length + UTF-8 JSON (stdin/stdout)
                 ┌──────────────▼───────────────┐
                 │  smartsort-host.exe          │  spawned per message by the browser
                 │  browser/native_host.py      │
                 └──────────────┬───────────────┘
                                │ named pipe + HMAC handshake
                 ┌──────────────▼───────────────┐
                 │  BridgeServer (app thread)   │
                 │  browser/bridge_server.py    │
                 └──────────────┬───────────────┘
                                │ validate → dispatch
                 ┌──────────────▼───────────────┐
                 │  AppController (Qt)          │  ui/controller.py
                 └───┬───────────────┬──────────┘
                     │               │
        ┌────────────▼───┐   ┌───────▼────────────┐
        │ DownloadManager│   │ UndoManager        │
        │ (policy)       │   │ (reverse moves)    │
        └────────┬───────┘   └───────┬────────────┘
                 │                   │
        ┌────────▼───────────────────▼────────────┐
        │ Organizer  →  Classifier                │  core/
        │            →  ConflictResolver          │
        │            →  fileops.safe_move         │
        └────────────────┬────────────────────────┘
                         │
        ┌────────────────▼────────────────────────┐
        │ Repositories → SQLite (WAL)             │  storage/
        └─────────────────────────────────────────┘

        Fallback path (no extension):
        DownloadFolderWatcher ──► DownloadManager.handle_watched_file
```

### Layer rules

| Layer | May import | Must not import |
|---|---|---|
| `core/` | `storage/`, `config/` | Qt, `browser/`, `ui/` |
| `storage/` | stdlib, `config/defaults` | Qt, `core/`, `ui/` |
| `browser/` | stdlib, `config/` | Qt (the host runs without it), `ui/` |
| `services/` | stdlib, `core/`, `config/` | Qt |
| `ui/` | everything | — |

`core/` being Qt-free is what makes the test suite fast and lets the organizer
be exercised without an event loop.

---

## 2. Download detection

Two independent sources feed the same pipeline:

1. **Browser events** (primary). The extension listens to
   `chrome.downloads.onCreated` and `onChanged`, and forwards a message only
   when a download reaches `complete` (or `interrupted` / `cancelled`, which are
   recorded and ignored).
2. **Folder watching** (fallback). `DownloadFolderWatcher` polls a directory and
   reports a file when its size has not changed for `watch_settle_seconds` and
   the file is not held open by another process.

### Why polling instead of `ReadDirectoryChangesW`/watchdog

- Identical behaviour on local disks, USB drives and SMB shares (change
  notifications are unreliable or absent on the last two).
- No extra dependency.
- "Is this file still being written?" becomes an explicit, testable predicate
  instead of a race between a notification and the browser's flush.

The cost is latency (default 2 s) and a tiny amount of I/O, which is irrelevant
for a downloads folder.

### Deduplication

Both sources can report the same file. `Organizer` writes two keys into
`processed_items` after a successful move:

- `dl:<browser>:<download id>` — from the extension.
- `path:<sha256 of the normalised source path>` — from either source.

Either key short-circuits the next attempt with `duplicate`, so a browser event
that arrives after the watcher already moved the file (or vice versa) is a
no-op, not a second move. Because the path key is written for browser events
too, the watcher never re-organizes a file the extension reported.

### Why `sendNativeMessage` and not a long-lived port

MV3 service workers are suspended after ~30 s of inactivity, which tears down
open native ports and produces a permanently "disconnected" extension. One-shot
messages are stateless and always work; the price is starting the host process
per message (~1 s), which is irrelevant for download-frequency events.

### Why a named pipe with an HMAC handshake

The desktop app must not open a TCP listener (that would be reachable by other
processes and, with a bad firewall rule, by the network). A Windows named pipe
is local-only, and `multiprocessing.connection` adds a challenge/response
handshake keyed with a 32-byte token stored in the user's profile. A process
that cannot read the token cannot send a single byte.

The primary authorisation boundary is still the registry: Chrome/Edge only
launch a native host for extension IDs listed in the manifest's
`allowed_origins`, and SmartSort writes that list itself.

---

## 3. Organization pipeline

```
OrganizeRequest
   │
   ├─ policy gate ......... auto-organize on? paused? move allowed?
   ├─ destination gate .... configured? exists? not the source folder?
   ├─ dedupe gate ......... download key / path key already processed?
   ├─ source gate ......... exists? regular file? non-zero? not a temp suffix?
   ├─ plan ................ date folder (completion time) + category folder
   ├─ conflict resolution . photo.jpg → photo (1).jpg → photo (2).jpg …
   ├─ safe move ........... rename (same volume) or copy→verify→rename→unlink
   └─ record .............. operations row + processed_items keys
```

Every gate returns a typed status (`organized`, `skipped`, `duplicate`,
`failed`) with a machine-readable reason. The UI translates the reason; the
database stores it verbatim, which makes support questions answerable.

### The completion date, not the file date

The date folder comes from the download's completion timestamp reported by the
browser. When there is none (fallback watcher, manual run) the local clock is
used. Timestamps arriving as UTC are converted to local time before the date is
derived, so a download that finished at 23:30 UTC lands in the folder for the
local calendar day.

### No-overwrite guarantee

`os.rename` on Windows fails with `FileExistsError` when the target exists — it
does not overwrite. `safe_move` relies on exactly that:

- **Same volume:** try candidate names in order until `os.rename` succeeds.
- **Cross volume:** create the temporary file with `"xb"` (exclusive create),
  copy, `fsync`, compare byte counts, `copystat`, then `os.rename` the temporary
  file onto a candidate name (same volume as the destination, therefore atomic),
  and only then unlink the source.

There is no code path that opens an existing destination file for writing.

### Failure containment

| Failure | Behaviour |
|---|---|
| Source missing | `failed: source_missing`, no folders created |
| Permission denied / file locked | `failed: permission_denied`, source untouched |
| Disk full | `failed: disk_full`, temporary file removed, source untouched |
| Copy shorter than source | `failed: copy_incomplete`, temporary file removed |
| Source cannot be deleted after a verified copy | move **succeeds** with a warning; the destination copy is kept and the source remains |
| Name space exhausted (2000 candidates) | `failed: conflict_exhausted` |

A failed move is still written to the history with the error, so the user can
see what happened instead of wondering where a file went.

---

## 4. Database schema

SQLite, WAL mode, `PRAGMA user_version` for migrations.

```sql
settings(key PK, value JSON, updated_at)
categories(id PK, name, enabled, extensions CSV, sort_order, builtin)
operations(id PK, download_id, origin, category,
           original_path, final_path, size_bytes,
           completed_at, organized_at, status,
           error, message, undo_state, undo_at)
processed_items(key PK, kind, download_id, browser,
                source_path, final_path, processed_at, operation_id)
```

- One connection, guarded by an `RLock`, `check_same_thread=False`. Writes are
  a few rows per file, so a pool would add complexity without benefit.
- Explicit `BEGIN IMMEDIATE` transactions; migrations run inside one.
- `operations` is append-only except for the undo columns, which is what makes
  the audit trail trustworthy.
- `processed_items` is the dedupe ledger and can be pruned independently.

Migration 1 creates everything. Future migrations are appended to
`MIGRATIONS` in `storage/migrations.py` and applied in order.

---

## 5. Undo

Undo reads `original_path` and `final_path` from the operation row and performs
the reverse move with the same no-overwrite primitive.

Preconditions, checked in order:

1. The operation exists and is `organized`.
2. The organized file still exists.
3. The original directory still exists.
4. The original path is free — otherwise the UI asks the user, and `on_conflict="rename"`
   restores as `photo (1).jpg`.

Undo never deletes the organized copy to resolve a failure. If the original
folder is gone, the operation fails with `original_directory_missing` and the
file stays where it is.

After a successful undo the operation becomes `undone` and the dedupe keys are
**kept**, so the fallback watcher does not immediately re-organize a file the
user just pulled back into the downloads folder.

---

## 6. Security model

| Threat | Mitigation |
|---|---|
| Malicious extension sends arbitrary commands | Message types are an allow-list; nothing is ever `eval`'d or executed. |
| Path traversal (`..\..\Windows`) | Rejected at validation (`path_traversal`) *and* neutralised again by `sanitize_filename` before use. |
| Device paths (`\\?\`, `\\.\`) | Rejected. |
| Oversized message / memory exhaustion | 1 MiB frame limit enforced before allocation; field length caps. |
| Rogue local process talks to the app | Named pipe + HMAC handshake with a per-user token. |
| Rogue extension ID | Registry `allowed_origins` written by the app + optional in-app allow-list check. |
| Shell injection through filenames | No subprocess is ever spawned with file data. |
| Silent data loss | No-overwrite rename, copy-verify-delete, source preserved on every failure path. |
| Downloaded file execution | SmartSort never opens, executes or extracts anything. |

Network access: none. The application has no HTTP client, no update checker and
no telemetry.

---

## 7. Threading model

| Thread | Work |
|---|---|
| Qt main thread | All widgets, signals, dialogs |
| `smartsort-bridge` (+ one per connection) | Native messaging dispatch |
| `smartsort-watcher` | Polling loop |
| `smartsort-worker` | `TaskRunner` queue: undo, long operations |
| Qt worker pool | `QFileDialog` internals |

Cross-thread communication is via Qt signals (auto → queued) and the SQLite
`RLock`. `Organizer` serialises the "find a free name and rename" window with a
lock, but correctness comes from the OS-level rename, not the lock — a second
process doing the same thing still cannot overwrite.

---

## 8. Trade-offs made

1. **Polling over filesystem events.** Predictable on network shares, testable,
   dependency-free. Costs latency.
2. **`sendNativeMessage` over a persistent port.** Survives MV3 suspension;
   costs ~1 s per message.
3. **One SQLite connection.** Simpler and faster than a pool at this write
   volume; the lock is held for microseconds.
4. **No ORM.** Repositories are the only SQL; ~200 lines, fully visible.
5. **Category from extension only.** No content sniffing in v1 — it is
   deterministic, fast and privacy-preserving. A file named `.jpg` that is
   actually a ZIP stays in `Images`; the UI says so.
6. **English + Persian dictionaries instead of `.ts`/`.qm`.** No `lrelease`
   step in the build, and the catalogue is readable in a diff.

---

## 9. Acceptance criteria mapping

| # | Criterion | Where it is verified |
|---|---|---|
| 1 | App launches | `tests/integration/test_ui_smoke.py`, `SmartSort.exe --version` |
| 2 | Destination on another drive | `settings.destination_dir` is any absolute path; cross-volume path in `test_fileops.py` |
| 3 | Local classification | `tests/unit/test_classifier.py` |
| 4 | Date + category folders | `test_organizer.py::test_creates_date_and_category_folders` |
| 5 | Only completed downloads | `test_download_manager.py::test_unfinished_downloads_are_never_moved` |
| 6 | Never overwrites | `test_fileops.py::test_safe_move_never_overwrites`, `test_organizer.py::test_conflict_creates_numbered_copy` |
| 7 | Failures preserve the source | `test_fileops.py` disk-full / permission tests |
| 8 | History survives restart | `test_database.py::test_operations_survive_restart` |
| 9 | Undo works | `tests/unit/test_undo.py` |
| 10 | Messages validated | `tests/security/test_message_validation.py` |
| 11 | Integration install/remove | `register_native_host.ps1`, `--register-host` / `--unregister-host` |
| 12 | No paid API or cloud | no network code exists |
| 13 | Tests pass | 230 tests, all green |
| 14 | Docs | `docs/` |
| 15 | Packaged build tested | `scripts/build_windows.ps1` smoke test |
