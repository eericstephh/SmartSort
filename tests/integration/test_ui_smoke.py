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
