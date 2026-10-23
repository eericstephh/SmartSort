# Security model

This document states what SmartSort enforces, how it was verified, and what it
does **not** protect against. It is written to be checked against the code, not
taken on trust: every claim names the file that implements it.

Revision note: this file was rewritten after a hardening pass that closed six
issues found in the first audit — pickle on the bridge wire, an unbounded
connection count, a no-op token ACL, an allow-list that could be bypassed, a
registration path that left it empty, and diagnostics that exposed the account
name. The fixes are in §6, §7, §8 and §9.4. What is still not fixed is in §9.

## 1. Threat model

**Untrusted input.** Everything arriving from a browser extension is treated as
hostile: message type, download id, filename, path, URL, MIME type, timestamps,
byte counts. A filename is a string an attacker can choose — a page can trigger
a download named `..\..\..\Windows\System32\evil.dll` if it wants to.

**Trusted.** The local user, the local filesystem, and the SmartSort data
directory (`%LOCALAPPDATA%\SmartSort`). If an attacker already runs code as this
user, they have the user's own file permissions and SmartSort cannot raise that
barrier — see §9.1.

**Out of scope.** A compromised browser profile, malware running as the same
user, physical access, and a malicious Windows kernel.

## 2. No network access

Verified by search, not by assertion — the entire `smartsort/` package and the
extension contain **zero** network primitives:

```
grep -rn "import socket|import urllib|import requests|from http|urlopen|
         webbrowser|smtplib|ftplib|telnet" smartsort/ browser_extension/   → no matches
grep -n "fetch(|XMLHttpRequest|WebSocket|https?://" browser_extension/*.js  → no matches
```

There is no telemetry, no update check, no crash reporting, no account, no
license server. The app is fully functional offline after installation. The only
IPC is a Windows named pipe on the local machine (§6).

The extension requests exactly four permissions — `downloads`, `nativeMessaging`,
`storage`, `alarms` — and no host permissions, so it cannot read page content on
any site.

## 3. Untrusted input pipeline

A browser message passes four independent gates before a file can move:

| Gate | File | What it does |
| --- | --- | --- |
| 1. Framing | `browser/protocol.py` | Rejects zero-length frames, frames over 1 MiB, invalid JSON, and non-object payloads |
| 2. Schema | `browser/message_validation.py` | Type, length and range check on every field; unknown message types rejected against an allow-list |
| 3. Authorisation | `ui/controller.py` | Extension-ID allow-list (§7) |
| 4. Policy | `core/organizer.py` | Source must exist, be a regular file, be non-zero, not be temporary, not be inside the destination, not be in a protected system directory (§8) |

`validate_message` returns a **normalised** dict rather than the caller's object,
so unvalidated fields cannot leak downstream by accident.

## 4. Path safety

Two independent layers, because one is not enough:

