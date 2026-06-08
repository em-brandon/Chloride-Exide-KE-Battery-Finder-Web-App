"""Staging table — filter tabs, inline edit, commit, discard."""
from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabBar, QMessageBox,
    QDialog, QDoubleSpinBox, QComboBox, QDialogButtonBox, QFormLayout,
    QStackedWidget,
)

import db_queries
from widgets.commit_dialog import CommitDialog

FILTER_TABS = ["All", "Valid", "Invalid", "Conflicts"]
FILTER_KEYS = ["all", "valid", "invalid", "conflicts"]


class EditRowDialog(QDialog):
    def __init__(self, row: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Edit: {row.get('make_n','')} {row.get('model_n','')} {row.get('year','')}")
        self.setFixedSize(320, 180)
        self._row_id = row["id"]

        layout = QFormLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        self._ah = QDoubleSpinBox()
        self._ah.setRange(20, 250)
        self._ah.setDecimals(0)
        self._ah.setValue(float(row.get("ah") or 45))
        layout.addRow("Ah:", self._ah)

        self._tech = QComboBox()
        self._tech.addItems(["MF", "AGM", "EFB", "GEL", "WET"])
        current = (row.get("technology") or "MF").upper()
        idx = self._tech.findText(current)
        if idx >= 0:
            self._tech.setCurrentIndex(idx)
        layout.addRow("Technology:", self._tech)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def _save(self) -> None:
        try:
            db_queries.patch_staging(self._row_id, self._ah.value(), self._tech.currentText())
            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))

    def get_row_id(self) -> int:
        return self._row_id


