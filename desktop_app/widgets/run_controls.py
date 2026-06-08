"""Provider checkboxes + phase selector + Run/Pause/Resume/Cancel controls."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QPushButton, QComboBox, QFrame, QProgressBar,
)

PROVIDERS = ["searxng", "duckduckgo", "brave", "tavily"]


class RunControlsWidget(QWidget):
    run_requested    = pyqtSignal(list, str)  # (providers, phase)
    pause_requested  = pyqtSignal()
    resume_requested = pyqtSignal()
    cancel_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._running = False
        self._paused  = False
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
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # Title row
        title_row = QHBoxLayout()
        title = QLabel("Pipeline Controls")
        title.setStyleSheet("font-size: 10pt; font-weight: 700; color: #111827;")
        title_row.addWidget(title)
        title_row.addStretch()

        self._status_label = QLabel("Idle")
        self._status_label.setStyleSheet("color: #6b7280; font-size: 8.5pt;")
        title_row.addWidget(self._status_label)
        layout.addLayout(title_row)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: #e2e4e9; border: none; max-height: 1px;")
        layout.addWidget(sep)

        # Provider checkboxes
        prov_label = QLabel("Providers")
        prov_label.setStyleSheet(
            "font-size: 7.5pt; font-weight: 700; letter-spacing: 0.08em; color: #6b7280; text-transform: uppercase;"
        )
        layout.addWidget(prov_label)

        prov_row = QHBoxLayout()
        prov_row.setSpacing(20)
        self._checks: dict[str, QCheckBox] = {}
        for p in PROVIDERS:
            cb = QCheckBox(p.capitalize())
            cb.setChecked(True)
            self._checks[p] = cb
            prov_row.addWidget(cb)
        prov_row.addStretch()
        layout.addLayout(prov_row)

        # Phase + buttons row
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(10)

        phase_label = QLabel("Phase:")
        phase_label.setStyleSheet("color: #6b7280; font-size: 9pt;")
        ctrl_row.addWidget(phase_label)

        self._phase_combo = QComboBox()
        self._phase_combo.addItems(["Both", "Phase 1 only", "Phase 2 only"])
        self._phase_combo.setFixedWidth(140)
        ctrl_row.addWidget(self._phase_combo)

        ctrl_row.addStretch()

        self._run_btn = QPushButton("▶  Run Pipeline")
        self._run_btn.setObjectName("runBtn")
        self._run_btn.setFixedWidth(140)
        self._run_btn.clicked.connect(self._on_run)
        ctrl_row.addWidget(self._run_btn)

        self._pause_btn = QPushButton("⏸  Pause")
        self._pause_btn.setObjectName("pauseBtn")
        self._pause_btn.setFixedWidth(100)
        self._pause_btn.setVisible(False)
        self._pause_btn.clicked.connect(self._on_pause_resume)
        ctrl_row.addWidget(self._pause_btn)

        self._cancel_btn = QPushButton("✕  Cancel")
        self._cancel_btn.setObjectName("cancelBtn")
        self._cancel_btn.setFixedWidth(100)
        self._cancel_btn.setVisible(False)
        self._cancel_btn.clicked.connect(self.cancel_requested)
        ctrl_row.addWidget(self._cancel_btn)

        layout.addLayout(ctrl_row)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setVisible(False)
        self._progress.setFixedHeight(8)
        layout.addWidget(self._progress)

        # Progress detail label
        self._prog_detail = QLabel("")
        self._prog_detail.setStyleSheet("color: #6b7280; font-size: 8pt;")
        self._prog_detail.setVisible(False)
        layout.addWidget(self._prog_detail)

    def _get_phase(self) -> str:
        idx = self._phase_combo.currentIndex()
        return {0: "both", 1: "phase1", 2: "phase2"}[idx]

    def _get_providers(self) -> list[str]:
        return [p for p, cb in self._checks.items() if cb.isChecked()]

    def _on_run(self) -> None:
        providers = self._get_providers()
        if not providers:
            self._status_label.setText("Select at least one provider")
            return
        self.run_requested.emit(providers, self._get_phase())

    def _on_pause_resume(self) -> None:
        if self._paused:
            self._paused = False
            self._pause_btn.setText("⏸  Pause")
            self.resume_requested.emit()
        else:
            self._paused = True
            self._pause_btn.setText("▶  Resume")
            self.pause_requested.emit()

    # ── External state changes ────────────────────────────────────────────────

    def set_running(self, running: bool) -> None:
        self._running = running
        self._paused  = False
        self._run_btn.setVisible(not running)
        self._pause_btn.setVisible(running)
        self._cancel_btn.setVisible(running)
        self._progress.setVisible(running)
        self._prog_detail.setVisible(running)
        for cb in self._checks.values():
            cb.setEnabled(not running)
        self._phase_combo.setEnabled(not running)
        if running:
            self._status_label.setText("Running…")
            self._pause_btn.setText("⏸  Pause")
            self._progress.setValue(0)
        else:
            self._status_label.setText("Idle")

    def update_progress(self, processed: int, total: int, provider: str) -> None:
        if total > 0:
            self._progress.setValue(int(processed / total * 100))
        self._prog_detail.setText(
            f"{processed:,} / {total:,}  ·  provider: {provider}"
        )

    def update_phase1_progress(self, fetched: int, total: int) -> None:
        self._prog_detail.setText(f"Phase 1 — web prefetch: {fetched}/{total} models")

    def set_status(self, text: str) -> None:
        self._status_label.setText(text)
