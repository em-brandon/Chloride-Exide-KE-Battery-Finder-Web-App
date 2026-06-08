"""Dark sidebar with section navigation."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
)

NAV_ITEMS: list[tuple[str, str]] = [
    ("▣", "Dashboard"),
    ("▶", "Pipeline"),
    ("⊞", "Staging"),
    ("⏱", "Versions"),
    ("⬡", "Quotas"),
]


class SidebarWidget(QWidget):
    nav_changed = pyqtSignal(int)

    def __init__(self, username: str, parent=None) -> None:
        super().__init__(parent)
        self._username = username
        self._buttons: list[QPushButton] = []
        self._staging_badge: QLabel
        self.setObjectName("sidebar")
        self.setFixedWidth(200)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # App title
        title = QLabel("🔋 Battery Finder")
        title.setObjectName("appTitle")
        title.setWordWrap(False)
        layout.addWidget(title)

        # Divider
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: #1f2937; border: none; max-height: 1px;")
        layout.addWidget(sep)

        layout.addSpacing(8)

        # Nav buttons
        for idx, (icon, label) in enumerate(NAV_ITEMS):
            row = QHBoxLayout()
            row.setContentsMargins(8, 0, 8, 0)
            row.setSpacing(0)

            btn = QPushButton(f"  {icon}  {label}")
            btn.setFlat(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(38)

            def _make_handler(i: int):
                def handler() -> None:
                    self._set_active(i)
                return handler

            btn.clicked.connect(_make_handler(idx))
            self._buttons.append(btn)
            row.addWidget(btn)

            if idx == 2:  # Staging badge
                self._staging_badge = QLabel("")
                self._staging_badge.setStyleSheet(
                    "background: #CC0000; color: #ffffff; border-radius: 8px; "
                    "padding: 1px 6px; font-size: 7pt; font-weight: 700;"
                )
                self._staging_badge.setVisible(False)
                row.addWidget(self._staging_badge)
                row.addSpacing(8)

            layout.addLayout(row)

        layout.addStretch()

        # Bottom divider
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("background: #1f2937; border: none; max-height: 1px;")
        layout.addWidget(sep2)

        # User badge
        user_lbl = QLabel(self._username)
        user_lbl.setObjectName("userBadge")
        layout.addWidget(user_lbl)

        role_lbl = QLabel("Pipeline Admin")
        role_lbl.setObjectName("userRole")
        layout.addWidget(role_lbl)

        # Activate first item without emitting
        self._set_active(0, emit=False)

    def _set_active(self, idx: int, emit: bool = True) -> None:
        for i, btn in enumerate(self._buttons):
            btn.setProperty("active", i == idx)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if emit:
            self.nav_changed.emit(idx)

    def set_staging_badge(self, count: int) -> None:
        if count > 0:
            self._staging_badge.setText(str(count))
            self._staging_badge.setVisible(True)
        else:
            self._staging_badge.setVisible(False)
