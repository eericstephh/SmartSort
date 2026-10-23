# Installation

Two supported ways to install SmartSort. Neither requires administrator rights
and neither writes to `Program Files`.

> **PowerShell execution policy.** If a script refuses to run with *"running
> scripts is disabled on this system"*, either allow local scripts once:
>
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```
>
> or run each script with a scoped bypass:
>
> ```powershell
> powershell -ExecutionPolicy Bypass -File .\scripts\install_windows.ps1 -Build
> ```

---

## A. Two ways to install

Both are per-user: no administrator rights, nothing written to `Program Files`.

|  | `SmartSort-1.0.0-portable.zip` | `SmartSort-Setup-1.0.0.exe` |
|---|---|---|
| Installs to | wherever you unzip it | `%LOCALAPPDATA%\Programs\SmartSort` |
| Data lives in | a `data` folder beside the exe | `%LOCALAPPDATA%\SmartSort` |
| Shortcuts | none — you create them | Start menu and desktop (optional) |
| Listed in *Apps & features* | no | yes, with an uninstaller |
| Best for | a USB stick, trying it out, keeping everything in one folder | everyday use |

### A1. Portable

Unzip `SmartSort-1.0.0-portable.zip`. You get a single folder:

```
SmartSort\
    SmartSort.exe            the desktop application
    smartsort-host.exe       the browser native messaging host
    browser_extension\       the unpacked Chrome/Edge extension
    docs\                    this documentation
    portable.txt             the marker that makes it portable
```

Run `SmartSort.exe`. Because `portable.txt` sits next to it, the database, logs
and bridge token are created in `SmartSort\data\` — **not** in
`%LOCALAPPDATA%`. Copy or move the folder anywhere, including a USB stick, and
your history travels with it. Delete `portable.txt` to go back to the normal
per-user location.

Check it any time with:

```powershell
.\SmartSort.exe --print-paths
```

### A2. Installer

Run `SmartSort-Setup-1.0.0.exe`. It asks for a folder (default
`%LOCALAPPDATA%\Programs\SmartSort`), whether to create shortcuts, and whether
to start the app afterwards. No elevation prompt appears.

Silent installation, for a script:

```powershell
.\SmartSort-Setup-1.0.0.exe /S
.\SmartSort-Setup-1.0.0.exe /S /D="D:\Apps\SmartSort"
.\SmartSort-Setup-1.0.0.exe /S /D="D:\Apps\SmartSort" --no-shortcuts
```

| Option | Effect |
|---|---|
| `/S` | No window, default options |
| `/D=<path>` | Install folder (must be the last argument when using the interactive form) |
| `--no-shortcuts` | Skip the Start menu and desktop shortcuts |

The installer writes exactly one registry key, under `HKCU`:

```
HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\SmartSort
```

That is what makes SmartSort appear in **Settings → Apps → Installed apps**.

### A3. Choose a destination

Dashboard → **Change** → pick a folder on any drive (for example
`E:\SmartSort`). The folder is created if it does not exist. A write test runs
immediately, so a read-only or network-unavailable path is rejected right away
instead of failing silently later.

### A4. Optional: start with Windows

Settings → **Startup and window** → *Start SmartSort when I sign in*.
This writes exactly one value:

```
HKCU\Software\Microsoft\Windows\CurrentVersion\Run  →  SmartSort
```

Nothing else. Turning the switch off removes that value.

### A5. Verify the build (developers)

```powershell
.venv\Scripts\python.exe scripts\verify_packaged.py
```

This starts the packaged application, sends a real `download_completed` message
through the packaged native host over the real named pipe, and asserts that the
file lands in `<destination>\<date>\Images\`. It prints `PASS` on success.

### Moving the portable build

The folder is self-contained. If you move it after registering the browser
integration, re-run the registration step, because the manifest stores an
absolute path to the launcher.

---

## B. Source install

Requirements: Windows 10/11 64-bit, Python 3.10 or newer on `PATH`.

```powershell
git clone <repository> smartsort
cd smartsort
.\scripts\install_windows.ps1
.\scripts\run_dev.ps1
```

`install_windows.ps1` will:

1. verify the Python version,
2. create `.venv`,
3. `pip install -r requirements.txt`,
4. generate the icon assets,
5. print the next steps.

Run the test suite with:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q
```

---

## C. Browser integration

### What the integration is

Three pieces:

1. **The extension** (`browser_extension/`) — observes the downloads API.
2. **The native messaging manifest** — a small JSON file that tells the browser
   which executable to launch.
3. **The registry entries** — one key per browser pointing at that manifest.

Chrome and Edge share the same manifest format, so one registration covers both.

### Step 1 — load the extension

**Chrome**

1. Open `chrome://extensions`.
2. Enable **Developer mode** (top right).
3. Click **Load unpacked**.
4. Select the `browser_extension` folder inside `dist\SmartSort` (or the
   repository root when running from source).
