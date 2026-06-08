"""Login dialog shown before the main window."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame,
)

from auth import login


class AuthDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Battery Finder — Admin Login")
        self.setFixedSize(380, 280)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.username: str = ""
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 32, 32, 32)
        root.setSpacing(16)

        # Title
        title = QLabel("Pipeline Dashboard")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(title)

        sub = QLabel("Sign in with your admin credentials")
        sub.setStyleSheet("color: #6b7280; font-size: 8.5pt;")
        sub.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(sub)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #e2e4e9;")
        root.addWidget(sep)

        # Username
        self._user_edit = QLineEdit()
        self._user_edit.setPlaceholderText("Username")
        self._user_edit.returnPressed.connect(self._try_login)
        root.addWidget(self._user_edit)

        # Password
        self._pass_edit = QLineEdit()
        self._pass_edit.setPlaceholderText("Password")
        self._pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._pass_edit.returnPressed.connect(self._try_login)
        root.addWidget(self._pass_edit)

        # Error label
        self._err_label = QLabel("")
        self._err_label.setStyleSheet("color: #CC0000; font-size: 8pt;")
        self._err_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(self._err_label)

        # Buttons
        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        login_btn = QPushButton("Sign In")
        login_btn.setObjectName("primaryBtn")
        login_btn.clicked.connect(self._try_login)
        btn_row.addWidget(login_btn)

        root.addLayout(btn_row)
        root.addStretch()

    def _try_login(self) -> None:
        user = self._user_edit.text().strip()
        pw   = self._pass_edit.text()
        if not user or not pw:
            self._err_label.setText("Enter username and password")
            return
        self._err_label.setText("Authenticating…")
        self.repaint()
        try:
            result = login(user, pw)
        except Exception as exc:
            self._err_label.setText(f"DB error: {exc}")
            return
        if result:
            self.username = user
            self.accept()
        else:
            self._err_label.setText("Invalid credentials")
            self._pass_edit.clear()
            self._pass_edit.setFocus()
