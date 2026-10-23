# Privacy

SmartSort is designed so that your file names never leave your computer.

---

## Summary

| Question | Answer |
|---|---|
| Does SmartSort have telemetry? | No. There is no analytics, crash reporting or usage counting code. |
| Does it need an account? | No. |
| Does it use a cloud service or paid API? | No. |
| Does it send file names or contents anywhere? | No. |
| Can it work offline? | Yes — permanently. Nothing degrades without a network. |
| Does it read the contents of my files? | No. It reads names, sizes and timestamps only. |
| Does it execute or open downloads? | No. Never. |
| Does it extract archives? | No. |

---

## What is stored locally

Everything lives under `%LOCALAPPDATA%\SmartSort` (per-user, not machine-wide):

| Data | Purpose | Where |
|---|---|---|
| Destination folder, toggles, language, theme | Settings | `smartsort.db` (`settings` table) |
| Extension allow-list | Security | `smartsort.db` |
| Original and final paths of every move | History + Undo | `smartsort.db` (`operations` table) |
| Download IDs already handled | Deduplication | `smartsort.db` (`processed_items`) |
| Browser/extension IDs | Native messaging registration | `native-host\com.smartsort.host.json` |
| Bridge token | Authenticates the browser host to the app | `bridge.token` |
| Log | Troubleshooting | `logs\smartsort.log` (rotated at 2 MB, 3 files) |

**No credentials are stored** because none exist. There is no password, token or
API key anywhere in the product.

### File paths in the history

The history necessarily contains paths, because Undo cannot work without them.
It stays in a local SQLite file readable only by your Windows user account. If
you want to remove it:

- **Settings-free option:** delete `%LOCALAPPDATA%\SmartSort\smartsort.db` while
  SmartSort is closed.
- **Selective option:** set `history_retention_days` in the database (or leave
  the default of 0 = keep forever).

---

## What leaves the computer

Nothing. There is no HTTP client in the codebase, no update checker, no crash
uploader and no licence check.

The only inter-process communication is local:

```
browser extension ──stdin/stdout──► smartsort-host.exe ──named pipe──► SmartSort.exe
```

A Windows named pipe is not a network socket. It cannot be reached from another
machine.

---

## Permissions requested

### The desktop app

- **Filesystem:** read/write inside the destination folder and the folders it
  monitors. No elevation, no `Program Files`, no system directories.
- **Registry (HKCU only):**
  - `Software\Google\Chrome\NativeMessagingHosts\com.smartsort.host`
  - `Software\Microsoft\Edge\NativeMessagingHosts\com.smartsort.host`
  - `Software\Microsoft\Windows\CurrentVersion\Run` → `SmartSort` (only if you
    enable *Start with Windows*)
- **No** firewall rule, **no** service, **no** scheduled task, **no** admin
  rights, **no** security-setting changes.

### The browser extension

| Permission | Why it is needed | What it is *not* used for |
|---|---|---|
| `downloads` | Observe `onCreated` / `onChanged` to know when a download finished and where it was saved. | It never deletes, pauses or re-downloads anything. |
| `nativeMessaging` | Talk to the desktop app. | — |
| `storage` | Keep the last 5 events for the popup. | No sync, no cloud. |
| `alarms` | A 5-minute heartbeat so the app can show connection status. | — |

The extension has **no** host permissions. It cannot read page content, cannot
inject scripts and cannot see your browsing history.

---

## Diagnostics export

**About → Export diagnostics** creates a zip on your disk containing the log, a
settings snapshot, database health and browser registration status. It is
created only when you ask for it and is never uploaded.

It may contain file paths from your machine. Review it before sharing it with
anyone.

---

## Data deletion

| To delete | Do this |
|---|---|
| History and settings | `.\scripts\uninstall_windows.ps1 -PurgeData` (or delete `%LOCALAPPDATA%\SmartSort`) |
| Browser integration | `.\scripts\register_native_host.ps1 -Unregister` |
| The app itself | Delete `dist\SmartSort` |
| Organized files | Delete them yourself; SmartSort has no delete feature |

---

## Children and sensitive data

SmartSort has no user-generated content, no messaging and no network features.
It processes file names only, and does not distinguish between kinds of files.

---

## Third-party components

| Component | License | Purpose |
|---|---|---|
| PySide6 / Qt 6 | LGPL-3.0 | Desktop UI toolkit |
| Python 3.10+ | PSF | Runtime |
| PyInstaller | GPL-2.0 + exception | Packaging (build-time only) |
| pytest, pytest-qt | MIT | Tests (development only) |

There is no analytics SDK, no crash reporter and no advertising library.

Under the LGPL you may replace the Qt libraries shipped in `dist\SmartSort` with
your own compatible build; no SmartSort source changes are required.

---

## Contact

This is an open-source project; privacy questions belong in the issue tracker.
There is no data controller because no data is collected.
