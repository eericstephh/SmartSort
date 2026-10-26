"""About & diagnostics screen."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..config.defaults import APP_HOMEPAGE, APP_VERSION
from ..i18n import t
from .theme import Palette
from .widgets import Card, MutedLabel, Pill, SectionTitle, title_block

_EXT_ID_RE = re.compile(r"^[a-p]{32}$")
LICENSE_NAME = "MIT"


class AboutPage(QWidget):
    def __init__(self, controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._palette: Palette | None = None
        self._build()
        self.refresh()

    # -- construction ------------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        container = QWidget()
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(28, 24, 28, 28)
        self._layout.setSpacing(16)
        scroll.setWidget(container)

        self._layout.addWidget(title_block(t("about.title"), t("about.subtitle")))
        self._layout.addWidget(self._app_card())
        self._layout.addWidget(self._browser_card())
        self._layout.addWidget(self._diagnostics_card())
        self._layout.addWidget(self._privacy_card())
        self._layout.addStretch(1)

    def _app_card(self) -> QWidget:
        card = Card(padding=20, spacing=8)
        card.add(SectionTitle(t("app.name")))
        row = QHBoxLayout()
        row.addWidget(QLabel(f"{t('about.version')}:"), 0)
        row.addWidget(QLabel(APP_VERSION), 1)
        row.addWidget(QLabel(f"{t('about.license')}:"), 0)
        row.addWidget(QLabel(LICENSE_NAME), 1)
        card.add_layout(row)

        # A user who wants to report a bug or check for a newer build should not
        # have to guess the URL: the About screen is the only place that can
        # tell them where this copy came from.
        project_row = QHBoxLayout()
        project_row.addWidget(QLabel(f"{t('about.project_page')}:"), 0)
        self._project_link = QLabel()
        self._project_link.setOpenExternalLinks(True)
        self._project_link.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self._project_link.setWordWrap(True)
        self._set_project_link()
        project_row.addWidget(self._project_link, 1)
        card.add_layout(project_row)
        self._data_dir_label = MutedLabel(str(self._controller.data_dir))
        self._data_dir_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card.add(self._data_dir_label)

        buttons = QHBoxLayout()
        open_data = QPushButton(t("about.open_data_folder"))
        open_data.clicked.connect(lambda: self._controller.open_path(self._controller.data_dir))
        buttons.addWidget(open_data)
        buttons.addStretch(1)
        card.add_layout(buttons)
        return card

    def _browser_card(self) -> QWidget:
        card = Card(padding=20, spacing=10)
        card.add(SectionTitle(t("about.section_browser")))
        card.add(MutedLabel(t("about.browser_help")))

        id_row = QHBoxLayout()
        id_row.setSpacing(8)
        id_row.addWidget(QLabel(t("about.extension_id")), 0)
        self._extension_edit = QLineEdit()
        self._extension_edit.setPlaceholderText("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        current = self._controller.settings.allowed_extension_ids
        self._extension_edit.setText(", ".join(current))
        id_row.addWidget(self._extension_edit, 1)
        card.add_layout(id_row)

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        self._browser_pills: dict[str, Pill] = {}
        for browser in ("chrome", "edge"):
            status_row.addWidget(QLabel(t(f"about.browser_{browser}")), 0)
            pill = Pill(t("about.not_registered"), "skipped")
            self._browser_pills[browser] = pill
            status_row.addWidget(pill, 0)
            status_row.addSpacing(12)
        status_row.addStretch(1)
        card.add_layout(status_row)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        install = QPushButton(t("about.install"))
        install.setObjectName("primary")
        install.clicked.connect(self._install)
        actions.addWidget(install)

        remove = QPushButton(t("about.uninstall"))
        remove.setObjectName("danger")
        remove.clicked.connect(self._uninstall)
        actions.addWidget(remove)

        open_ext = QPushButton(t("about.open_extension_folder"))
        open_ext.clicked.connect(self._open_extension_folder)
        actions.addWidget(open_ext)
        actions.addStretch(1)
        card.add_layout(actions)
        return card

    def _diagnostics_card(self) -> QWidget:
        card = Card(padding=20, spacing=10)
        card.add(SectionTitle(t("about.section_diagnostics")))

        log_row = QHBoxLayout()
        log_row.addWidget(QLabel(f"{t('about.log_file')}:"), 0)
        self._log_label = MutedLabel(str(self._controller.log_file))
        self._log_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        log_row.addWidget(self._log_label, 1)
        card.add_layout(log_row)

        db_row = QHBoxLayout()
        db_row.addWidget(QLabel(f"{t('about.database')}:"), 0)
        self._db_label = MutedLabel(str(self._controller.context.db_path))
        self._db_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        db_row.addWidget(self._db_label, 1)
        card.add_layout(db_row)

        self._schema_label = MutedLabel("")
        card.add(self._schema_label)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        open_logs = QPushButton(t("about.open_logs"))
        open_logs.clicked.connect(lambda: self._controller.open_path(self._controller.log_file.parent))
        actions.addWidget(open_logs)

        export = QPushButton(t("about.export"))
        export.clicked.connect(self._export_diagnostics)
        actions.addWidget(export)

        backup = QPushButton(t("about.backup"))
        backup.clicked.connect(self._backup)
        actions.addWidget(backup)
        actions.addStretch(1)
        card.add_layout(actions)
        return card

    def _privacy_card(self) -> QWidget:
        card = Card(padding=20, spacing=8)
        card.add(SectionTitle(t("about.section_privacy")))
        card.add(MutedLabel(t("about.privacy_text")))
        return card

    # -- state -------------------------------------------------------------
    def refresh(self) -> None:
        info = self._controller.browser_registration()
        status = info.get("status", {})
        for browser, pill in self._browser_pills.items():
            registered = bool(status.get(browser))
            if registered:
                pill.set_status("organized", t("about.registered"), self._palette)
                pill.setToolTip(str(status.get(browser)))
            else:
                pill.set_status("skipped", t("about.not_registered"), self._palette)
                pill.setToolTip("")
        schema = self._controller.context.db.scalar("PRAGMA user_version", default=0)
        self._schema_label.setText(f"{t('about.schema')}: {schema}")

    def _parse_extension_ids(self) -> list[str] | None:
        raw = self._extension_edit.text().replace(";", ",")
        candidates = [part.strip().lower() for part in raw.split(",") if part.strip()]
        for candidate in candidates:
            if not _EXT_ID_RE.match(candidate):
                QMessageBox.warning(
                    self, t("common.warning"), t("about.extension_id_invalid")
                )
                return None
        return candidates

    def _install(self) -> None:
        ids = self._parse_extension_ids()
        if ids is None:
            return
        if not ids:
            QMessageBox.warning(self, t("common.warning"), t("about.extension_id_invalid"))
            return
        result = self._controller.install_browser_integration(ids)
        if result.ok:
            QMessageBox.information(self, t("about.section_browser"), t("about.install_ok"))
        else:
            QMessageBox.warning(
                self,
                t("common.error"),
                t("about.install_failed", reason="; ".join(result.errors) or "unknown"),
            )
        self.refresh()

    def _uninstall(self) -> None:
        answer = QMessageBox.question(
            self,
            t("about.uninstall"),
            t("about.uninstall") + "?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        result = self._controller.remove_browser_integration()
        if result.ok:
            QMessageBox.information(self, t("about.section_browser"), t("about.uninstall_ok"))
        else:
            QMessageBox.warning(
                self,
                t("common.error"),
                t("about.install_failed", reason="; ".join(result.errors) or "unknown"),
            )
        self.refresh()

    def _open_extension_folder(self) -> None:
        from ..browser import registry

        folder = registry.open_extension_folder()
        if folder is None:
            QMessageBox.information(
                self, t("about.section_browser"), t("about.extension_folder_missing")
            )
            return
        self._controller.open_path(folder)

    def _export_diagnostics(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        default = str(Path.home() / f"smartsort-diagnostics-{stamp}.zip")
        target, _filter = QFileDialog.getSaveFileName(
            self, t("about.export"), default, "Zip archive (*.zip)"
        )
        if not target:
            return
        try:
            path = self._controller.export_diagnostics(Path(target))
        except Exception as exc:  # pragma: no cover - environmental
            QMessageBox.warning(
                self, t("common.error"), t("errors.operation_failed", reason=str(exc))
            )
            return
        QMessageBox.information(self, t("about.export"), t("about.export_done", path=str(path)))

    def _backup(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        default = str(Path.home() / f"smartsort-backup-{stamp}.zip")
        target, _filter = QFileDialog.getSaveFileName(
            self, t("about.backup"), default, "Backup (*.zip *.db)"
        )
        if not target:
            return
        try:
            path = self._controller.backup_state(Path(target))
        except Exception as exc:  # pragma: no cover - environmental
            QMessageBox.warning(
                self, t("common.error"), t("errors.operation_failed", reason=str(exc))
            )
            return
        QMessageBox.information(self, t("about.backup"), t("about.backup_done", path=str(path)))

    # -- theming -----------------------------------------------------------
    def _set_project_link(self) -> None:
        """Colour the link from the palette.

        An ``<a>`` tag without a colour is painted with Qt's default link
        colour, which is a dark blue that disappears on the dark theme's
        background. The label is rebuilt on every theme change instead.
        """
        colour = self._palette.accent if self._palette is not None else "#2563eb"
        self._project_link.setText(
            f'<a style="color:{colour};" href="{APP_HOMEPAGE}">{APP_HOMEPAGE}</a>'
        )

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._set_project_link()
        self.refresh()

    def retranslate(self) -> None:
        self.refresh()
