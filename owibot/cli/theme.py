"""Tasteful CLI presentation: one accent, dim secondary text, box-drawing rules.

- Colors auto-disable when stdout is not a tty or NO_COLOR is set.
- No ASCII-art logos, no emoji rain. Structure carries the design.
"""
from __future__ import annotations

import os
import sys
import threading
import time

_ACCENT = "32"   # hacker green
_DIM = "2"
_BOLD = "1"
_RED = "31"
_YELLOW = "33"
_GREEN = "32"


def enabled() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _uni(uni: str, ascii_: str) -> str:
    """Box-drawing when the console encoding allows it, ASCII otherwise."""
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        uni.encode(enc)
        return uni
    except (UnicodeEncodeError, LookupError):
        return ascii_


def paint(code: str, text: str) -> str:
    if not enabled():
        return text
    return f"\033[{code}m{text}\033[0m"


def accent(text: str) -> str: return paint(_ACCENT, text)
def dim(text: str) -> str: return paint(_DIM, text)
def bold(text: str) -> str: return paint(_BOLD, text)
def red(text: str) -> str: return paint(_RED, text)
def yellow(text: str) -> str: return paint(_YELLOW, text)
def green(text: str) -> str: return paint(_GREEN, text)


def rule(width: int = 56) -> str:
    return dim(_uni("─", "-") * width)


def banner(version: str, rows: list[tuple[str, str]]) -> str:
    """Startup panel. rows = [(label, value)] shown under the wordmark."""
    lines = [f"{accent(_uni('◉', '*') + ' owibot')} {dim(version)}", rule()]
    for label, value in rows:
        lines.append(f"{dim(label.ljust(10))} {value}")
    lines.append(rule())
    lines.append(dim("Type a message, or /help for commands. Ctrl+C or 'exit' to quit."))
    return "\n".join(lines)


def reply_block(text: str) -> str:
    return f"{rule()}\n{text.strip()}\n{rule()}"


def footer(tool_calls: int, session_turns: int, mem_usage: str) -> str:
    mark = _uni("⧖", "~")
    return dim(f"{mark} {tool_calls} tool calls this turn · {session_turns} live exchanges · memory {mem_usage}")


def error_block(text: str) -> str:
    return red(f"error: {text}")


def warn_block(text: str) -> str:
    return yellow(f"warn: {text}")


class Spinner:
    """Minimal waiting indicator. Silent when output is piped."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    ASCII_FRAMES = "-\\|/"

    def __init__(self, label: str = "thinking"):
        self.label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self):
        if not enabled():
            return self
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread:
            self._thread.join()
        if enabled():
            sys.stdout.write("\r" + " " * (len(self.label) + 4) + "\r")
            sys.stdout.flush()

    def _spin(self):
        frames = self.FRAMES if _uni("⠋", "") else self.ASCII_FRAMES
        i = 0
        while not self._stop.is_set():
            frame = frames[i % len(frames)]
            sys.stdout.write(f"\r{accent(frame + ' ' + self.label)}")
            sys.stdout.flush()
            i += 1
            time.sleep(0.08)
