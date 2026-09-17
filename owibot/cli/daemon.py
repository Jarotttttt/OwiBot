"""Detached background gateway: `owibot gateway --background`, `--stop`."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path


def pid_path(home: Path) -> Path:
    return home / "gateway.pid"


def log_path(home: Path) -> Path:
    return home / "gateway.log"


def is_running(home: Path) -> int | None:
    try:
        pid = int(pid_path(home).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return None
    return pid


def start_detached(home: Path) -> tuple[int, Path]:
    """Spawn `owibot gateway` detached. Returns (pid, log path)."""
    if (pid := is_running(home)) is not None:
        raise RuntimeError(f"gateway already running (pid {pid})")
    log = log_path(home)
    cmd = [sys.executable, "-u", "-m", "owibot", "gateway", "--fg-child"]
    kwargs: dict = {"stdin": subprocess.DEVNULL,
                    "stdout": open(log, "a", encoding="utf-8"),
                    "stderr": subprocess.STDOUT,
                    "close_fds": True}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(cmd, **kwargs)
    finally:
        kwargs["stdout"].close()
    pid_path(home).write_text(str(proc.pid), encoding="utf-8")
    return proc.pid, log


def stop(home: Path) -> str:
    pid = is_running(home)
    if pid is None:
        try:
            pid_path(home).unlink()
        except OSError:
            pass
        return "gateway is not running."
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, timeout=15)
        else:
            raise
    try:
        pid_path(home).unlink()
    except OSError:
        pass
    return f"stopped gateway (pid {pid})."
