"""Autostart service for the Telegram gateway.

Default: Startup-folder batch file (no admin needed, runs at logon).
Optional: Task Scheduler entry (--scheduled, needs admin, supports --on-start).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

TASK_NAME = "OwiBot-Gateway"
BAT_NAME = "OwiBot-Gateway.bat"


def _require_windows() -> None:
    if sys.platform != "win32":
        raise RuntimeError("service install is Windows-only. "
                           "On Linux use systemd, on macOS use launchd — see README.")


def owibot_exe() -> str:
    exe = shutil.which("owibot")
    if not exe:
        raise RuntimeError("owibot executable not found on PATH; reinstall with `pip install -e .`")
    return exe


def startup_dir() -> Path:
    appdata = os.environ.get("APPDATA", str(Path.home()))
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def bat_path() -> Path:
    return startup_dir() / BAT_NAME


def build_bat(exe: str) -> str:
    return f'@echo off\r\nrem OwiBot gateway autostart (managed by `owibot service`)\r\nstart "" /min "{exe}" gateway\r\n'


def install_startup() -> str:
    _require_windows()
    target = bat_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_bat(owibot_exe()), encoding="utf-8")
    return f"Installed autostart: {target} (runs `owibot gateway` at logon, no admin needed)."


def build_create_cmd(on_start: bool = False) -> list[str]:
    schedule = "ONSTART" if on_start else "ONLOGON"
    return ["schtasks", "/Create", "/TN", TASK_NAME,
            "/TR", f'"{owibot_exe()} gateway"', "/SC", schedule, "/F"]


def _run(cmd: list[str]) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        raise RuntimeError("schtasks not found (Windows only).")
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    if p.returncode != 0:
        raise RuntimeError(f"schtasks failed: {out or p.returncode}")
    return out or "OK"


def install_scheduled(on_start: bool = False) -> str:
    _require_windows()
    _run(build_create_cmd(on_start))
    mode = "system start" if on_start else "logon"
    return f"Installed scheduled task '{TASK_NAME}' (runs `owibot gateway` at {mode})."


def install(scheduled: bool = False, on_start: bool = False) -> str:
    if scheduled:
        return install_scheduled(on_start)
    return install_startup()


def uninstall() -> str:
    _require_windows()
    notes = []
    bat = bat_path()
    if bat.exists():
        bat.unlink()
        notes.append(f"removed {bat}")
    try:
        notes.append(_run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]))
    except RuntimeError as err:
        notes.append(f"scheduled task: {err}")
    return "\n".join(notes)


def status() -> str:
    _require_windows()
    lines = [f"startup file: {'present' if bat_path().exists() else 'absent'} ({bat_path()})"]
    try:
        lines.append("scheduled task:\n" + _run(["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST"]))
    except RuntimeError as err:
        lines.append(f"scheduled task: {err}")
    return "\n".join(lines)
