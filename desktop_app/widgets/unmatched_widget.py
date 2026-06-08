"""Collapsible unmatched-vehicles table with search."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
)


class UnmatchedWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._expanded = False
        self._all_rows: list[dict] = []
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
        hdr.setStyleSheet("QWidget { background: #fff5f5; border-radius: 14px 14px 0 0; }")
        hdr_layout = QHBoxLayout(hdr)
        hdr_layout.setContentsMargins(16, 12, 16, 12)

        self._toggle_btn = QPushButton("▶  Unmatched Vehicles")
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setStyleSheet(
            "QPushButton { font-size: 10pt; font-weight: 700; color: #CC0000; "
            "border: none; background: transparent; text-align: left; }"
        )
        self._toggle_btn.clicked.connect(self._toggle)
        hdr_layout.addWidget(self._toggle_btn)
        hdr_layout.addStretch()

        self._count_label = QLabel("")
        self._count_label.setStyleSheet("color: #CC0000; font-size: 8pt; font-weight: 700;")
        hdr_layout.addWidget(self._count_label)
        layout.addWidget(hdr)

        # Body
        self._body = QWidget()
        self._body.setVisible(False)
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(12, 10, 12, 12)
        body_layout.setSpacing(8)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Filter make / model…")
        self._search_edit.setFixedWidth(260)
        self._search_edit.textChanged.connect(self._filter)
        body_layout.addWidget(self._search_edit)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Make", "Model", "Year"])
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        body_layout.addWidget(self._table)

        layout.addWidget(self._body)

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        prefix = "▼" if self._expanded else "▶"
        self._toggle_btn.setText(f"{prefix}  Unmatched Vehicles")

    def _filter(self, text: str) -> None:
        q = text.upper()
        filtered = [
            r for r in self._all_rows
            if q in str(r.get("make", "")).upper() or q in str(r.get("model", "")).upper()
        ] if q else self._all_rows
        self._populate(filtered)

    def _populate(self, rows: list[dict]) -> None:
        self._table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self._table.setItem(i, 0, QTableWidgetItem(str(r.get("make", ""))))
            self._table.setItem(i, 1, QTableWidgetItem(str(r.get("model", ""))))
            self._table.setItem(i, 2, QTableWidgetItem(str(r.get("year", ""))))

    def update_data(self, vehicles: list[dict]) -> None:
        self._all_rows = vehicles
        self._count_label.setText(f"{len(vehicles):,} unmatched")
        self._populate(vehicles)
