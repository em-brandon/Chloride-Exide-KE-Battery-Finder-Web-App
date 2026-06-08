"""Entry point — QApplication → AuthDialog → MainWindow."""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from qt_material import apply_stylesheet

# Ensure project root is on path for db.py / models.py imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auth_dialog import AuthDialog
from main_window import MainWindow

# Sidebar and header overrides that qt-material doesn't cover
_CUSTOM_QSS = """
/* ── Sidebar ──────────────────────────────────────────────── */
#sidebar {
    background: #111827;
    border-right: 1px solid #1f2937;
}
#sidebar QLabel#appTitle {
    color: #ffffff;
    font-size: 11pt;
    font-weight: 700;
    padding: 18px 16px 14px 16px;
    background: transparent;
}
#sidebar QPushButton {
    background: transparent;
    color: #9ca3af;
    border: none;
    border-radius: 8px;
    padding: 10px 16px;
    text-align: left;
    font-size: 9pt;
    font-weight: 600;
}
#sidebar QPushButton:hover {
    background: #1f2937;
    color: #e5e7eb;
}
#sidebar QPushButton[active="true"] {
    background: #312e81;
    color: #ffffff;
}
#sidebar QLabel#userBadge {
    color: #ffffff;
    font-size: 8.5pt;
    font-weight: 700;
    padding: 6px 16px 2px 16px;
    background: transparent;
}
#sidebar QLabel#userRole {
    color: #6b7280;
    font-size: 7.5pt;
    padding: 0px 16px 16px 16px;
    background: transparent;
}

/* ── Header bar ───────────────────────────────────────────── */
#headerBar {
    background: #CC0000;
}
#headerBar QLabel#headerTitle {
    color: #ffffff;
    font-size: 11pt;
    font-weight: 700;
    background: transparent;
}

/* ── Log pane ─────────────────────────────────────────────── */
QPlainTextEdit {
    background: #0d1117;
    color: #e5e7eb;
    border: 1px solid #30363d;
    border-radius: 8px;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 8pt;
    padding: 8px;
}
"""


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Battery Finder Pipeline")
    app.setOrganizationName("Chloride Exide KE")

    # Apply qt-material base theme, then layer our custom overrides
    apply_stylesheet(app, theme="dark_red.xml", invert_secondary=False)
    app.setStyleSheet(app.styleSheet() + _CUSTOM_QSS)

    # Auth
    auth = AuthDialog()
    if auth.exec() != auth.DialogCode.Accepted:
        sys.exit(0)

    window = MainWindow(username=auth.username)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
