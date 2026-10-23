# Troubleshooting

Start with **About & diagnostics → Export diagnostics**. That produces a zip with
the log, the settings snapshot, database health and browser registration status.
Nothing in it is uploaded anywhere.

---

## The app does not start

**"Windows protected your PC"** — expected for an unsigned build. More info →
Run anyway. See [installation.md](installation.md#e-code-signing).

**Nothing happens when I double-click the exe** — SmartSort may already be
running and hiding in the notification area. Check the tray; double-click the
icon to restore. Only one instance is allowed.

**It starts then disappears** — read
`%LOCALAPPDATA%\SmartSort\logs\smartsort.log`. Startup failures are logged with a
traceback. Common causes:

| Log line | Cause |
|---|---|
| `cannot open database` | The data folder is read-only or on a disconnected drive. |
| `cannot listen on \\.\pipe\smartsort-bridge-v2` | Another SmartSort instance owns the pipe. |
| `ImportError: DLL load failed` | A broken PySide6 install. Reinstall: `pip install --force-reinstall PySide6`. |

---

## Nothing is being organized

Work through this list in order — each item is a distinct gate in the pipeline.

1. **Is a destination set?** Dashboard should show a path, not
   *No destination selected*. If not, press **Change**.
2. **Is the app paused?** The dashboard pill says **Paused**. Press **Resume**.
3. **Is automatic organization on?** Settings → *Organize completed downloads
   automatically*.
4. **Did the download actually finish?** Files ending in `.crdownload`, `.part`,
   `.partial`, `.tmp` are never touched. A download paused at 99 % is still
   downloading.
5. **Is the file still open?** SmartSort renames a file to test whether the
   browser has released it. A file still held open is retried on the next scan.
6. **Is the file already in the destination?** Files inside the managed folder
   are skipped on purpose (this is what prevents recursive organization).
7. **Is the file empty?** Zero-byte files are skipped.
8. **Did it already get handled?** Open **History** and search for the name. A
   second event for the same download shows as *Already handled*.

---

## History says "Skipped" with a reason

| Reason | Meaning |
|---|---|
| `auto_organize_disabled` | The automation switch is off. |
| `paused` | The pause button is active (also pauses the watcher). |
| `policy_disallows_move` | *Move files the browser saved to its default folder* is off. |
| `file_still_downloading` | The name ends with a temporary suffix. |
| `already_in_destination` | The file is already inside the managed folder. |
| `empty_file` | Size is 0 bytes. |
| `browser_reports_missing_file` | The browser said the file no longer exists. |

## History says "Failed"

| Reason | Meaning and fix |
|---|---|
| `source_missing` | The file was moved or deleted between detection and the move. Harmless. |
| `permission_denied` | Antivirus, another program, or a read-only destination. The source file is untouched. Close the program holding it, or pick a writable destination. |
| `disk_full` | The destination drive is full. The temporary file is removed and the source is kept. |
| `destination_unavailable` | The drive is disconnected or the path is not a directory. |
| `destination_not_configured` | No destination selected. |
| `copy_incomplete` | The copy was shorter than the source (usually the drive was removed mid-copy). The source is kept. |
| `conflict_exhausted` | More than 2000 files with the same name. Rename the source. |
| `io_error` | Anything else; the message contains the OS error. |

---

## Browser shows "Not installed" / "Disconnected"

The popup's message tells you which stage failed.

### "Not installed"

The registry entry or the manifest is missing.

```powershell
# 1. Confirm the registry entry exists (HKCU, no admin needed)
Get-ItemProperty "HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.smartsort.host"

# 2. Confirm the manifest exists and the path inside it is correct
Get-Content "$env:LOCALAPPDATA\SmartSort\native-host\com.smartsort.host.json"
```

- If the key is missing, re-run
  `.\scripts\register_native_host.ps1 -ExtensionId <ID>`.
- If the key exists but the `path` in the manifest does not exist, the build was
  moved. Re-run the registration from the new location.
- Restart the browser afterwards. Registrations are read at startup.

### "App not running"

The desktop app is not running, or its bridge could not start. Start
SmartSort, then press **Test connection** in the popup.

If the app *is* running, check the log for
`bridge could not start` — usually a second instance holding the pipe.

### "Not allowed"

The extension ID is not in the manifest's `allowed_origins`. This happens when:

- you loaded the extension in Edge but only registered the Chrome ID, or
- the extension was removed and re-added (the ID changes for unpacked
  extensions if the folder moved), or
- the ID was pasted with a typo.

Re-register with the current ID, then restart the browser.

### "Error"

Chrome started the host but it exited immediately. Run the host by hand to see
why:

```powershell
cd dist\SmartSort
.\smartsort-host.exe --help
```

Then read `%LOCALAPPDATA%\SmartSort\logs\smartsort.log` (the host logs there, not
to stdout, because stdout is the protocol channel).

### The popup says Connected but downloads are not moved

1. Check **History** — the operation is probably there with a reason.
2. Confirm the destination is set.
3. Confirm the download's file still exists where the browser reported it. If
   the browser was configured to delete downloads after completion, there is
   nothing to move.

---

## Duplicate or missing entries in History

- **Duplicates** should not happen: both the download ID and the source path are
  recorded. If you see the same file moved twice, the file was downloaded twice
  (different download IDs) — that is correct behaviour.
- **Missing entries** happen when the browser never reported the download and
  the fallback watcher is off. Enable **Fallback folder monitoring** in Settings
  and point it at the browser's download folder.

---

## Undo does not work

| Message | Meaning |
|---|---|
| `organized_file_missing` | The file was moved or deleted after SmartSort organized it. |
| `original_directory_missing` | The folder it came from (often `Downloads`) no longer exists. Recreate it, then undo again. |
| `target_exists` | A new file with the same name is there. Confirm the dialog to restore with a numbered name. |
| `operation_not_undoable` | Already undone, or the move failed in the first place. |

Undo never deletes the organized file to work around a problem.

---

## The fallback watcher moves files too early

Increase **Wait until a file stops changing** in Settings (default 3 s). For
slow connections or network drives, 10–20 s is reasonable. Also increase
**Check every** if you have thousands of files in the folder.

If a browser writes into a temporary name and then renames it, the watcher sees
only the final name — that is the correct behaviour and needs no tuning.

---

## High CPU or disk usage

- The watcher polls every 2 s by default. On a folder with tens of thousands of
  files, raise **Check every** to 10 s.
- The dashboard refreshes every 10 s and on every event; it is not a poller.
- A large cross-volume copy is I/O bound and expected to use the disk.

---

## Resetting everything

1. **Back up first**: About → **Back up settings & history**.
2. Quit SmartSort from the tray.
3. Rename `%LOCALAPPDATA%\SmartSort` to `SmartSort.old`.
4. Start SmartSort. A fresh database is created.
5. If you want the history back, replace the new `smartsort.db` with the backup.

---

## Reporting a problem

Include:

- the diagnostics zip,
- the exact status text from History for the affected file,
- whether the browser popup said Connected at the time,
- your Windows version (`winver`).

Never include the files themselves.
