"""Main window: sidebar navigation, pages, tray integration."""

from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from ..config.defaults import APP_NAME, APP_VERSION
from ..i18n import is_rtl, t
from .about_page import AboutPage
from .branding import app_icon, tray_pixmap
from .categories_page import CategoriesPage
from .controller import AppController
from .dashboard import DashboardPage
from .history_page import HistoryPage
from .settings_page import SettingsPage
from .theme import palette_for, stylesheet

logger = logging.getLogger(__name__)

NAV_ITEMS = (
    ("dashboard", "nav.dashboard"),
    ("settings", "nav.settings"),
    ("history", "nav.history"),
    ("categories", "nav.categories"),
    ("about", "nav.about"),
)


def _button_text(text: str) -> str:
    """Escape '&' so QPushButton does not swallow it as a mnemonic."""
    return text.replace("&", "&&")


class MainWindow(QMainWindow):
    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self._controller = controller
        self._quitting = False
        self._pages: dict[str, QWidget] = {}
        self._nav_buttons: dict[str, QPushButton] = {}

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1060, 720)
        self.setMinimumSize(880, 600)

        self._build_ui()
        self._build_tray()
        self._connect_signals()
        self.apply_theme(controller.settings.theme, persist=False)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(10_000)
        self._refresh_timer.timeout.connect(self.refresh)
        self._refresh_timer.start()
        self.refresh()

    # -- UI ----------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_sidebar())

        self._stack = QStackedWidget()
        layout.addWidget(self._stack, 1)
        self.setCentralWidget(root)

        self._status_bar = QStatusBar()
        self._status_label = QLabel("")
        self._status_label.setObjectName("statusBarLabel")
        self._status_bar.addWidget(self._status_label, 1)
        self.setStatusBar(self._status_bar)

        self._install_pages()

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(226)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(6)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        icon_label = QLabel()
        icon_label.setPixmap(app_icon().pixmap(QSize(30, 30)))
        brand_row.addWidget(icon_label)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        name = QLabel(APP_NAME)
        name.setObjectName("brandName")
        tag = QLabel(t("app.tagline"))
        tag.setObjectName("brandTag")
        brand_text.addWidget(name)
        brand_text.addWidget(tag)
        brand_row.addLayout(brand_text, 1)
        layout.addLayout(brand_row)
        layout.addSpacing(18)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        for index, (key, label_key) in enumerate(NAV_ITEMS):
            button = QPushButton(_button_text(t(label_key)))
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, i=index: self._stack.setCurrentIndex(i))
            self._nav_group.addButton(button, index)
            layout.addWidget(button)
            self._nav_buttons[key] = button
        self._nav_buttons["dashboard"].setChecked(True)

        layout.addStretch(1)
        version = QLabel(f"v{APP_VERSION}")
        version.setObjectName("muted")
        layout.addWidget(version)
        return sidebar

    def _install_pages(self) -> None:
        while self._stack.count():
            widget = self._stack.widget(0)
            self._stack.removeWidget(widget)
            if hasattr(widget, "shutdown"):
                try:
                    widget.shutdown()
                except Exception:  # pragma: no cover - defensive
                    logger.debug("page shutdown failed", exc_info=True)
            widget.deleteLater()

        self._pages = {
            "dashboard": DashboardPage(self._controller),
            "settings": SettingsPage(self._controller),
            "history": HistoryPage(self._controller),
            "categories": CategoriesPage(self._controller),
            "about": AboutPage(self._controller),
        }
        for key, _label in NAV_ITEMS:
            page = self._pages[key]
            self._stack.addWidget(page)
            if isinstance(page, DashboardPage):
                page.navigate_requested.connect(self.navigate)
            if isinstance(page, SettingsPage):
                page.theme_changed.connect(self.apply_theme)

    def _build_tray(self) -> None:
        self._tray: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.info("system tray is not available")
            return
        tray = QSystemTrayIcon(tray_pixmap(64), self)
        tray.setToolTip(APP_NAME)
        self._tray_menu = QMenu()
        self._tray_show = QAction(t("tray.show"), self)
        self._tray_show.triggered.connect(self._show_from_tray)
        self._tray_pause = QAction(t("tray.pause"), self)
        self._tray_pause.triggered.connect(self._toggle_pause_from_tray)
        self._tray_quit = QAction(t("tray.quit"), self)
        self._tray_quit.triggered.connect(self.quit_application)
        self._tray_menu.addAction(self._tray_show)
        self._tray_menu.addAction(self._tray_pause)
        self._tray_menu.addSeparator()
        self._tray_menu.addAction(self._tray_quit)
        tray.setContextMenu(self._tray_menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        self._tray = tray

    def _connect_signals(self) -> None:
        self._controller.operations_changed.connect(self.refresh)
        self._controller.settings_changed.connect(self.refresh)
        self._controller.status_changed.connect(self.refresh)
        self._controller.language_changed.connect(self._on_language_changed)
        self._controller.notification.connect(self._on_notification)
        self._controller.browser_activity.connect(lambda _browser: self.refresh())

    # -- navigation --------------------------------------------------------
    def navigate(self, key: str) -> None:
        for index, (name, _label) in enumerate(NAV_ITEMS):
            if name == key:
                self._stack.setCurrentIndex(index)
                button = self._nav_buttons.get(key)
                if button is not None:
                    button.setChecked(True)
                page = self._pages.get(key)
                if hasattr(page, "reload"):
                    page.reload()
                elif hasattr(page, "refresh"):
                    page.refresh()
                return

    # -- theming -----------------------------------------------------------
    def apply_theme(self, theme: str, *, persist: bool = True) -> None:
        palette = palette_for(theme)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(stylesheet(palette))
        if persist:
            self._controller.settings.set("theme", theme)
        for page in self._pages.values():
            if hasattr(page, "apply_palette"):
                page.apply_palette(palette)
        self.refresh()

    def _on_language_changed(self, language: str) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setLayoutDirection(Qt.RightToLeft if is_rtl(language) else Qt.LeftToRight)
        # Rebuild the pages so every string is re-translated. Deferred so the
        # settings widget that triggered this can finish its own signal first.
        QTimer.singleShot(0, self._rebuild_ui)

    def _rebuild_ui(self) -> None:
        current = self._stack.currentIndex()
        self._install_pages()
        self._stack.setCurrentIndex(max(0, min(current, self._stack.count() - 1)))
        for index, (key, label_key) in enumerate(NAV_ITEMS):
            button = self._nav_buttons.get(key)
            if button is not None:
                button.setText(_button_text(t(label_key)))
        if self._tray is not None:
            self._tray_show.setText(t("tray.show"))
            self._tray_quit.setText(t("tray.quit"))
            self._update_tray_pause_text()
        self.apply_theme(self._controller.settings.theme, persist=False)

    # -- refresh -----------------------------------------------------------
    def refresh(self) -> None:
        stats = self._controller.stats()
        destination = stats.get("destination") or t("dashboard.destination_none")
        paused = stats.get("paused")
        state = t("status.paused") if paused else (
            t("status.active") if stats.get("auto_organize") and stats.get("destination") else t("status.off")
        )
        self._status_label.setText(f"{state}  ·  {destination}")
        self._update_tray_pause_text()

        page = self._pages.get("dashboard")
        if page is not None and hasattr(page, "refresh") and self._stack.currentIndex() == 0:
            page.refresh()

    def _update_tray_pause_text(self) -> None:
        if self._tray is None:
            return
        paused = self._controller.is_paused()
        self._tray_pause.setText(t("tray.resume") if paused else t("tray.pause"))

    # -- tray --------------------------------------------------------------
    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self._show_from_tray()

    def _toggle_pause_from_tray(self) -> None:
        self._controller.toggle_paused()
        self.refresh()

    def _on_notification(self, kind: str, payload: str) -> None:
        if self._tray is None or not self._tray.isVisible():
            return
        name, _, category = payload.partition("|")
        body = t("notify.organized_body", name=name, category=category)
        self._tray.showMessage(
            t("notify.organized_title"), body, QSystemTrayIcon.Information, 4000
        )

    # -- window events -----------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._quitting or not self._controller.settings.close_to_tray or self._tray is None:
            event.accept()
            self.quit_application()
            return
        event.ignore()
        self.hide()
        if not self._controller.settings.get("_tray_hint_shown", False):
            self._tray.showMessage(
                APP_NAME,
                t("tray.still_running"),
                QSystemTrayIcon.Information,
                4000,
            )
            self._controller.settings.set("_tray_hint_shown", True)

    def changeEvent(self, event) -> None:  # noqa: N802
        if (
            event.type() == event.Type.WindowStateChange
            and self.isMinimized()
            and self._controller.settings.minimize_to_tray
            and self._tray is not None
        ):
            QTimer.singleShot(0, self.hide)
        super().changeEvent(event)

    def quit_application(self) -> None:
        self._quitting = True
        self._refresh_timer.stop()
        for page in self._pages.values():
            if hasattr(page, "shutdown"):
                try:
                    page.shutdown()
                except Exception:  # pragma: no cover
                    pass
        if self._tray is not None:
            self._tray.hide()
        self._controller.shutdown()
        QApplication.quit()
