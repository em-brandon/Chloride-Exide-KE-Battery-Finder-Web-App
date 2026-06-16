"""
PyInstaller entry point — starts FastAPI + opens the React UI in a native Edge WebView2 window.

Build:
    cd pipeline_app
    bun --cwd frontend run build
    pyinstaller pipeline_app.spec
    iscc /DAppVersion=<version> installer.iss

The DATABASE_URL is read from pipeline.env next to the exe (or baked in via the env at build time).
"""

import os
import socket
import sys
import threading
import time

import uvicorn
import webview

from __version__ import __version__


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _resource(relative: str) -> str:
    """Return absolute path to a bundled resource (works both frozen and unfrozen)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def _exe_dir() -> str:
    return os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))


def _show_error(title: str, message: str) -> None:
    import tkinter
    import tkinter.messagebox as mb
    root = tkinter.Tk()
    root.withdraw()
    mb.showerror(title, message)
    root.destroy()


def _check_env() -> None:
    """Exit with a friendly dialog if pipeline.env is missing."""
    env_path = os.path.join(_exe_dir(), "pipeline.env")
    if not os.path.isfile(env_path):
        _show_error(
            "Setup Required",
            f"pipeline.env not found at:\n\n{env_path}\n\n"
            "Copy pipeline.env.example, fill in your DATABASE_URL, then restart the app.",
        )
        sys.exit(1)


def _load_env() -> None:
    """Load pipeline.env from the directory next to the exe (or script)."""
    env_path = os.path.join(_exe_dir(), "pipeline.env")
    if os.path.isfile(env_path):
        from dotenv import load_dotenv
        load_dotenv(env_path, override=False)


def _wait_for_port(port: int, timeout: float = 8.0) -> bool:
    """Return True once the server is accepting connections, False on timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def run() -> None:
    _check_env()
    _load_env()
    port = _find_free_port()

    # Mount frontend/dist as static files — override the path FastAPI uses at import time
    os.environ.setdefault("PIPELINE_FRONTEND_DIST", _resource("frontend/dist"))

    server_thread = threading.Thread(
        target=lambda: uvicorn.run(
            "app:app",
            host="127.0.0.1",
            port=port,
            log_level="warning",
        ),
        daemon=True,
    )
    server_thread.start()

    if not _wait_for_port(port):
        _show_error(
            "Startup Failed",
            "The application server failed to start.\n\n"
            "Check that DATABASE_URL in pipeline.env is correct and the database is reachable.",
        )
        sys.exit(1)

    webview.create_window(
        title=f"Chloride Exide — Pipeline App  v{__version__}",
        url=f"http://127.0.0.1:{port}",
        width=1340,
        height=860,
        min_size=(960, 620),
        text_select=True,
    )
    webview.start(debug=False)


if __name__ == "__main__":
    run()
