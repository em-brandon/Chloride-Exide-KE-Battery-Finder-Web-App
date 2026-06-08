"""Collapsible matched-records table with search + pagination."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
)

import db_queries


class MatchedWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._expanded = False
        self._page = 1
        self._total = 0
        self._page_size = 50
        self._search = ""
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
        hdr.setStyleSheet("QWidget { background: #f4f5f7; border-radius: 14px 14px 0 0; }")
        hdr_layout = QHBoxLayout(hdr)
        hdr_layout.setContentsMargins(16, 12, 16, 12)

        self._toggle_btn = QPushButton("▶  Matched Records")
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setStyleSheet(
            "QPushButton { font-size: 10pt; font-weight: 700; color: #111827; "
            "border: none; background: transparent; text-align: left; }"
        )
        self._toggle_btn.clicked.connect(self._toggle)
        hdr_layout.addWidget(self._toggle_btn)
        hdr_layout.addStretch()

        self._count_label = QLabel("")
        self._count_label.setStyleSheet("color: #6b7280; font-size: 8pt;")
        hdr_layout.addWidget(self._count_label)
        layout.addWidget(hdr)

        # Body
        self._body = QWidget()
        self._body.setVisible(False)
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(12, 10, 12, 12)
        body_layout.setSpacing(8)

        # Search bar
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search make / model…")
        self._search_edit.setFixedWidth(260)
        self._search_edit.textChanged.connect(self._on_search)
        body_layout.addWidget(self._search_edit)

        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["Make", "Model", "Year", "Ah", "Technology", "Source", "Validated At"]
        )
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        body_layout.addWidget(self._table)

        # Pagination
        pg_row = QHBoxLayout()
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

        body_layout.addLayout(pg_row)
        layout.addWidget(self._body)

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        prefix = "▼" if self._expanded else "▶"
        self._toggle_btn.setText(f"{prefix}  Matched Records")
        if self._expanded and self._table.rowCount() == 0:
            self.load()

    def _on_search(self, text: str) -> None:
        self._search = text
        self._page = 1
        self.load()

    def _go_page(self, page: int) -> None:
        total_pages = max(1, -(-self._total // self._page_size))
        self._page = max(1, min(page, total_pages))
        self.load()

    def load(self) -> None:
        try:
            data = db_queries.get_matched(self._page, self._search, self._page_size)
        except Exception:
            return

        self._total = data["total"]
        items = data["items"]
        total_pages = max(1, -(-self._total // self._page_size))

        self._count_label.setText(f"{self._total:,} records")
        self._pg_label.setText(f"Page {self._page} / {total_pages}")
        self._prev_btn.setEnabled(self._page > 1)
        self._next_btn.setEnabled(self._page < total_pages)

        self._table.setRowCount(len(items))
        for row_idx, r in enumerate(items):
            validated = str(r.get("validated_at", "") or "")[:19].replace("T", " ")
            for col, text in [
                (0, r.get("make_n", "")),
                (1, r.get("model_n", "")),
                (2, str(r.get("year", ""))),
                (3, str(r.get("ah", ""))),
                (4, r.get("technology", "")),
                (5, r.get("source", "")),
                (6, validated),
            ]:
                self._table.setItem(row_idx, col, QTableWidgetItem(text))
