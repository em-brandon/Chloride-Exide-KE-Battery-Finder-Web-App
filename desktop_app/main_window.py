"""Main application window — sidebar navigation + sectioned QStackedWidget."""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QScrollArea, QStackedWidget, QWidget,
    QVBoxLayout, QHBoxLayout, QMessageBox,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db_queries
from pipeline_runner import PipelineRunner
from widgets.header_widget import HeaderWidget
from widgets.sidebar_widget import SidebarWidget
from widgets.run_controls import RunControlsWidget
from widgets.log_panel import LogPanelWidget
from widgets.coverage_widget import CoverageWidget
from widgets.quota_widget import QuotaWidget
from widgets.version_widget import VersionWidget
from widgets.matched_widget import MatchedWidget
from widgets.unmatched_widget import UnmatchedWidget
from widgets.staging_widget import StagingWidget


class MainWindow(QMainWindow):
    def __init__(self, username: str) -> None:
        super().__init__()
        self._username = username
        self._runner: PipelineRunner | None = None
        self.setWindowTitle(f"Battery Finder — Pipeline Dashboard  ·  {username}")
        self.resize(1280, 900)
        self._build()
        self._initial_load()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        root_widget = QWidget()
        self.setCentralWidget(root_widget)

        root = QVBoxLayout(root_widget)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header bar
        self._header = HeaderWidget(username=self._username)
        root.addWidget(self._header)

        # Body: sidebar + stacked content
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._sidebar = SidebarWidget(username=self._username)
        self._sidebar.nav_changed.connect(self._on_nav)
        body.addWidget(self._sidebar)

        self._stack = QStackedWidget()
        body.addWidget(self._stack, stretch=1)

        root.addLayout(body, stretch=1)

        # Pages
        self._stack.addWidget(self._build_dashboard_page())  # 0
        self._stack.addWidget(self._build_pipeline_page())   # 1
        self._stack.addWidget(self._build_staging_page())    # 2
        self._stack.addWidget(self._build_versions_page())   # 3
        self._stack.addWidget(self._build_quotas_page())     # 4

    @staticmethod
    def _wrap(widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        scroll.setWidget(widget)
        return scroll

    def _build_dashboard_page(self) -> QScrollArea:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        self._coverage = CoverageWidget(refresh_cb=self._load_coverage)
        layout.addWidget(self._coverage)

        self._unmatched = UnmatchedWidget()
        layout.addWidget(self._unmatched)

        layout.addStretch()
        return self._wrap(page)

    def _build_pipeline_page(self) -> QScrollArea:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        self._run_controls = RunControlsWidget()
        self._run_controls.run_requested.connect(self._on_run)
        self._run_controls.pause_requested.connect(self._on_pause)
        self._run_controls.resume_requested.connect(self._on_resume)
        self._run_controls.cancel_requested.connect(self._on_cancel)
        layout.addWidget(self._run_controls)

        self._log_panel = LogPanelWidget()
        self._log_panel.setMinimumHeight(300)
        layout.addWidget(self._log_panel, stretch=1)

        return self._wrap(page)

    def _build_staging_page(self) -> QScrollArea:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(0)

        self._staging = StagingWidget(
            username=self._username,
            refresh_coverage_cb=self._load_coverage,
            refresh_versions_cb=self._versions_load_deferred,
            clear_badge_cb=lambda: self._sidebar.set_staging_badge(0),
        )
        layout.addWidget(self._staging, stretch=1)

        return self._wrap(page)

    def _build_versions_page(self) -> QScrollArea:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        self._versions = VersionWidget(
            username=self._username,
            refresh_coverage_cb=self._load_coverage,
        )
        layout.addWidget(self._versions)

        self._matched = MatchedWidget()
        layout.addWidget(self._matched)

        layout.addStretch()
        return self._wrap(page)

    def _build_quotas_page(self) -> QScrollArea:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        self._quota = QuotaWidget(refresh_cb=self._load_quotas)
        layout.addWidget(self._quota)

        layout.addStretch()
        return self._wrap(page)

    # ── Navigation ────────────────────────────────────────────────────────────

    def _on_nav(self, idx: int) -> None:
        self._stack.setCurrentIndex(idx)

    def _versions_load_deferred(self) -> None:
        self._versions.load()

    # ── Initial data load ─────────────────────────────────────────────────────

    def _initial_load(self) -> None:
        self._load_coverage()
        self._load_quotas()
        self._versions.load()
        self._check_staging()

    def _load_coverage(self) -> None:
        try:
            data = db_queries.get_coverage()
            self._coverage.update_data(data)
            self._unmatched.update_data(data.get("unmatched_vehicles", []))
        except Exception as exc:
            self._log_panel.append(f"[Coverage] Error: {exc}")

    def _load_quotas(self) -> None:
        try:
            quotas = db_queries.get_quotas()
            self._quota.update_data(quotas)
        except Exception:
            pass

    def _check_staging(self) -> None:
        try:
            data = db_queries.get_staging(1, "all", 1)
            total = data["total"]
            self._sidebar.set_staging_badge(total)
            self._staging.load()
        except Exception:
            pass

    # ── Pipeline controls ─────────────────────────────────────────────────────

    def _on_run(self, providers: list[str], phase: str) -> None:
        if self._runner and self._runner.isRunning():
            return
        self._log_panel.append(f"\n[Run] Starting pipeline  phase={phase}  providers={providers}")
        self._runner = PipelineRunner(providers=providers, phase=phase, parent=self)
        self._runner.log_line.connect(self._log_panel.append)
        self._runner.progress.connect(self._run_controls.update_progress)
        self._runner.phase1_progress.connect(self._run_controls.update_phase1_progress)
        self._runner.finished.connect(self._on_run_finished)
        self._runner.error_occurred.connect(self._on_run_error)
        self._run_controls.set_running(True)
        self._header.set_status("running")
        self._runner.start()

    def _on_pause(self) -> None:
        if self._runner:
            self._runner.pause()
            self._run_controls.set_status("Paused")
            self._header.set_status("paused")

    def _on_resume(self) -> None:
        if self._runner:
            self._runner.resume()
            self._run_controls.set_status("Running…")
            self._header.set_status("running")

    def _on_cancel(self) -> None:
        if self._runner:
            self._runner.cancel()
            self._log_panel.append("[Run] Cancelling…")
            self._run_controls.set_status("Cancelling…")
            self._header.set_status("cancelling")

    def _on_run_finished(self, result: dict) -> None:
        fetched = result.get("fetched", 0)
        failed  = result.get("failed", 0)
        self._log_panel.append(
            f"[Run] Finished — fetched={fetched}  failed={failed}  "
            f"provider_counts={result.get('provider_counts', {})}"
        )
        self._run_controls.set_running(False)
        self._run_controls.set_status(f"Done — {fetched} fetched, {failed} failed")
        self._header.set_status("done")
        self._load_coverage()
        self._load_quotas()
        self._check_staging()

    def _on_run_error(self, msg: str) -> None:
        self._log_panel.append(f"[Run] ERROR: {msg}")
        self._run_controls.set_running(False)
        self._run_controls.set_status("Error — see log")
        self._header.set_status("error")
        QMessageBox.critical(self, "Pipeline Error", msg)
