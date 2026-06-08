"""QThread wrapper around the web_battery_validate pipeline."""
from __future__ import annotations

import sys
import threading
import uuid
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class PipelineRunner(QThread):
    log_line        = pyqtSignal(str)
    progress        = pyqtSignal(int, int, str)   # processed, total, provider
    phase1_progress = pyqtSignal(int, int)         # fetched, total_models
    finished        = pyqtSignal(dict)
    error_occurred  = pyqtSignal(str)

    def __init__(
        self,
        providers: list[str] | None = None,
        phase: str = "both",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.providers = providers
        self.phase = phase
        self.run_id = str(uuid.uuid4())
        self._cancel = threading.Event()
        self._pause  = threading.Event()

    def run(self) -> None:
        try:
            from pipelines.web_battery_validate import main as run_pipeline

            result = run_pipeline(
                cancel_event=self._cancel,
                pause_event=self._pause,
                progress_callback=lambda p, t, pv: self.progress.emit(p, t, pv or ""),
                log_callback=lambda line: self.log_line.emit(line),
                enabled_providers=self.providers,
                run_id=self.run_id,
                phase1_progress_callback=lambda p, t: self.phase1_progress.emit(p, t),
                phase=self.phase,
            )
            self.finished.emit(result or {})
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def pause(self) -> None:
        self._pause.set()

    def resume(self) -> None:
        self._pause.clear()

    def cancel(self) -> None:
        self._cancel.set()
        self._pause.clear()
