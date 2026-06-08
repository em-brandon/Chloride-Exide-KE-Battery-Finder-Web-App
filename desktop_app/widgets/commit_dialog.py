"""Conflict resolution dialog shown before committing staging."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QRadioButton,
    QButtonGroup, QWidget, QScrollArea, QFrame,
)


class CommitDialog(QDialog):
    """Shows conflicts; lets the user choose staging vs current for each."""

    def __init__(self, conflicts: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Resolve Conflicts Before Commit")
        self.setMinimumSize(780, 500)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self._conflicts = conflicts
        self._resolutions: dict[int, str] = {}  # row_id → "staging" | "current"
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel(f"{len(self._conflicts)} conflict{'s' if len(self._conflicts) != 1 else ''} require resolution")
        title.setStyleSheet("font-size: 10pt; font-weight: 700; color: #111827;")
        layout.addWidget(title)

        sub = QLabel("For each conflict, choose which value to keep in the master table.")
        sub.setStyleSheet("color: #6b7280; font-size: 8.5pt;")
        layout.addWidget(sub)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: #e2e4e9; border: none; max-height: 1px;")
        layout.addWidget(sep)

        # Table
        self._table = QTableWidget(len(self._conflicts), 7)
        self._table.setHorizontalHeaderLabels(
            ["Make", "Model", "Year", "Current Ah / Tech", "Staging Ah / Tech", "Keep Current", "Keep Staging"]
        )
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self._groups: list[QButtonGroup] = []

        for row_idx, c in enumerate(self._conflicts):
            row_id = c["id"]

            def _cell(text: str, bold: bool = False) -> QTableWidgetItem:
                item = QTableWidgetItem(str(text))
                if bold:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                return item

            self._table.setItem(row_idx, 0, _cell(c.get("make_n", "")))
            self._table.setItem(row_idx, 1, _cell(c.get("model_n", "")))
            self._table.setItem(row_idx, 2, _cell(str(c.get("year", ""))))
            self._table.setItem(row_idx, 3, _cell(
                f"{c.get('current_ah', '?')} Ah / {c.get('current_tech', '?')}"
            ))
            self._table.setItem(row_idx, 4, _cell(
                f"{c.get('staging_ah', '?')} Ah / {c.get('staging_tech', '?')}", bold=True
            ))

            # Radio buttons
            grp = QButtonGroup(self)
            self._groups.append(grp)

            keep_cur = QRadioButton()
            keep_stg = QRadioButton()
            keep_stg.setChecked(True)
            grp.addButton(keep_cur, 0)
            grp.addButton(keep_stg, 1)

            def _make_handler(rid: int, grp: QButtonGroup):
                def _handler(btn_id: int):
                    self._resolutions[rid] = "current" if btn_id == 0 else "staging"
                return _handler

            grp.idClicked.connect(_make_handler(row_id, grp))
            self._resolutions[row_id] = "staging"  # default

            for col, rb in [(5, keep_cur), (6, keep_stg)]:
                cell_widget = QWidget()
                cell_layout = QHBoxLayout(cell_widget)
                cell_layout.setContentsMargins(0, 0, 0, 0)
                cell_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cell_layout.addWidget(rb)
                self._table.setCellWidget(row_idx, col, cell_widget)

        layout.addWidget(self._table)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        commit_btn = QPushButton("Commit with Resolutions")
        commit_btn.setObjectName("commitBtn")
        commit_btn.clicked.connect(self.accept)
        btn_row.addWidget(commit_btn)

        layout.addLayout(btn_row)

    def get_resolutions(self) -> dict[int, str]:
        return dict(self._resolutions)
