"""
Local HTTP server: Waitress + Flask app (Windows, Linux, macOS).
- Dev: python local_server.py
- Frozen binary (PyInstaller): data under %LOCALAPPDATA%\\VMAnalytic (Windows)
  or $XDG_DATA_HOME/VMAnalytic (Linux), ~/Library/... could be added for macOS frozen.
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _user_data_root() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "VMAnalytic"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "VMAnalytic"
    xdg = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(xdg) / "VMAnalytic"


def _bootstrap_frozen() -> None:
    """Writable user dir + helper_files copy from bundle (PyInstaller)."""
    bundle = Path(sys._MEIPASS)  # type: ignore[misc]
    data_root = _user_data_root()
    data_root.mkdir(parents=True, exist_ok=True)
    (data_root / "data" / "uploads").mkdir(parents=True, exist_ok=True)
    (data_root / "saved_csv_files").mkdir(parents=True, exist_ok=True)
    src_hf = bundle / "helper_files"
    dst_hf = data_root / "helper_files"
    if src_hf.is_dir():
        if not dst_hf.is_dir():
            shutil.copytree(src_hf, dst_hf)
        else:
            for p in src_hf.glob("*.txt"):
                shutil.copy2(p, dst_hf / p.name)
    os.environ["VMANALYTIC_ROOT"] = str(data_root.resolve())


def _setup_paths() -> None:
    if getattr(sys, "frozen", False):
        sys.path.insert(0, str(Path(sys._MEIPASS)))  # type: ignore[misc]
        _bootstrap_frozen()
        os.chdir(os.environ["VMANALYTIC_ROOT"])
    else:
        root = Path(__file__).resolve().parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        os.chdir(root)


_setup_paths()

from waitress import serve  # noqa: E402
from web.app import app  # noqa: E402


def _open_browser(host: str, port: int) -> None:
    time.sleep(1.25)
    webbrowser.open(f"http://{host}:{port}/")


def _should_open_browser() -> bool:
    if sys.platform in ("win32", "darwin"):
        return True
    return bool(os.environ.get("DISPLAY"))


def main() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    threads = int(os.environ.get("WAITRESS_THREADS", "4"))

    print(f"VMAnalytic App — http://{host}:{port}/")
    if getattr(sys, "frozen", False):
        print(f"Data directory: {os.environ.get('VMANALYTIC_ROOT', '')}")
    print("Press Ctrl+C to stop.\n")

    if _should_open_browser():
        threading.Thread(
            target=_open_browser,
            args=(host, port),
            daemon=True,
        ).start()

    serve(app, host=host, port=port, threads=threads, channel_timeout=600)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
