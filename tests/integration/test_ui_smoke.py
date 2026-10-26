"""UI construction smoke tests.

These do not try to look like a human tester; they verify that every screen can
be built, populated, re-themed and re-translated without raising, which is the
class of bug that only shows up when a real window opens.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pytestqt")

from smartsort.app.bootstrap import create_context  # noqa: E402


@pytest.fixture
def window(tmp_path: Path, monkeypatch, qtbot):
    from smartsort.app.ui.controller import AppController
    from smartsort.app.ui.main_window import MainWindow

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("SMARTSORT_DATA_DIR", str(data_dir))
    context = create_context(data_dir, setup_logs=False)
    context.settings.destination_dir = str(tmp_path / "SmartSort")
    (tmp_path / "SmartSort").mkdir()

    controller = AppController(context)
    main_window = MainWindow(controller)
    qtbot.addWidget(main_window)
    try:
        yield main_window, controller
    finally:
        main_window.quit_application()
        context.close()


def test_window_builds_with_all_pages(window) -> None:
    main_window, _controller = window
    assert main_window._stack.count() == 5
    assert set(main_window._pages) == {
        "dashboard",
        "settings",
        "history",
        "categories",
        "about",
    }


def test_every_page_can_be_visited(window, qtbot) -> None:
    main_window, _controller = window
    for key in ("settings", "history", "categories", "about", "dashboard"):
        main_window.navigate(key)
        qtbot.wait(30)
        assert main_window._stack.currentIndex() >= 0


def test_dashboard_refresh_with_no_history(window) -> None:
    main_window, _controller = window
    main_window.navigate("dashboard")
    main_window._pages["dashboard"].refresh()


def test_theme_switch(window, qtbot) -> None:
    main_window, controller = window
    main_window.apply_theme("dark")
    qtbot.wait(20)
    assert controller.settings.theme == "dark"
    main_window.apply_theme("light")
    qtbot.wait(20)
    assert controller.settings.theme == "light"


def test_language_switch_rebuilds_pages(window, qtbot) -> None:
    main_window, controller = window
    controller.set_language("fa")
    # The rebuild is deferred through a zero-delay timer.
    qtbot.wait(120)
    assert main_window._stack.count() == 5
    controller.set_language("en")
    qtbot.wait(120)
    assert main_window._stack.count() == 5


def test_history_page_loads_recorded_operations(window, qtbot, tmp_path: Path) -> None:
    from tests.conftest import make_file

    main_window, controller = window
    source = make_file(tmp_path / "Downloads", "photo.jpg", b"x")
    result = controller.organize_now(str(source))
    assert result["status"] == "organized"

    main_window.navigate("history")
    page = main_window._pages["history"]
    page.reload()
    qtbot.wait(30)
    assert page._table.rowCount() == 1


def test_categories_page_lists_all_categories(window, qtbot) -> None:
    main_window, _controller = window
    main_window.navigate("categories")
    page = main_window._pages["categories"]
    qtbot.wait(20)
    assert page._table.rowCount() == 7


def test_about_page_shows_the_project_link(window) -> None:
    """A user who wants to report a bug needs a URL that actually resolves."""
    from smartsort.app.config.defaults import APP_HOMEPAGE

    main_window, _controller = window
    page = main_window._pages["about"]
    assert APP_HOMEPAGE in page._project_link.text()
    assert page._project_link.openExternalLinks() is True


def test_project_link_is_readable_in_both_themes(window) -> None:
    """An <a> tag with no colour gets Qt's default link blue.

    That blue is unreadable on the dark background, so the label has to take
    its colour from the palette and be rebuilt when the theme changes.
    """
    from smartsort.app.ui.theme import DARK, LIGHT

    main_window, _controller = window
    page = main_window._pages["about"]

    page.apply_palette(DARK)
    assert DARK.accent in page._project_link.text()

    page.apply_palette(LIGHT)
    assert LIGHT.accent in page._project_link.text()
    assert DARK.accent not in page._project_link.text()


def test_skip_duplicates_toggle_follows_the_stored_setting(window) -> None:
    main_window, controller = window
    page = main_window._pages["settings"]

    assert page._skip_duplicates.is_checked() is False

    controller.settings.set("skip_duplicate_content", True)
    page.load()
    assert page._skip_duplicates.is_checked() is True


def test_categories_page_grows_when_a_category_is_added(window, qtbot) -> None:
    main_window, controller = window
    page = main_window._pages["categories"]
    before = page._table.rowCount()

    controller.add_category("Design", ["psd"])
    page.reload()
    qtbot.wait(20)

    assert page._table.rowCount() == before + 1
    # Built-in rows offer no rename or delete; the new row does.
    assert page._table.cellWidget(0, 4) is None
    assert page._table.cellWidget(page._table.rowCount() - 1, 4) is not None


def test_controller_reports_extension_conflicts(window) -> None:
    _main_window, controller = window
    assert controller.category_conflicts(["png"]) == {"png": "Images"}
    assert controller.category_conflicts(["psd"]) == {}
    # A category never conflicts with itself.
    assert controller.category_conflicts(["png"], exclude_id="images") == {}
