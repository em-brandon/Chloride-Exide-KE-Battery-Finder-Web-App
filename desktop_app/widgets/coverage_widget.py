"""Coverage stats + donut chart."""
from __future__ import annotations

import math

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
)


class DonutChart(QWidget):
    """Custom QPainter donut chart showing coverage %."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pct = 0.0
        self.setMinimumSize(120, 120)
        self.setMaximumSize(140, 140)

    def set_pct(self, pct: float) -> None:
        self._pct = max(0.0, min(100.0, pct))
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        ring = 14
        margin = ring // 2 + 4
        rect_size = min(w, h) - 2 * margin

        x = (w - rect_size) // 2
        y = (h - rect_size) // 2

        from PyQt6.QtCore import QRectF
        rect = QRectF(x, y, rect_size, rect_size)

        # Background ring
        pen_bg = QPen(QColor("#e2e4e9"), ring)
        pen_bg.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(pen_bg)
        p.drawArc(rect, 0, 360 * 16)

        # Coverage arc (green)
        if self._pct > 0:
            pen_fg = QPen(QColor("#22c55e"), ring)
            pen_fg.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(pen_fg)
            span = int(self._pct / 100 * 360 * 16)
            p.drawArc(rect, 90 * 16, -span)

        # Centre text
        p.setPen(QPen(QColor("#111827")))
        pct_font = QFont("Segoe UI", 11, QFont.Weight.Bold)
        p.setFont(pct_font)
        cx, cy = w // 2, h // 2
        p.drawText(
            QRectF(x, y + rect_size * 0.25, rect_size, rect_size * 0.35),
            Qt.AlignmentFlag.AlignCenter,
            f"{self._pct:.1f}%",
        )

        p.setPen(QPen(QColor("#6b7280")))
        small_font = QFont("Segoe UI", 7, QFont.Weight.Bold)
        p.setFont(small_font)
        p.drawText(
            QRectF(x, cy + 6, rect_size, 20),
            Qt.AlignmentFlag.AlignCenter,
            "COVERED",
        )


def _stat_row(label: str, value: str, accent: str = "#111827") -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lbl = QLabel(label)
    lbl.setStyleSheet("color: #6b7280; font-size: 8pt;")
    lay.addWidget(lbl)
    lay.addStretch()
    val = QLabel(value)
    val.setStyleSheet(f"font-weight: 700; color: {accent}; font-size: 9pt;")
    lay.addWidget(val)
    return w


class CoverageWidget(QWidget):
    def __init__(self, refresh_cb, parent=None) -> None:
        super().__init__(parent)
        self._refresh_cb = refresh_cb
        self._data: dict = {}
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
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("Coverage")
        title.setStyleSheet("font-size: 10pt; font-weight: 700; color: #111827;")
        hdr.addWidget(title)
        hdr.addStretch()
        refresh_btn = QPushButton("↺")
        refresh_btn.setFlat(True)
        refresh_btn.setStyleSheet(
            "QPushButton { color: #6b7280; font-size: 11pt; border: none; background: transparent; }"
            "QPushButton:hover { color: #CC0000; }"
        )
        refresh_btn.clicked.connect(self._refresh_cb)
        hdr.addWidget(refresh_btn)
        layout.addLayout(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: #e2e4e9; border: none; max-height: 1px;")
        layout.addWidget(sep)

        # Donut + stats side-by-side
        mid = QHBoxLayout()
        self._donut = DonutChart()
        mid.addWidget(self._donut, 0, Qt.AlignmentFlag.AlignVCenter)

        stats_col = QVBoxLayout()
        stats_col.setSpacing(4)
        self._stat_widgets: dict[str, QLabel] = {}

        for key, label, accent in [
            ("matched",       "Matched",        "#22c55e"),
            ("unmatched",     "Unmatched",      "#CC0000"),
            ("total",         "Total combos",   "#111827"),
            ("master_count",  "Master records", "#6366f1"),
            ("staging_count", "In staging",     "#f59e0b"),
            ("web_cache_size","Cache entries",  "#0891b2"),
        ]:
            row = _stat_row(label, "—", accent)
            val_label = row.findChildren(QLabel)[1]
            self._stat_widgets[key] = val_label
            stats_col.addWidget(row)

        mid.addLayout(stats_col)
        layout.addLayout(mid)

    def update_data(self, data: dict) -> None:
        self._data = data
        pct = data.get("pct_matched", 0.0)
        self._donut.set_pct(pct)
        for key, lbl in self._stat_widgets.items():
            val = data.get(key, "—")
            lbl.setText(f"{val:,}" if isinstance(val, int) else str(val))