5. The card shows an **ID** such as `abcdefghijklmnopabcdefghijklmnop`. Copy it.

**Edge**

1. Open `edge://extensions`.
2. Enable **Developer mode** (left sidebar).
3. Click **Load unpacked** and select the same folder.
4. Copy the ID from the card. Edge assigns a different ID than Chrome, so
   register both if you use both.

### Step 2 — register the native host

Either use the app:

> **About & diagnostics → Browser integration** → paste the ID(s), separated by
> a comma → **Install browser integration**

or the script:

```powershell
.\scripts\register_native_host.ps1 -ExtensionId <CHROME_ID>
.\scripts\register_native_host.ps1 -ExtensionId <CHROME_ID>,<EDGE_ID>
```

or the packaged executable directly:

```powershell
.\dist\SmartSort\SmartSort.exe --register-host <CHROME_ID>,<EDGE_ID>
```

All three paths do the same thing:

- write `%LOCALAPPDATA%\SmartSort\native-host\com.smartsort.host.json`
- create `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.smartsort.host`
- create `HKCU\Software\Microsoft\Edge\NativeMessagingHosts\com.smartsort.host`

The manifest looks like this:

```json
{
  "name": "com.smartsort.host",
  "description": "SmartSort native messaging host",
  "path": "C:\\...\\dist\\SmartSort\\smartsort-host.exe",
  "type": "stdio",
  "allowed_origins": ["chrome-extension://<YOUR_ID>/"]
}
```

`allowed_origins` is the real security boundary: no other extension can launch
the host.

### Step 3 — restart the browser

Chrome and Edge read native messaging registrations at startup. After
restarting, open the extension popup — it should show **Connected** and the
destination folder.

If it shows **Not installed**, see [troubleshooting.md](troubleshooting.md).

### Updating the integration

- **New build, same folder:** nothing to do, the manifest points at the same
  path.
- **Moved the build:** re-run the registration (it overwrites the manifest).
- **New extension ID** (for example after publishing): re-register with the new
  ID. The old `allowed_origins` entry is replaced.

### Disabling without uninstalling

- In the browser: `chrome://extensions` → toggle the SmartSort card off. The
  desktop app keeps working with the fallback folder watcher.
- In the app: Settings → turn off **Move files the browser saved to its default
  folder**, or press **Pause** on the dashboard.

### Removing the integration

```powershell
.\scripts\register_native_host.ps1 -Unregister
```

or **Remove browser integration** in the app. This deletes the manifest and the
two `HKCU` keys — and only those. Then remove the extension from the browser's
extensions page.

---

## D. Uninstalling SmartSort

**If you used the installer**, use the normal Windows route:

*Settings → Apps → Installed apps → SmartSort → Uninstall*, or run
`uninstall.exe` from the install folder.

It asks one question with three answers. **No** is the default button, so
pressing Enter keeps your settings and history:

| Answer | Result |
|---|---|
| **Yes** | Remove the app **and** delete settings and history |
| **No** (default) | Remove the app but keep settings and history for a future install |
| **Cancel** | Do nothing |

Silent equivalents:

```powershell
uninstall.exe /S            # keep settings and history
uninstall.exe /S /PURGE     # delete them too
```

It removes the shortcuts, the *Apps & features* entry, the `HKCU` Run value, the
native messaging keys for Chrome, Edge, Chromium and Brave, and the install
folder. Your organized files are **never** touched.

**If you used the portable zip**, there is nothing to uninstall: delete the
folder. Delete `data\` inside it first if you also want to remove your history.

**From a source checkout**, the scripts are still available:

```powershell
.\scripts\uninstall_windows.ps1
```

Optional flags:

| Flag | Effect |
|---|---|
| `-PurgeData` | Also deletes `%LOCALAPPDATA%\SmartSort` (settings, history, logs) after typing `DELETE`. |
| `-RemoveBuild` | Also deletes `.venv`, `build` and `dist`. |

---

## E. Code signing

The build is unsigned. Windows SmartScreen shows
*"Windows protected your PC"* the first time `SmartSort.exe` runs:

> More info → **Run anyway**

This is expected for any unsigned executable. To remove the warning you need an
Authenticode certificate (OV or EV) and to sign both executables:

```powershell
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 `
  /f certificate.pfx /p <password> dist\SmartSort\SmartSort.exe
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 `
  /f certificate.pfx /p <password> dist\SmartSort\smartsort-host.exe
```

Sign **before** distributing and **after** every rebuild, because signing
invalidates on modification. An EV certificate removes the SmartScreen warning
immediately; an OV certificate needs reputation to build up.

The browser does not require the host executable to be signed, but some
enterprise policies block unsigned native messaging hosts.
