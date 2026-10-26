"""Render the tutorial video from the real SmartSort interface.

Nothing in this script is a mock-up: every frame is a grab of the actual
``MainWindow``. The window is pointed at a throwaway data directory that this
script fills with invented file names and empty placeholder files, so no real
download, folder path or history row can reach the video.

    .venv\\Scripts\\python.exe scripts\\make_demo_video.py --ffmpeg <path to ffmpeg.exe>

``--lang fa|en|all`` picks the language; each one is written to
``docs/media/smartsort-tutorial-<lang>.mp4``. Both versions share the same
scenes and differ only in the words on the slides.

The ffmpeg binary is not vendored; ``imageio-ffmpeg`` ships one, and the path
can also come from the FFMPEG environment variable.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _offscreen  # noqa: E402  (lives next to this script)

# The UI must be built without a display. This has to happen before Qt loads.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

CANVAS = (1920, 1080)
WINDOW_SIZE = (1480, 830)
FPS = 30

# Every path the interface displays is built under a scratch folder that is
# deliberately outside the user profile: a path like C:\Users\<name>\... would
# put a real account name on screen. See _offscreen.neutral_scratch.
FRAMES = PROJECT_ROOT / ".pytest-tmp" / "demo-video" / "slides"
SEGMENTS = PROJECT_ROOT / ".pytest-tmp" / "demo-video" / "segments"
MEDIA_DIR = PROJECT_ROOT / "docs" / "media"

# Invented downloads. The names are deliberately generic, and the files
# themselves are a few bytes each - the sizes below are display metadata only.
SAMPLES = (
    ("holiday-photo.jpg", "images", "Images", 2_480_000, 6),
    ("invoice-2026-03.pdf", "documents", "Documents", 184_000, 26),
    ("podcast-episode-12.mp3", "audio", "Audio", 41_300_000, 52),
    ("screenshot-2026-10-24.png", "images", "Images", 640_000, 74),
    ("project-backup.zip", "archives", "Archives", 812_000_000, 98),
    ("meeting-recording.mp4", "videos", "Videos", 233_000_000, 121),
)

PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

# Language code -> the number style used on the slides. Persian keeps Persian
# digits; English keeps Latin ones.
DIGITS = {"fa": PERSIAN_DIGITS, "en": None}


def number(value: int | str, lang: str) -> str:
    table = DIGITS.get(lang)
    return str(value).translate(table) if table else str(value)


def log(message: str) -> None:
    print(f"[video] {message}", flush=True)


# -- demo data -------------------------------------------------------------
def seed(data_dir: Path, root: Path, lang: str) -> tuple[Path, Path]:
    """Fill a fresh data directory with invented history.

    Returns the (downloads, destination) folders, both under ``root`` so that no
    path shown by the interface contains a real account name.
    """
    downloads = root / "Downloads"
    destination = root / "Organized"
    downloads.mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)

    from smartsort.app.bootstrap import create_context

    context = create_context(data_dir, setup_logs=False)
    try:
        context.settings.set("language", lang)
        context.settings.set("theme", "dark")
        context.settings.set("destination_dir", str(destination))
        context.settings.set("auto_organize", True)
        context.settings.set("skip_duplicate_content", True)
        context.settings.set("watch_directory", str(downloads))
        context.repos.categories.create("Subtitles", ["srt"])

        now = datetime.now().astimezone()
        for name, category, folder, size, minutes_ago in SAMPLES:
            final = destination / now.strftime("%Y-%m-%d") / folder / name
            final.parent.mkdir(parents=True, exist_ok=True)
            final.write_bytes(b"demo")
            context.repos.operations.add(
                origin="browser",
                category=category,
                original_path=str(downloads / name),
                final_path=str(final),
                status="organized",
                size_bytes=size,
                completed_at=(now - timedelta(minutes=minutes_ago)).isoformat(
                    timespec="seconds"
                ),
            )

        # One duplicate, so the history shows what the new feature records.
        first = destination / now.strftime("%Y-%m-%d") / "Images" / SAMPLES[0][0]
        context.repos.operations.add(
            origin="browser",
            category="images",
            original_path=str(downloads / "holiday-photo (1).jpg"),
            final_path="",
            status="content_duplicate",
            size_bytes=2_480_000,
            completed_at=(now - timedelta(minutes=3)).isoformat(timespec="seconds"),
            message="content_already_exists",
            undo_state="unavailable",
            content_hash="0" * 64,
            duplicate_of=str(first),
        )
    finally:
        context.close()

    # A couple of files still waiting in the download folder, for realism.
    for name in ("design-mockup-v3.psd", "annual-report.xlsx"):
        (downloads / name).write_bytes(b"demo")

    return downloads, destination


# -- the window ------------------------------------------------------------
# The offscreen platform does not enumerate the system font database in this
# environment, so every glyph would come out as a box. The font files are still
# readable, so they are registered by hand before any widget is built.
FONT_FILES = (
    "segoeui.ttf",
    "segoeuib.ttf",
    "segoeuisl.ttf",
    "segoeuil.ttf",
    "tahoma.ttf",
    "tahomabd.ttf",
)


def register_fonts() -> None:
    from PySide6.QtGui import QFontDatabase

    folder = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    loaded = 0
    for name in FONT_FILES:
        path = folder / name
        if not path.is_file():
            continue
        if QFontDatabase.addApplicationFont(str(path)) >= 0:
            loaded += 1
    log(f"registered {loaded} font files, {len(QFontDatabase.families())} families")
    if not QFontDatabase.families():
        raise SystemExit("no fonts could be registered; text would render as boxes")


def build_window(data_dir: Path, lang: str):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from smartsort.app.bootstrap import create_context
    from smartsort.app.i18n import set_language
    from smartsort.app.ui.controller import AppController
    from smartsort.app.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    log(f"registered {_offscreen.register_fonts()} font families")
    set_language(lang)
    app.setLayoutDirection(Qt.RightToLeft if is_rtl(lang) else Qt.LeftToRight)

    context = create_context(data_dir, setup_logs=False)
    controller = AppController(context)
    window = MainWindow(controller)
    window.resize(*WINDOW_SIZE)
    window.show()
    app.processEvents()
    return app, context, controller, window


def grab_page(app, window, key: str, highlight=None):
    """Switch to a page and return a pixmap of the whole window."""
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtGui import QColor, QPainter, QPen

    window.navigate(key)
    app.processEvents()
    page = window._pages.get(key)
    if page is not None and hasattr(page, "refresh"):
        page.refresh()
    app.processEvents()

    shot = window.grab()

    if highlight is not None and page is not None:
        target = getattr(page, highlight, None)
        if target is not None:
            top_left = target.mapTo(window, QPoint(0, 0))
            rect = QRect(top_left, target.size()).adjusted(-10, -10, 10, 10)
            painter = QPainter(shot)
            painter.setRenderHint(QPainter.Antialiasing, True)
            pen = QPen(QColor("#4DA3FF"))
            pen.setWidth(4)
            painter.setPen(pen)
            painter.setBrush(QColor(77, 163, 255, 34))
            painter.drawRoundedRect(rect, 12, 12)
            painter.end()
    return shot


# -- slides ----------------------------------------------------------------
SLIDE_STYLE = """
#slide {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #131a29, stop:0.55 #0e1420, stop:1 #0a0e17);
}
#title { color: #eaf1fb; font-family: "Segoe UI", "Tahoma"; font-size: 44px; font-weight: 700; }
#stepLabel { color: #4da3ff; font-family: "Segoe UI", "Tahoma"; font-size: 24px; font-weight: 600; }
#caption { color: #a8bad4; font-family: "Segoe UI", "Tahoma"; font-size: 27px; }
#shot { background: #0a0e17; border: 1px solid #223049; border-radius: 14px; }
#footer { color: #55698a; font-family: "Segoe UI", "Tahoma"; font-size: 20px; }
"""


def make_slide(
    *,
    title: str,
    caption: str,
    shot=None,
    step: int | None = None,
    total: int | None = None,
    rtl: bool = True,
    lang: str = "fa",
):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

    slide = QWidget()
    slide.setObjectName("slide")
    slide.setStyleSheet(SLIDE_STYLE)
    slide.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
    slide.setFixedSize(*CANVAS)

    layout = QVBoxLayout(slide)
    layout.setContentsMargins(80, 54, 80, 44)
    layout.setSpacing(20)

    header = QHBoxLayout()
    header.setSpacing(18)
    title_label = QLabel(title)
    title_label.setObjectName("title")
    header.addWidget(title_label, 1)
    if step is not None and total is not None:
        step_label = QLabel(f"{number(step, lang)} / {number(total, lang)}")
        step_label.setObjectName("stepLabel")
        step_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.addWidget(step_label)
    layout.addLayout(header)

    if shot is not None:
        holder = QLabel()
        holder.setObjectName("shot")
        holder.setAlignment(Qt.AlignCenter)
        scaled = shot.scaled(
            1740, 772, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        holder.setPixmap(scaled)
        holder.setFixedSize(scaled.width() + 2, scaled.height() + 2)
        layout.addWidget(holder, 1, Qt.AlignHCenter)
    else:
        layout.addStretch(1)

    caption_label = QLabel(caption)
    caption_label.setObjectName("caption")
    caption_label.setWordWrap(True)
    caption_label.setAlignment(_start_alignment(slide, caption) | Qt.AlignVCenter)
    layout.addWidget(caption_label)

    footer = QLabel("SmartSort 1.1.0")
    footer.setObjectName("footer")
    layout.addWidget(footer)

    slide.setLayout(layout)
    return slide


def make_cover(cover: tuple[str, str, str], rtl: bool):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

    slide = QWidget()
    slide.setObjectName("slide")
    slide.setStyleSheet(
        SLIDE_STYLE
        + "#big { color:#eaf1fb; font-family:'Segoe UI','Tahoma'; font-size:96px;"
        " font-weight:800; }"
        + "#sub { color:#7fb2ef; font-family:'Segoe UI','Tahoma'; font-size:38px; }"
        + "#hint { color:#93a7c4; font-family:'Segoe UI','Tahoma'; font-size:28px; }"
    )
    slide.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
    slide.setFixedSize(*CANVAS)

    layout = QVBoxLayout(slide)
    layout.setContentsMargins(140, 140, 140, 120)
    layout.setSpacing(26)
    layout.addStretch(1)

    # Centred explicitly: a Latin word and a Persian line in the same column
    # otherwise align to opposite edges, because Qt follows each text's own
    # direction rather than the widget's.
    for text, name in zip(cover, ("big", "sub", "hint")):
        label = QLabel(text)
        label.setObjectName(name)
        label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        layout.addWidget(label)

    layout.addStretch(1)
    return slide


def _start_alignment(widget, text: str = ""):
    """Return the flag that puts ``text`` against the starting edge.

    Qt mirrors AlignLeft/AlignRight for right-to-left *paragraphs* only, so the
    flag that lands on the leading edge depends on the text as well as the
    widget: a Persian line needs AlignLeft in a Persian layout, while a
    Latin-only line (the project URL) needs AlignRight in that same layout.
    Choosing from the text keeps every line on the same edge instead of
    scattering them across the slide. In an English layout both cases reduce to
    AlignLeft, which is what the caller expects.
    """
    from PySide6.QtCore import Qt

    rtl_text = any("\u0590" <= char <= "\u08ff" for char in text)
    if widget.layoutDirection() == Qt.RightToLeft:
        return Qt.AlignLeft if rtl_text else Qt.AlignRight
    return Qt.AlignRight if rtl_text else Qt.AlignLeft


def make_plain(title: str, lines, *, rtl: bool = True):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

    slide = QWidget()
    slide.setObjectName("slide")
    slide.setStyleSheet(
        SLIDE_STYLE
        + "#line { color:#b7c7de; font-family:'Segoe UI','Tahoma'; font-size:32px; }"
    )
    slide.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
    slide.setFixedSize(*CANVAS)

    layout = QVBoxLayout(slide)
    layout.setContentsMargins(130, 120, 130, 100)
    layout.setSpacing(30)
    layout.addStretch(1)

    heading = QLabel(title)
    heading.setObjectName("title")
    heading.setAlignment(_start_alignment(slide, title) | Qt.AlignVCenter)
    layout.addWidget(heading)
    layout.addSpacing(10)

    for line in lines:
        label = QLabel(line)
        label.setObjectName("line")
        label.setWordWrap(True)
        # Set explicitly: a line that starts with a Latin word (a URL, for
        # instance) would otherwise be laid out against the other edge.
        label.setAlignment(_start_alignment(slide, line) | Qt.AlignVCenter)
        layout.addWidget(label)

    layout.addStretch(1)
    return slide


# -- encoding --------------------------------------------------------------
def encode(slides: list[tuple[Path, float]], ffmpeg: Path, output: Path) -> None:
    """Turn each slide into a slowly zooming clip, then join them."""
    SEGMENTS.mkdir(parents=True, exist_ok=True)
    for stale in SEGMENTS.glob("*.mp4"):
        stale.unlink()

    parts: list[Path] = []
    for index, (image, seconds) in enumerate(slides):
        part = SEGMENTS / f"{index:02d}.mp4"
        frames = max(1, int(round(seconds * FPS)))
        zoom = (
            f"scale=2400:-1,"
            f"zoompan=z='min(1+0.00055*on,1.06)':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={CANVAS[0]}x{CANVAS[1]}:fps={FPS},"
            f"format=yuv420p"
        )
        command = [
            str(ffmpeg), "-y", "-loglevel", "error",
            "-i", str(image),
            "-vf", zoom,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-movflags", "+faststart",
            str(part),
        ]
        log(f"clip {index + 1}/{len(slides)} ({seconds:.0f}s)")
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode != 0:
            raise SystemExit(f"ffmpeg failed:\n{completed.stderr[-2000:]}")
        parts.append(part)

    listing = SEGMENTS / "list.txt"
    listing.write_text(
        "".join(f"file '{part.as_posix()}'\n" for part in parts), encoding="utf-8"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    joined = subprocess.run(
        [
            str(ffmpeg), "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(listing),
            "-c", "copy", "-movflags", "+faststart", str(output),
        ],
        capture_output=True,
        text=True,
    )
    if joined.returncode != 0:
        raise SystemExit(f"ffmpeg concat failed:\n{joined.stderr[-2000:]}")


def find_ffmpeg(explicit: str | None) -> Path:
    candidate = explicit or os.environ.get("FFMPEG")
    if candidate:
        return Path(candidate)
    try:
        import imageio_ffmpeg

        return Path(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        raise SystemExit(
            "no ffmpeg found: pass --ffmpeg or set FFMPEG"
        )


# -- scenes ----------------------------------------------------------------
# One script, two languages. Everything that ends up on a slide lives here, so
# the two versions cannot drift apart in structure - only in wording.
TEXT: dict[str, dict] = {
    "fa": {
        "file": "smartsort-tutorial-fa.mp4",
        "cover": ("SmartSort", "دانلودها، مرتب.", "راهنمای نصب و استفاده"),
        "footer": "SmartSort 1.1.0",
        "scenes": (
            {
                "page": "dashboard",
                "title": "داشبورد",
                "caption": "وضعیت مرتب‌سازی، آمار امروز، پوشهٔ مقصد و آخرین فایل‌های مرتب‌شده.",
                "seconds": 5.5,
            },
            {
                "page": "settings",
                "title": "تنظیمات — پوشهٔ مقصد",
                "caption": "پوشهٔ مقصد و مرتب‌سازی خودکار را از همین‌جا تعیین می‌کنی. پوشهٔ تاریخ و دسته هم قابل خاموش کردن است.",
                "seconds": 6.5,
            },
            {
                "page": "settings",
                "title": "تشخیص فایل تکراری",
                "caption": "با روشن کردن این گزینه، محتوای هر دانلود با فایل‌های قبلی مقایسه می‌شود؛ فایل یکسان سر جایش می‌ماند.",
                "highlight": "_skip_duplicates",
                "seconds": 7.0,
            },
            {
                "page": "categories",
                "title": "دسته‌های دلخواه",
                "caption": "هر دسته‌ای با نام و پسوندهای خودت بساز؛ نام دسته همان نام پوشه است، پس طبق قواعد ویندوز بررسی می‌شود.",
                "highlight": "_table",
                "seconds": 7.0,
            },
            {
                "page": "history",
                "title": "تاریخچه و بازگردانی",
                "caption": "هر جابه‌جایی ثبت می‌شود. فایلی که اشتباه رفت، با یک دکمه به جای اولش برمی‌گردد.",
                "highlight": "_table",
                "seconds": 7.0,
            },
            {
                "page": "about",
                "title": "درباره",
                "caption": "نسخهٔ برنامه و لینک صفحهٔ پروژه.",
                "seconds": 4.5,
            },
        ),
        "extension": (
            "افزونهٔ مرورگر",
            (
                "۱. از داشبورد، پوشهٔ افزونه را باز کن.",
                "۲. در کروم یا اج، صفحهٔ افزونه‌ها را باز کن و «Load unpacked» را بزن.",
                "۳. همان پوشه را انتخاب کن و افزونه را پین کن.",
                "از آن پس هر دانلود کامل‌شده به برنامه گزارش می‌شود.",
            ),
        ),
        "outro": (
            "آماده‌ای؟",
            (
                "نسخهٔ ۱.۱٫۰ — ویندوز ۱۰ و ۱۱، ۶۴ بیتی",
                "بدون نیاز به دسترسی مدیر",
                "github.com/eericstephh/SmartSort",
            ),
        ),
    },
    "en": {
        "file": "smartsort-tutorial-en.mp4",
        "cover": ("SmartSort", "Downloads, organized.", "Install and use"),
        "footer": "SmartSort 1.1.0",
        "scenes": (
            {
                "page": "dashboard",
                "title": "Dashboard",
                "caption": "Sorting status, today's numbers, the destination folder, and the files sorted most recently.",
                "seconds": 5.5,
            },
            {
                "page": "settings",
                "title": "Settings — destination",
                "caption": "Pick the destination folder and switch automatic sorting on or off. The date and category folders can be turned off too.",
                "seconds": 6.5,
            },
            {
                "page": "settings",
                "title": "Duplicate detection",
                "caption": "With this on, the content of every download is compared with what you already have. An identical file stays where it is.",
                "highlight": "_skip_duplicates",
                "seconds": 7.0,
            },
            {
                "page": "categories",
                "title": "Your own categories",
                "caption": "Add a category with a name and extensions of your own. The name becomes the folder, so it is checked against the Windows rules.",
                "highlight": "_table",
                "seconds": 7.0,
            },
            {
                "page": "history",
                "title": "History and undo",
                "caption": "Every move is recorded. A file that went to the wrong place goes back where it came from in one click.",
                "highlight": "_table",
                "seconds": 7.0,
            },
            {
                "page": "about",
                "title": "About",
                "caption": "The version, and a link to the project page.",
                "seconds": 4.5,
            },
        ),
        "extension": (
            "The browser extension",
            (
                "1. Open the extension folder from the dashboard.",
                "2. In Chrome or Edge, open the extensions page and choose \u201cLoad unpacked\u201d.",
                "3. Select that folder and pin the extension.",
                "From then on, every finished download is reported to the app.",
            ),
        ),
        "outro": (
            "Ready when you are",
            (
                "Version 1.1.0 — Windows 10 and 11, 64-bit",
                "No administrator rights required",
                "github.com/eericstephh/SmartSort",
            ),
        ),
    },
}


def is_rtl(lang: str) -> bool:
    return lang == "fa"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffmpeg", default=None)
    parser.add_argument("--keep-data", action="store_true")
    parser.add_argument(
        "--lang",
        default="all",
        choices=("fa", "en", "all"),
        help="which language(s) to render; each gets its own mp4",
    )
    args = parser.parse_args()

    languages = ("fa", "en") if args.lang == "all" else (args.lang,)
    FRAMES.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_ffmpeg(args.ffmpeg)

    for lang in languages:
        render(lang, ffmpeg, keep_data=args.keep_data)
    return 0


def render(lang: str, ffmpeg: Path, *, keep_data: bool) -> Path:
    text = TEXT[lang]
    rtl = is_rtl(lang)
    output = MEDIA_DIR / text["file"]
    log(f"--- {lang} ---")

    scratch = _offscreen.neutral_scratch("video", clean=True)
    data_dir = scratch / "data"
    log(f"seeding a throwaway data directory at {scratch}")
    seed(data_dir, scratch, lang)

    app, context, controller, window = build_window(data_dir, lang)
    try:
        slides: list[tuple[Path, float]] = []

        cover = make_cover(text["cover"], rtl)
        cover_path = FRAMES / f"{lang}-00-cover.png"
        cover.grab().save(str(cover_path))
        slides.append((cover_path, 4.0))

        scenes = text["scenes"]
        for index, scene in enumerate(scenes, start=1):
            shot = grab_page(
                app, window, scene["page"], highlight=scene.get("highlight")
            )
            slide = make_slide(
                title=scene["title"],
                caption=scene["caption"],
                shot=shot,
                step=index,
                total=len(scenes),
                rtl=rtl,
                lang=lang,
            )
            path = FRAMES / f"{lang}-{index:02d}-{scene['page']}.png"
            slide.grab().save(str(path))
            slides.append((path, scene["seconds"]))
            log(f"captured {scene['page']}")

        steps = make_plain(*text["extension"], rtl=rtl)
        steps_path = FRAMES / f"{lang}-90-extension.png"
        steps.grab().save(str(steps_path))
        slides.append((steps_path, 7.0))

        outro = make_plain(*text["outro"], rtl=rtl)
        outro_path = FRAMES / f"{lang}-99-outro.png"
        outro.grab().save(str(outro_path))
        slides.append((outro_path, 5.0))
    finally:
        window.close()
        app.processEvents()
        context.close()

    log(f"encoding {output.name} with {ffmpeg.name}")
    encode(slides, ffmpeg, output)

    if not keep_data:
        shutil.rmtree(scratch, ignore_errors=True)
        log(f"removed {scratch}")

    size = output.stat().st_size
    log(f"wrote {output} ({size / 1024 / 1024:.1f} MB)")
    return output


if __name__ == "__main__":
    raise SystemExit(main())
