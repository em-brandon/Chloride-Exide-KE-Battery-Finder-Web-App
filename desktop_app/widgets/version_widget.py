"""Collapsible version history table + changelog dialog."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QDialog, QScrollArea,
    QMessageBox,
)

import db_queries


class ChangelogDialog(QDialog):
    def __init__(self, version_id: str, version_num: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Changelog — Version #{version_num}")
        self.setMinimumSize(700, 450)
        self._build(version_id)

    def _build(self, version_id: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        try:
            entries = db_queries.get_changelog(version_id)
        except Exception as exc:
            layout.addWidget(QLabel(f"Error loading changelog: {exc}"))
            return

        TYPE_COLORS = {
            "added":   ("#f0fdf4", "#15803d"),
            "updated": ("#eff6ff", "#1d4ed8"),
            "removed": ("#fff5f5", "#CC0000"),
        }

        table = QTableWidget(len(entries), 6)
        table.setHorizontalHeaderLabels(
            ["Type", "Make", "Model", "Year", "Old", "New"]
        )
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)

        for i, e in enumerate(entries):
            ct = e.get("change_type", "")
            bg, fg = TYPE_COLORS.get(ct, ("#ffffff", "#111827"))

            def _item(text: str) -> QTableWidgetItem:
                item = QTableWidgetItem(str(text))
                item.setBackground(Qt.GlobalColor.transparent)
                return item

            badge = QTableWidgetItem(ct.upper())
            badge.setForeground(Qt.GlobalColor.black)

            old_v = e.get("old_values") or {}
            new_v = e.get("new_values") or {}

            old_str = f"{old_v.get('ah','?')} Ah / {old_v.get('technology','?')}" if old_v else "—"
            new_str = f"{new_v.get('ah','?')} Ah / {new_v.get('technology','?')}" if new_v else "—"

            for col, text in [
                (0, ct.upper()), (1, e.get("make_n","")), (2, e.get("model_n","")),
                (3, str(e.get("year",""))), (4, old_str), (5, new_str),
            ]:
                table.setItem(i, col, _item(text))

        layout.addWidget(table)

        close_btn = QPushButton("Close")
        close_btn.setObjectName("secondaryBtn")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignRight)


class VersionWidget(QWidget):
    def __init__(self, username: str, refresh_coverage_cb, parent=None) -> None:
        super().__init__(parent)
        self._username = username
        self._refresh_coverage_cb = refresh_coverage_cb
        self._expanded = True
        self._page = 1
        self._total = 0
        self._page_size = 20
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
        hdr.setCursor(Qt.CursorShape.PointingHandCursor)
        hdr.setStyleSheet(
            "QWidget { background: #f4f5f7; border-radius: 14px 14px 0 0; }"
        )
        hdr_layout = QHBoxLayout(hdr)
        hdr_layout.setContentsMargins(16, 12, 16, 12)

        self._toggle_btn = QPushButton("▼  Version History")
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setStyleSheet(
            "QPushButton { font-size: 10pt; font-weight: 700; color: #111827; "
            "border: none; background: transparent; text-align: left; }"
        )
        self._toggle_btn.clicked.connect(self._toggle)
        hdr_layout.addWidget(self._toggle_btn)
        hdr_layout.addStretch()

        refresh_btn = QPushButton("↺")
        refresh_btn.setFlat(True)
        refresh_btn.setStyleSheet(
            "QPushButton { color: #6b7280; font-size: 11pt; border: none; background: transparent; }"
            "QPushButton:hover { color: #CC0000; }"
        )
        refresh_btn.clicked.connect(self.load)
        hdr_layout.addWidget(refresh_btn)
        layout.addWidget(hdr)

        # Body
        self._body = QWidget()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["#", "Committed At", "By", "Records", "Conflicts", "Notes", "Actions"]
        )
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        body_layout.addWidget(self._table)

        # Pagination
        pg_row = QHBoxLayout()
        pg_row.setContentsMargins(12, 8, 12, 12)
        self._pg_label = QLabel("Page 1")
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

        body_layout.addLayout(pg_row)
        layout.addWidget(self._body)

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        prefix = "▼" if self._expanded else "▶"
        self._toggle_btn.setText(f"{prefix}  Version History")

    def _go_page(self, page: int) -> None:
        total_pages = max(1, -(-self._total // self._page_size))
        self._page = max(1, min(page, total_pages))
        self.load()

    def load(self) -> None:
        try:
            data = db_queries.get_versions(self._page, self._page_size)
        except Exception as exc:
            return
        self._total = data["total"]
        items = data["items"]
        total_pages = max(1, -(-self._total // self._page_size))
        self._pg_label.setText(f"Page {self._page} / {total_pages}  ·  {self._total} versions")
        self._prev_btn.setEnabled(self._page > 1)
        self._next_btn.setEnabled(self._page < total_pages)

        self._table.setRowCount(len(items))
        for row_idx, v in enumerate(items):
            ver_id  = str(v.get("id", ""))
            ver_num = v.get("version_number", "")
            committed_at = str(v.get("committed_at", ""))[:19].replace("T", " ")

            def _item(text: str) -> QTableWidgetItem:
                return QTableWidgetItem(str(text))

            self._table.setItem(row_idx, 0, _item(f"#{ver_num}"))
            self._table.setItem(row_idx, 1, _item(committed_at))
            self._table.setItem(row_idx, 2, _item(v.get("committed_by", "—")))
            self._table.setItem(row_idx, 3, _item(str(v.get("committed_count", 0))))
            self._table.setItem(row_idx, 4, _item(str(v.get("conflict_count", 0))))
            self._table.setItem(row_idx, 5, _item(v.get("notes", "") or ""))

            # Action buttons
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(4, 2, 4, 2)
            btn_layout.setSpacing(6)

            log_btn = QPushButton("Changelog")
            log_btn.setObjectName("secondaryBtn")
            log_btn.setFixedHeight(24)
            log_btn.setStyleSheet("font-size: 8pt; padding: 2px 8px;")

            def _make_log_handler(vid: str, vnum: int):
                def handler():
                    dlg = ChangelogDialog(vid, vnum, self)
                    dlg.exec()
                return handler

            log_btn.clicked.connect(_make_log_handler(ver_id, ver_num))
            btn_layout.addWidget(log_btn)

            revert_btn = QPushButton("Revert")
            revert_btn.setObjectName("discardBtn")
            revert_btn.setFixedHeight(24)
            revert_btn.setStyleSheet("font-size: 8pt; padding: 2px 8px;")

            def _make_revert_handler(vid: str, vnum: int):
                def handler():
                    confirm = QMessageBox.question(
                        self, "Revert Version",
                        f"Create a new version that reverts version #{vnum}?\n"
                        "This will not delete any version history.",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    )
                    if confirm == QMessageBox.StandardButton.Yes:
                        try:
                            new_ver = db_queries.revert_version(vid, self._username)
                            QMessageBox.information(
                                self, "Reverted",
                                f"Version #{vnum} reverted as version #{new_ver}.",
                            )
                            self.load()
                            self._refresh_coverage_cb()
                        except Exception as exc:
                            QMessageBox.critical(self, "Error", str(exc))
                return handler

            revert_btn.clicked.connect(_make_revert_handler(ver_id, ver_num))
            btn_layout.addWidget(revert_btn)

            self._table.setCellWidget(row_idx, 6, btn_widget)