**Layer 1 — reject bad input.** `validate_path()` refuses NUL bytes, paths over
the length limit, `\\?\` and `\\.\` device paths, relative paths, and any path
containing a `..` segment. Traversal is checked *before* `ntpath.normpath()`,
because normalisation would silently collapse `C:\a\..\..\b` into something
harmless-looking and hide the attempt.

**Layer 2 — never trust the name.** `sanitize_filename()` in
`core/conflict_resolver.py` reduces whatever arrives to a bare filename: it strips
directory components, illegal characters, control characters, trailing dots and
spaces, and escapes reserved device names (`CON`, `NUL`, `COM1`, …) by
prefixing an underscore. A name that survives layer 1 but is still hostile
cannot escape the target directory through layer 2.

**Containment check.** `is_within()` resolves both paths and uses
`relative_to()`, so a symlink pointing into the destination is recognised as
already-organised and skipped (`tests/security/test_path_safety.py`).

## 5. Nothing downloaded is executed

```
grep -rn "\beval(|\bexec(|pickle|shell=True|os\.system|__import__" smartsort/
```

The only `exec` matches are `QDialog.exec()` and `QApplication.exec()` — Qt event
loops, not code evaluation. No `pickle` load path exists (§6), no shell is ever
used, and no dynamic import takes an untrusted string.

`os.startfile` appears twice (`ui/controller.py:open_path`,
`browser/registry.py:reveal_in_explorer`). Every call site passes a **directory**
— the destination, the log folder, the data folder, the extension folder, or
`Path(organized_file).parent` — so Explorer opens a folder. No downloaded file
is ever launched. Archives are never extracted and downloads are never inspected.

**One subprocess exists, and it is deliberate.** `browser/bridge_server.py`
calls `icacls` to set the token file's ACL (§6.4). It runs a fixed Windows system
binary with a fixed argument vector, no shell, no string interpolation of
untrusted data, a 10-second timeout and `CREATE_NO_WINDOW`. If it fails, the
token keeps the ACL it inherited and the app logs a debug line — not fatal.

## 6. The bridge

The browser cannot reach the app directly. Chrome spawns `smartsort-host.exe`
over stdin/stdout (native messaging), and that host connects to the app over a
Windows named pipe, `\\.\pipe\smartsort-bridge-v2`.

`multiprocessing.connection` implements an HMAC challenge/response handshake on
that pipe. The shared key is 32 random bytes from `secrets.token_hex`, stored in
`%LOCALAPPDATA%\SmartSort\bridge.token`. A process that does not know the token
cannot send a single message — the listener raises `AuthenticationError` and the
connection is dropped (`tests/integration/test_native_messaging.py::
test_bridge_rejects_a_wrong_token`).

There is deliberately **no TCP listener**. Nothing binds a port, so nothing is
reachable from another machine, from another container, or through the Windows
firewall.

Four properties were added in this pass because the first audit found them
missing:

**6.1 No pickle on the wire.** `Connection.send()` / `recv()` serialise with
pickle, and `pickle.loads` on attacker-controlled bytes is remote code
execution. The bridge now uses only `send_bytes` / `recv_bytes` and parses JSON
on top (`send_payload` / `recv_payload`). The authenticated handshake is
unchanged. `test_bridge_never_unpickles_a_client_payload` sends a pickled object
and asserts the handler is never called.

**6.2 Hard size cap.** `recv_bytes(MAX_BRIDGE_BYTES)` fails on anything over
2 MiB *before* decoding, so a hostile client cannot make the app allocate an
unbounded buffer.

**6.3 Bounded concurrency.** `BridgeServer` had a `max_connections` argument it
never enforced, and its connection counter only ever incremented. Both are fixed:
the accept loop refuses connections past the limit and the counter now reflects
live connections (`test_bridge_refuses_connections_beyond_the_limit`). Handler
exceptions are logged locally and reported to the client as a bare
`internal_error` — the exception text is no longer sent back.

**6.4 The token has a real ACL.** `os.chmod` only toggles the read-only attribute
on Windows, so the old code changed nothing. The token is now written to a
temporary file, given an explicit DACL by `icacls` (`/inheritance:r` plus a grant
for the current account only), read back to prove it is still readable, and only
then renamed into place. A botched ACL therefore cannot lock the app out of its
own token. Verified on this machine: the file's ACL is a single ACE for the
current user, with `BUILTIN\Users` and `Everyone` absent
(`test_bridge_token_is_readable_only_by_the_current_user`).

## 7. Extension allow-list

Two layers, and both must be configured for the list to mean anything.

**Registry layer.** The native-messaging manifest restricts *who may spawn the
host* via `allowed_origins`, generated from the extension IDs you register
(`browser/registry.py:build_manifest`).

**App layer.** The controller rejects any message whose extension ID is not in
`allowed_extension_ids`. Two bugs were found and fixed here:

1. The check read `if extension_id and allowed and extension_id not in allowed`,
   so a message that simply omitted `extensionId` skipped it. The list was
   advisory. It is now enforced whenever it is configured — a missing ID is
   rejected like any other mismatch.
2. `--register-host` wrote the registry key but never pinned the IDs, leaving
   the app-side list empty. `_pin_extension_ids()` now records them in the same
   step, so the two cannot drift apart.

With no allow-list configured the app still accepts any extension, because that
is the state before an ID is pinned. `AppController._warn_if_unbound()` logs a
warning when the host is registered but no ID is pinned, so the state is visible
rather than silent. Three regression tests cover the rejection paths and one
covers the pinning.

## 8. Protected system locations

A browser message can name any path. `is_protected_location()`
(`core/fileops.py`) refuses sources inside `%SystemRoot%`, `%ProgramFiles%`,
`%ProgramFiles(x86)%`, `%ProgramData%` and `%SystemDrive%\Windows`. The check runs
**before `stat()`**, so a hostile message cannot even make the app touch a system
directory — it is the difference between "a bad message is rejected" and "a bad
message made us read a system path". The operation is recorded as `skipped` with
`protected_location`, and the file is never moved.

The folder scanner applies the same rule (`REASON_PROTECTED`), so the preview
never offers a move the organizer would refuse.

## 9. Residual risks — the honest list

**9.1 A same-user process can impersonate an extension.**
The token file is now ACL-restricted to the current account (§6.4), which stops
other Windows users. It does not stop a program already running *as you*: it can
read the token, connect to the pipe, and send a `download_completed` message
naming any file you can read. SmartSort would then move that file.

There is no clean defence: native messaging cannot prove which extension is on
the other end of a pipe, and the token is the only shared secret. The practical
boundaries are the allow-list (§7) and the fact that such a process can move the
file itself with `MoveFile`. What the hardening in §6 did change is the
*consequence*: a leaked token used to be a code-execution primitive via pickle,
and now it is only a request to move a file — which that process could already
do.

**9.2 A compromised browser profile is game over.**
If an attacker controls the browser, they control `chrome.downloads` and can
report any path they like. SmartSort bounds the damage — the file must exist, must
be a regular file, must not be in a system directory, is never overwritten, and
the operation is recorded and undoable — but it will move the file. Preventing
this would require knowing which downloads are legitimate, which the app cannot
know.

**9.3 UNC source paths are accepted.**
A browser can legitimately save to a mapped network drive, so `\\server\share`
paths are not rejected. Reaching such a path can leak NTLM credentials to a
hostile SMB server. This is a real vector for a compromised extension; it is
allowed because blocking it would break network-drive downloads.

**9.4 Logs contain full file paths.**
`logger.info("organized %s -> %s", source, final_path, ...)` writes real paths to
`%LOCALAPPDATA%\SmartSort\logs\`. This is intentional — diagnosing "why didn't my
file move" without paths is hopeless. **Exported** diagnostics are redacted:
`redact_paths()` replaces the profile directory with `%USERPROFILE%` in
`diagnostics.json`, in every log file, and inside the exported database copy
(`tests/security/test_diagnostics_redaction.py`). The on-disk originals are
untouched, and the export never modifies the live database.

**9.5 No code signing.**
The build is unsigned, so Windows SmartScreen will warn on first run. That warning
is correct behaviour for an unsigned binary. Verify what you are running by
building from source (§11) rather than trusting a binary someone handed you.

**9.6 Not independently audited.**
This document is the author's own review of the author's own code. It is evidence,
not certification. The tests listed in §10 are the part you can re-run yourself.

## 10. What was verified, and how

| Property | Evidence |
| --- | --- |
| No network calls | Repository-wide search, §2 |
| No pickle on the wire | `test_bridge_never_unpickles_a_client_payload` |
| Bounded bridge payload | `recv_payload` cap, §6.2 |
| Bounded connections | `test_bridge_refuses_connections_beyond_the_limit` |
| No code execution of downloads | Repository-wide search, §5 |
| Framing limits | `tests/security/test_message_validation.py` (36 tests) |
| Path traversal | `tests/security/test_path_safety.py` (9 tests) |
| Protected system directories | `test_system_directories_are_never_organized`, `test_system_folder_files_are_not_offered` |
| Wrong token rejected | `test_bridge_rejects_a_wrong_token` |
| Real pipe, real host process | `tests/integration/test_native_messaging.py` (16 tests) |
| Allow-list enforced | `tests/integration/test_browser_flow.py` (3 tests) |
| Token ACL is user-only | `test_bridge_token_is_readable_only_by_the_current_user` |
| Exports are redacted | `tests/security/test_diagnostics_redaction.py` (5 tests) |
| Never overwrites | `tests/unit/test_organizer.py`, `tests/unit/test_conflict_resolver.py` |
| Failures preserve the source | `tests/unit/test_fileops.py`, `tests/unit/test_organizer.py` |
| Uninstaller refuses unsafe folders | `tests/unit/test_release_scripts.py` (12 tests) |
| Installer rejects zip-slip payloads | `tests/unit/test_release_scripts.py` |
| Uninstall keeps user data unless asked | `test_silent_uninstall_keeps_settings_and_history`, `test_purge_removes_settings_and_history` |
| A failed uninstall dialog deletes nothing | `test_dialog_failure_removes_nothing`, `test_dialog_cancel_does_nothing` |

Full suite: **293 passed**.

## 11. Hardening checklist for a cautious user

1. Build from source instead of running a binary you did not produce:
   `.\scripts\build_windows.ps1`.
2. Register only the extension ID you actually loaded. `--register-host` pins it
   automatically; the GUI does the same. Do not leave the list empty on a shared
   machine.
3. Keep the app in `%LOCALAPPDATA%`, not in a world-writable folder.
4. Do not point the destination at a network share you do not control.
5. Review the archive before sharing a diagnostics export, even though profile
   paths are redacted.
