"""Async pipeline wrapper — replaces QThread for NiceGUI."""
from __future__ import annotations

import asyncio
import threading
import uuid
from typing import Callable

from nicegui import run


async def execute(
    providers: list[str],
    phase: str,
    cancel_event: threading.Event,
    pause_event: threading.Event,
    log_push: Callable[[str], None],
    set_progress: Callable[[int, int, str], None],
    on_finish: Callable,
    on_error: Callable,
) -> None:
    """Run the web-battery-validate pipeline in a thread pool, streaming
    log lines and progress updates back to the NiceGUI event loop."""

    loop = asyncio.get_running_loop()

    def log_cb(line: str) -> None:
        loop.call_soon_threadsafe(log_push, line)

    def progress_cb(processed: int, total: int, provider: str) -> None:
        loop.call_soon_threadsafe(set_progress, processed, total, provider or "")

    def phase1_cb(fetched: int, total: int) -> None:
        loop.call_soon_threadsafe(log_push, f"[Phase 1] {fetched}/{total} models prefetched")

    try:
        from pipelines.web_battery_validate import main as run_pipeline

        result = await run.io_bound(
            run_pipeline,
            cancel_event=cancel_event,
            pause_event=pause_event,
            progress_callback=progress_cb,
            log_callback=log_cb,
            enabled_providers=providers,
            run_id=str(uuid.uuid4()),
            phase=phase,
            phase1_progress_callback=phase1_cb,
        )
        await on_finish(result or {})
    except Exception as exc:
        await on_error(str(exc))