class StagingWidget(QWidget):
    def __init__(
        self,
        username: str,
        refresh_coverage_cb: Callable,
        refresh_versions_cb: Callable,
        clear_badge_cb: Callable | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._username = username
        self._refresh_coverage_cb = refresh_coverage_cb
        self._refresh_versions_cb = refresh_versions_cb
        self._clear_badge_cb = clear_badge_cb or (lambda: None)
        self._filter_idx = 0
        self._page = 1
        self._total = 0
        self._page_size = 50
        self._build()

    def _build(self) -> None:
        frame = QFrame(self)
        frame.setObjectName("card")
        frame.setStyleSheet(
            "QFrame#card { background: #ffffff; border: 1px solid #e2e4e9; border-radius: 14px; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setStyleSheet("QWidget { background: #f4f5f7; border-radius: 14px 14px 0 0; }")
        hdr_layout = QHBoxLayout(hdr)
        hdr_layout.setContentsMargins(16, 12, 16, 12)

        title = QLabel("Staging Results")
        title.setStyleSheet("font-size: 10pt; font-weight: 700; color: #111827;")
        hdr_layout.addWidget(title)

        self._count_chip = QLabel("")
        self._count_chip.setStyleSheet(
            "background: #e0f2fe; color: #0369a1; border-radius: 10px; "
            "padding: 2px 10px; font-size: 8pt; font-weight: 700;"
        )
        hdr_layout.addWidget(self._count_chip)
        hdr_layout.addStretch()

        self._commit_btn = QPushButton("✓  Commit to Master")
        self._commit_btn.setObjectName("commitBtn")
        self._commit_btn.clicked.connect(self._on_commit)
        hdr_layout.addWidget(self._commit_btn)

        self._discard_btn = QPushButton("✕  Discard")
        self._discard_btn.setObjectName("discardBtn")
        self._discard_btn.clicked.connect(self._on_discard)
        hdr_layout.addWidget(self._discard_btn)

        layout.addWidget(hdr)

        # Body stack: page 0 = empty state, page 1 = table
        self._body_stack = QStackedWidget()
        layout.addWidget(self._body_stack, stretch=1)

        # Empty state page (0)
        empty_page = QWidget()
        empty_layout = QVBoxLayout(empty_page)
        empty_layout.setContentsMargins(0, 60, 0, 60)
        empty_lbl = QLabel("No staging rows — run the pipeline to populate.")
        empty_lbl.setStyleSheet("color: #9ca3af; font-size: 10pt;")
        empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_lbl)
        self._body_stack.addWidget(empty_page)

        # Table page (1)
        table_page = QWidget()
        table_layout = QVBoxLayout(table_page)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)

        # Tab bar
        self._tab_bar = QTabBar()
        for tab in FILTER_TABS:
            self._tab_bar.addTab(tab)
        self._tab_bar.currentChanged.connect(self._on_tab_change)
        self._tab_bar.setStyleSheet(
            "QTabBar::tab { padding: 6px 16px; font-size: 9pt; font-weight: 600; color: #6b7280; "
            "border: none; border-bottom: 2px solid transparent; background: transparent; }"
            "QTabBar::tab:selected { color: #CC0000; border-bottom: 2px solid #CC0000; }"
        )
        table_layout.addWidget(self._tab_bar)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: #e2e4e9; border: none; max-height: 1px;")
        table_layout.addWidget(sep)

        self._table = QTableWidget(0, 10)
        self._table.setHorizontalHeaderLabels([
            "Make", "Model", "Year", "Battery Code", "Ah", "Tech",
            "Source", "Valid", "Conflict", "Actions"
        ])
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        table_layout.addWidget(self._table, stretch=1)

        # Pagination
        pg_row = QHBoxLayout()
        pg_row.setContentsMargins(12, 8, 12, 12)
        self._pg_label = QLabel("")
        self._pg_label.setStyleSheet("color: #6b7280; font-size: 8pt;")
        pg_row.addWidget(self._pg_label)
        pg_row.addStretch()

        self._prev_btn = QPushButton("← Prev")
        self._prev_btn.setObjectName("secondaryBtn")
        self._prev_btn.clicked.connect(lambda: self._go_page(self._page - 1))
        pg_row.addWidget(self._prev_btn)

        self._next_btn = QPushButton("Next →")
        self._next_btn.setObjectName("secondaryBtn")
        self._next_btn.clicked.connect(lambda: self._go_page(self._page + 1))
        pg_row.addWidget(self._next_btn)

        table_layout.addLayout(pg_row)
        self._body_stack.addWidget(table_page)

        # Start on empty state; hide action buttons until rows exist
        self._set_has_rows(False)

    def _set_has_rows(self, has: bool) -> None:
        self._body_stack.setCurrentIndex(1 if has else 0)
        self._commit_btn.setVisible(has)
        self._discard_btn.setVisible(has)
        self._count_chip.setVisible(has)

    def _on_tab_change(self, idx: int) -> None:
        self._filter_idx = idx
        self._page = 1
        self.load()

    def _go_page(self, page: int) -> None:
        total_pages = max(1, -(-self._total // self._page_size))
        self._page = max(1, min(page, total_pages))
        self.load()

    def load(self) -> None:
        filter_key = FILTER_KEYS[self._filter_idx]
        try:
            data = db_queries.get_staging(self._page, filter_key, self._page_size)
        except Exception as exc:
            QMessageBox.critical(self, "Error loading staging", str(exc))
            return

        self._total = data["total"]
        self._set_has_rows(self._total > 0)
        items = data["items"]
        total_pages = max(1, -(-self._total // self._page_size))

        self._count_chip.setText(f"{self._total:,} rows")
        self._pg_label.setText(f"Page {self._page} / {total_pages}")
        self._prev_btn.setEnabled(self._page > 1)
        self._next_btn.setEnabled(self._page < total_pages)

        self._table.setRowCount(len(items))
        for row_idx, r in enumerate(items):
            is_valid   = r.get("is_valid", False)
            is_conflict = r.get("conflict", False)

            def _item(text: str, red: bool = False, green: bool = False) -> QTableWidgetItem:
                item = QTableWidgetItem(str(text))
                if red:
                    item.setForeground(Qt.GlobalColor.red)
                elif green:
                    item.setForeground(Qt.GlobalColor.darkGreen)
                return item

            self._table.setItem(row_idx, 0, _item(r.get("make_n", "")))
            self._table.setItem(row_idx, 1, _item(r.get("model_n", "")))
            self._table.setItem(row_idx, 2, _item(str(r.get("year", ""))))
            self._table.setItem(row_idx, 3, _item(r.get("battery_code", "") or "—"))
            self._table.setItem(row_idx, 4, _item(str(r.get("ah", "") or "—")))
            self._table.setItem(row_idx, 5, _item(r.get("technology", "") or "—"))
            self._table.setItem(row_idx, 6, _item(r.get("source", "") or "—"))
            self._table.setItem(row_idx, 7, _item("✓" if is_valid else "✗", red=not is_valid, green=is_valid))
            self._table.setItem(row_idx, 8, _item("!" if is_conflict else "", red=is_conflict))

            # Edit button
            edit_btn = QPushButton("Edit")
            edit_btn.setObjectName("secondaryBtn")
            edit_btn.setFixedHeight(24)
            edit_btn.setStyleSheet("font-size: 8pt; padding: 2px 8px;")

            def _make_edit_handler(row_data: dict):
                def handler():
                    dlg = EditRowDialog(row_data, self)
                    if dlg.exec() == QDialog.DialogCode.Accepted:
                        self.load()
                return handler

            edit_btn.clicked.connect(_make_edit_handler(dict(r)))

            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(4, 2, 4, 2)
            btn_layout.addWidget(edit_btn)
            self._table.setCellWidget(row_idx, 9, btn_widget)

    def _on_commit(self) -> None:
        try:
            pre = db_queries.pre_commit()
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))
            return

        resolutions: dict[int, str] = {}

        if pre["conflict_count"] > 0:
            dlg = CommitDialog(pre["conflicts"], self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            resolutions = dlg.get_resolutions()

        confirm = QMessageBox.question(
            self, "Commit to Master",
            "Write all valid staging rows to the master table?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            result = db_queries.commit_staging(resolutions, self._username)
            QMessageBox.information(
                self, "Committed",
                f"Version #{result['version']} created.\n"
                f"Added: {result['added']}  Updated: {result['updated']}",
            )
            self._set_has_rows(False)
            self._clear_badge_cb()
            self._refresh_coverage_cb()
            self._refresh_versions_cb()
        except Exception as exc:
            QMessageBox.critical(self, "Commit failed", str(exc))

    def _on_discard(self) -> None:
        confirm = QMessageBox.question(
            self, "Discard Staging",
            "Delete all staging rows? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            db_queries.discard_staging()
            self._set_has_rows(False)
            self._clear_badge_cb()
            self._refresh_coverage_cb()
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))
