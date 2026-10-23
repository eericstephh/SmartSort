"""The translation catalogue must stay complete."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from smartsort.app import i18n

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "smartsort"
_KEY_PATTERN = re.compile(r'(?<![\w.])t\(\s*"([A-Za-z0-9_.]+)"')
_DYNAMIC_PATTERN = re.compile(r't\(\s*f"([A-Za-z0-9_.]+)\{')


def _used_keys() -> set[str]:
    keys: set[str] = set()
    for path in PACKAGE_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        keys.update(_KEY_PATTERN.findall(text))
    return keys


def test_every_used_key_exists() -> None:
    missing = sorted(key for key in _used_keys() if not i18n.has_key(key))
    assert missing == [], f"missing translation keys: {missing}"


def test_persian_catalogue_is_complete() -> None:
    assert i18n.missing_keys("fa") == []


def test_unknown_key_falls_back_to_itself() -> None:
    assert i18n.t("does.not.exist") == "does.not.exist"


def test_language_switch_changes_output() -> None:
    i18n.set_language("en")
    english = i18n.t("nav.dashboard")
    i18n.set_language("fa")
    persian = i18n.t("nav.dashboard")
    assert english != persian
    i18n.set_language("en")


def test_rtl_flag() -> None:
    assert i18n.is_rtl("fa") is True
    assert i18n.is_rtl("en") is False


def test_placeholder_formatting() -> None:
    i18n.set_language("en")
    assert "5" in i18n.t("history.count", count=5)


def test_unknown_language_is_ignored() -> None:
    i18n.set_language("en")
    i18n.set_language("klingon")
    assert i18n.current_language() == "en"


def test_dynamic_key_families_exist() -> None:
    """Keys built with f-strings must still exist for every variant."""
    assert i18n.has_key("about.browser_chrome")
    assert i18n.has_key("about.browser_edge")
    for status in ("organized", "failed", "skipped", "duplicate", "undone"):
        assert i18n.has_key(f"status.{status}")
