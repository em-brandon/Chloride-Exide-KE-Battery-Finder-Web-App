"""Collapsible real-time log panel."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QPlainTextEdit, QFrame,
)


class LogPanelWidget(QWidget):
    MAX_LINES = 2000

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._expanded = True
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

        # Header (clickable)
        hdr = QWidget()
        hdr.setCursor(Qt.CursorShape.PointingHandCursor)
        hdr.setStyleSheet(
            "QWidget { background: #f4f5f7; border-radius: 14px 14px 0 0; padding: 10px 16px; }"
        )
        hdr_layout = QHBoxLayout(hdr)
        hdr_layout.setContentsMargins(16, 10, 16, 10)

        title = QLabel("Pipeline Log")
        title.setStyleSheet("font-size: 9.5pt; font-weight: 700; color: #111827;")
        hdr_layout.addWidget(title)
        hdr_layout.addStretch()

        self._toggle_btn = QPushButton("▼")
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setStyleSheet(
            "QPushButton { color: #6b7280; font-size: 9pt; border: none; background: transparent; }"
        )
        self._toggle_btn.clicked.connect(self._toggle)
        hdr_layout.addWidget(self._toggle_btn)

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setFlat(True)
        self._clear_btn.setStyleSheet(
            "QPushButton { color: #6b7280; font-size: 8pt; border: none; background: transparent; }"
            "QPushButton:hover { color: #CC0000; }"
        )
        self._clear_btn.clicked.connect(lambda: self._log.clear())
        hdr_layout.addWidget(self._clear_btn)

        layout.addWidget(hdr)

        # Log body
        self._body = QWidget()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(12, 8, 12, 12)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setFixedHeight(200)
        body_layout.addWidget(self._log)

        layout.addWidget(self._body)

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._toggle_btn.setText("▼" if self._expanded else "▶")

    def append(self, line: str) -> None:
        self._log.appendPlainText(line)
        # trim to MAX_LINES
        doc = self._log.document()
        while doc.blockCount() > self.MAX_LINES:
            cursor = self._log.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.select(cursor.SelectionType.LineUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()
        self._log.moveCursor(self._log.textCursor().MoveOperation.End)
