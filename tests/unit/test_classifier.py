"""Classification rules."""

from __future__ import annotations

import pytest

from smartsort.app.core.classifier import Classifier, _normalise_extension
from smartsort.app.storage.models import Category


def build(extensions_map: dict[str, list[str]], disabled: set[str] | None = None) -> Classifier:
    disabled = disabled or set()
    categories = [
        Category(
            id=cat_id,
            name=cat_id.title(),
            enabled=cat_id not in disabled,
            extensions=tuple(exts),
        )
        for cat_id, exts in extensions_map.items()
    ]
    return Classifier(categories)


@pytest.fixture
def default_classifier(repos) -> Classifier:
    return Classifier(repos.categories.list_all())


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("photo.jpg", "images"),
        ("photo.JPEG", "images"),
        ("anim.gif", "images"),
        ("scan.TIFF", "images"),
        ("clip.mp4", "videos"),
        ("movie.MKV", "videos"),
        ("report.pdf", "documents"),
        ("sheet.xlsx", "documents"),
        ("notes.txt", "documents"),
        ("song.mp3", "audio"),
        ("voice.OPUS", "audio"),
        ("bundle.zip", "archives"),
        ("archive.7z", "archives"),
        ("setup.exe", "installers"),
        ("package.msi", "installers"),
    ],
)
def test_known_extensions(default_classifier: Classifier, filename: str, expected: str) -> None:
    assert default_classifier.classify(filename) == expected


@pytest.mark.parametrize(
    "filename",
    ["weird.qqq", "noextension", "trailingdot.", ".hidden", "file.unknownext"],
)
def test_unknown_extensions_fall_back_to_other(default_classifier: Classifier, filename: str) -> None:
    assert default_classifier.classify(filename) == "other"


def test_dotfile_without_extension_is_other(default_classifier: Classifier) -> None:
    assert default_classifier.classify(".gitignore") == "other"


def test_compound_extension_matches_longest_suffix() -> None:
    classifier = build({"archives": ["tar.gz", "gz"], "other": []})
    assert classifier.classify("backup.tar.gz") == "archives"


def test_compound_extension_requires_full_match() -> None:
    classifier = build({"archives": ["tar.gz"], "other": []})
    # A plain .gz is not in the map, so it must fall back to "other".
    assert classifier.classify("single.gz") == "other"


def test_disabled_category_falls_back_to_other() -> None:
    classifier = build({"images": ["jpg"], "other": []}, disabled={"images"})
    assert classifier.classify("photo.jpg") == "other"


def test_custom_extension_is_honoured() -> None:
    classifier = build({"documents": ["md"], "other": []})
    assert classifier.classify("readme.md") == "documents"


@pytest.mark.parametrize(
    "filename",
    ["movie.mp4.crdownload", "archive.zip.part", "file.pdf.tmp", "x.msi.partial"],
)
def test_temporary_download_suffixes(default_classifier: Classifier, filename: str) -> None:
    assert default_classifier.is_temporary(filename) is True


def test_normal_file_is_not_temporary(default_classifier: Classifier) -> None:
    assert default_classifier.is_temporary("movie.mp4") is False


def test_extension_case_is_ignored(default_classifier: Classifier) -> None:
    assert default_classifier.classify("PICTURE.JPG") == "images"
    assert default_classifier.classify("Picture.Jpg") == "images"


def test_path_objects_are_accepted(default_classifier: Classifier, tmp_path) -> None:
    assert default_classifier.classify(tmp_path / "x.png") == "images"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("jpg", ".jpg"),
        (".jpg", ".jpg"),
        ("*.jpg", ".jpg"),
        ("  JPG  ", ".jpg"),
        ("", ""),
        ("x" * 40, ""),
    ],
)
def test_normalise_extension(raw: str, expected: str) -> None:
    assert _normalise_extension(raw) == expected


def test_duplicate_extensions_keep_first_category() -> None:
    classifier = build({"images": ["png"], "videos": ["png"], "other": []})
    assert classifier.classify("x.png") == "images"
