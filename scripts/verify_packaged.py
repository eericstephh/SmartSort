"""End-to-end verification of the packaged build.

Starts the packaged desktop application, then drives the packaged native
messaging host exactly the way Chrome would: framed JSON on stdin/stdout. The
test asserts that a real file is moved into the real destination layout.

Usage:

    .venv\\Scripts\\python.exe scripts\\verify_packaged.py
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST = PROJECT_ROOT / "dist" / "SmartSort"
GUI = DIST / "SmartSort.exe"
HOST = DIST / "smartsort-host.exe"

PROTOCOL_VERSION = 1


def read_frame(stream) -> dict:
    header = stream.read(4)
    if len(header) < 4:
        raise RuntimeError("host closed the stream without a response")
    (length,) = struct.unpack("<I", header)
    body = stream.read(length)
    return json.loads(body.decode("utf-8"))


def write_frame(stream, payload: dict) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    stream.write(struct.pack("<I", len(body)) + body)
    stream.flush()


def wait_for_bridge(log_file: Path, timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if log_file.exists():
            text = log_file.read_text(encoding="utf-8", errors="replace")
            if "bridge listening" in text:
                return True
        time.sleep(0.25)
    return False


def other_instances() -> int:
    """How many SmartSort processes are running right now.

    A second instance hits the single-instance lock, hands its arguments to the
    running copy and exits, so the bridge never comes up in *this* process. That
    looks exactly like a broken build, so the failure message says which it is.
    """
    try:
        listed = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq SmartSort.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - environmental
        return 0
    return listed.stdout.lower().count("smartsort.exe")


def main() -> int:
    if not GUI.exists() or not HOST.exists():
        print(f"missing build artefacts under {DIST}", file=sys.stderr)
        return 2

    stamp = int(time.time())
    data_dir = PROJECT_ROOT / ".pytest-tmp" / "e2e" / f"run-{stamp}"
    downloads = data_dir / "Downloads"
    destination = data_dir / "SmartSortDest"
    downloads.mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)

    # Seed the destination so the app reports ready=True.
    os.environ["SMARTSORT_DATA_DIR"] = str(data_dir)
    sys.path.insert(0, str(PROJECT_ROOT))
    from smartsort.app.bootstrap import create_context

    context = create_context(data_dir, setup_logs=False)
    context.settings.destination_dir = str(destination)
    # On from the start: a file organized while the option was off is stored
    # without a hash, so it cannot be matched later. Turning the option on only
    # protects downloads that arrive after it.
    context.settings.set("skip_duplicate_content", True)
    context.close()

    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.pop("SMARTSORT_DATA_DIR", None)

    log_file = data_dir / "logs" / "smartsort.log"
    print("1. starting the packaged application")
    app = subprocess.Popen(
        [str(GUI), "--data-dir", str(data_dir), "--minimized"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_for_bridge(log_file):
            print("   FAILED: the bridge never started", file=sys.stderr)
            running = other_instances()
            if running:
                print(
                    f"   {running} SmartSort process(es) were already running. "
                    "A second instance exits on the single-instance lock, so the "
                    "bridge belongs to the other one. Close it and try again.",
                    file=sys.stderr,
                )
            else:
                print(f"   see {log_file}", file=sys.stderr)
            return 1
        print("   bridge is listening")

        print("2. asking the packaged native host for a ping")
        host = subprocess.Popen(
            [str(HOST), "--data-dir", str(data_dir)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            write_frame(
                host.stdin,
                {
                    "type": "ping",
                    "protocolVersion": PROTOCOL_VERSION,
                    "browser": "chrome",
                },
            )
            response = read_frame(host.stdout)
        finally:
            try:
                host.stdin.close()
            except OSError:
                pass
            host.wait(timeout=20)

        print(f"   response: {response}")
        assert response.get("ok") is True, "ping was rejected"
        assert response.get("app") == "SmartSort", "unexpected app identity"
        assert response.get("ready") is True, "app did not report ready"

        print("3. reporting a completed download through the host")
        sample = downloads / "holiday-photo.jpg"
        sample.write_bytes(b"\xff\xd8\xff\xe0 fake jpeg payload")

        host = subprocess.Popen(
            [str(HOST), "--data-dir", str(data_dir)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            write_frame(
                host.stdin,
                {
                    "type": "download_completed",
                    "protocolVersion": PROTOCOL_VERSION,
                    "browser": "chrome",
                    "download": {
                        "id": f"e2e-{stamp}",
                        "filename": str(sample),
                        "state": "complete",
                        "totalBytes": sample.stat().st_size,
                        "exists": True,
                    },
                },
            )
            response = read_frame(host.stdout)
        finally:
            try:
                host.stdin.close()
            except OSError:
                pass
            host.wait(timeout=20)

        print(f"   response: {response}")
        assert response.get("status") == "organized", "the file was not organized"

        final = Path(response["finalPath"])
        assert final.exists(), "the destination file does not exist"
        assert final.read_bytes() == b"\xff\xd8\xff\xe0 fake jpeg payload"
        assert final.parent.name == "Images", f"wrong category folder: {final.parent}"
        assert not sample.exists(), "the source file was not moved"
        print(f"   moved to: {final.relative_to(destination)}")

        print("4. verifying the operation was persisted")
        context = create_context(data_dir, setup_logs=False)
        try:
            recent = context.repos.operations.list_recent(1)
            assert recent, "no operation recorded"
            assert recent[0].final_path == str(final)
            assert recent[0].status == "organized"
            print(f"   history row #{recent[0].id} recorded")
        finally:
            context.close()

        print("5. scanning an existing folder through the packaged executable")
        scan_dir = data_dir / "OldDownloads"
        scan_dir.mkdir(exist_ok=True)
        (scan_dir / "invoice.pdf").write_bytes(b"%PDF-1.4 fake")
        (scan_dir / "song.mp3").write_bytes(b"ID3 fake")
        (scan_dir / "unfinished.zip.part").write_bytes(b"partial")

        completed = subprocess.run(
            [str(GUI), "--data-dir", str(data_dir), "--scan", str(scan_dir)],
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
            check=False,
        )
        assert completed.returncode == 0, f"scan failed: {completed.stderr}"
        out = completed.stdout
        assert "invoice.pdf" in out, "the scan did not list the pdf"
        assert "documents" in out, "the pdf was not classified"
        assert "file_still_downloading" in out, "the .part file was not flagged"
        assert "2 of 3 files can be organized" in out, out
        assert (scan_dir / "invoice.pdf").exists(), "a scan must not move files"
        print("   2 of 3 previewed, nothing moved")

        print("6. adding a user category and scanning with it")
        # ``srt`` is not claimed by any built-in category, so the new one wins it.
        # (An extension that documents/images/... already own stays theirs.)
        context = create_context(data_dir, setup_logs=False)
        try:
            category_id = context.repos.categories.create("Subtitles", ["srt"])
            print(f"   created category {category_id!r}")
        finally:
            context.close()

        notes_dir = data_dir / "SubtitleInbox"
        notes_dir.mkdir(exist_ok=True)
        (notes_dir / "episode-01.srt").write_bytes(b"1\n00:00:01,000 --> 00:00:02,000\nhi\n")

        completed = subprocess.run(
            [str(GUI), "--data-dir", str(data_dir), "--scan", str(notes_dir)],
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
            check=False,
        )
        assert completed.returncode == 0, f"scan failed: {completed.stderr}"
        assert category_id in completed.stdout, (
            f"the packaged scanner ignored the user category:\n{completed.stdout}"
        )
        print(f"   the packaged scanner classified into {category_id!r}")

        print("7. sending the same bytes twice with duplicate detection on")
        again = downloads / "holiday-photo-copy.jpg"
        # Same content as the file step 3 already organized, different name.
        again.write_bytes(b"\xff\xd8\xff\xe0 fake jpeg payload")

        host = subprocess.Popen(
            [str(HOST), "--data-dir", str(data_dir)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            write_frame(
                host.stdin,
                {
                    "type": "download_completed",
                    "protocolVersion": PROTOCOL_VERSION,
                    "browser": "chrome",
                    "download": {
                        "id": f"e2e-dup-{stamp}",
                        "filename": str(again),
                        "state": "complete",
                        "totalBytes": again.stat().st_size,
                        "exists": True,
                    },
                },
            )
            response = read_frame(host.stdout)
        finally:
            try:
                host.stdin.close()
            except OSError:
                pass
            host.wait(timeout=20)

        print(f"   response: {response}")
        assert response.get("status") == "content_duplicate", (
            f"the duplicate was not recognised: {response}"
        )
        assert again.exists(), "a content duplicate must be left where it is"
        print("   recognised as a duplicate and left untouched")

        print("")
        print("PASS - packaged build works end to end")
        return 0
    finally:
        if app.poll() is None:
            app.kill()
            try:
                app.wait(timeout=15)
            except subprocess.TimeoutExpired:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
