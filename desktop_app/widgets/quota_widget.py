"""API quota cards grid."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QFrame, QProgressBar, QPushButton,
)

PROVIDER_COLORS = {
    "brave":      "#f59e0b",
    "tavily":     "#6366f1",
    "searxng":    "#22c55e",
    "duckduckgo": "#0ea5e9",
}


class QuotaCard(QWidget):
    def __init__(self, provider: str, made: int, limit: int, pct: float, parent=None) -> None:
        super().__init__(parent)
        color = PROVIDER_COLORS.get(provider.lower(), "#6b7280")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        name = QLabel(provider.capitalize())
        name.setStyleSheet(f"font-weight: 700; color: {color}; font-size: 9pt;")
        layout.addWidget(name)

        if limit == -1:
            usage_text = f"{made:,}  (unlimited)"
        else:
            usage_text = f"{made:,} / {limit:,}"
        usage = QLabel(usage_text)
        usage.setStyleSheet("color: #374151; font-size: 8.5pt;")
        layout.addWidget(usage)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(pct) if limit != -1 else 0)
        bar.setFixedHeight(6)
        bar.setTextVisible(False)
        bar.setStyleSheet(
            f"QProgressBar {{ background: #e2e4e9; border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {color}; border-radius: 3px; }}"
        )
        layout.addWidget(bar)

        if limit != -1:
            pct_label = QLabel(f"{pct:.1f}% used")
            pct_label.setStyleSheet("color: #6b7280; font-size: 7.5pt;")
            layout.addWidget(pct_label)


class QuotaWidget(QWidget):
    def __init__(self, refresh_cb, parent=None) -> None:
        super().__init__(parent)
        self._refresh_cb = refresh_cb
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

        hdr = QHBoxLayout()
        title = QLabel("API Quotas  (this month)")
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

        self._grid = QGridLayout()
        self._grid.setSpacing(8)
        layout.addLayout(self._grid)

        self._empty = QLabel("No quota data available")
        self._empty.setStyleSheet("color: #9ca3af; font-size: 8.5pt;")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty)

    def update_data(self, quotas: list[dict]) -> None:
        # Clear grid
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._empty.setVisible(not quotas)

        cols = 2
        for i, q in enumerate(quotas):
            card = QuotaCard(
                q.get("provider", "?"),
                q.get("calls_made", 0),
                q.get("quota_limit", -1),
                q.get("pct_used", 0.0),
            )
            card.setStyleSheet(
                "QWidget { background: #f8f9fb; border: 1px solid #e2e4e9; border-radius: 10px; }"
            )
            self._grid.addWidget(card, i // cols, i % cols)
