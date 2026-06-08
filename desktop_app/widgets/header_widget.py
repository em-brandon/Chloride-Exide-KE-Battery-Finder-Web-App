"""Top header bar — title, username, pipeline status chip."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel

_STATUS_STYLES: dict[str, tuple[str, str]] = {
    "idle":       ("Idle",        "background: rgba(255,255,255,0.20); color: #ffffff;"),
    "running":    ("Running…",    "background: #22c55e; color: #ffffff;"),
    "paused":     ("Paused",      "background: #f59e0b; color: #ffffff;"),
    "done":       ("Done",        "background: rgba(255,255,255,0.20); color: #ffffff;"),
    "error":      ("Error",       "background: #dc2626; color: #ffffff;"),
    "cancelling": ("Cancelling…", "background: #f59e0b; color: #ffffff;"),
}


class HeaderWidget(QFrame):
    def __init__(self, username: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("headerBar")
        self.setFixedHeight(48)
        self._build(username)
        self.set_status("idle")

    def _build(self, username: str) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(12)

        title = QLabel("Pipeline Dashboard")
        title.setObjectName("headerTitle")
        layout.addWidget(title)

        layout.addStretch()

        user_lbl = QLabel(f"👤  {username}")
        user_lbl.setStyleSheet(
            "color: rgba(255,255,255,0.85); font-size: 8.5pt; font-weight: 600;"
        )
        layout.addWidget(user_lbl)

        layout.addSpacing(8)

        self._status_chip = QLabel()
        self._status_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_chip)

    def set_status(self, key: str) -> None:
        label, extra = _STATUS_STYLES.get(key, _STATUS_STYLES["idle"])
        self._status_chip.setText(label)
        self._status_chip.setStyleSheet(
            f"border-radius: 10px; padding: 3px 14px; font-size: 8pt; font-weight: 700; {extra}"
        )
