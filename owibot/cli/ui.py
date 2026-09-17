"""Tiny setup-screen styling: stdlib only, encoding-safe, NO_COLOR aware.

Vibe: green-on-black mission control. Fancy unicode when the console
allows it, clean ASCII when it doesn't (Windows cp1252).
"""
from __future__ import annotations

import os
import sys

GREEN, DIM, BOLD, RED, YELLOW = "32", "2", "1", "31", "33"


def _tty() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def paint(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _tty() else text


def green(t: str) -> str: return paint(GREEN, t)
def dim(t: str) -> str: return paint(DIM, t)
def bold(t: str) -> str: return paint(BOLD, t)
def red(t: str) -> str: return paint(RED, t)
def yellow(t: str) -> str: return paint(YELLOW, t)


def uni(yes: str, no: str) -> str:
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        yes.encode(enc)
        return yes
    except (UnicodeEncodeError, LookupError):
        return no


OK = lambda: uni("✓", "OK")  # noqa: E731
CROSS = lambda: uni("✗", "X")  # noqa: E731
ARROW = lambda: uni("❯", ">")  # noqa: E731


def rule(width: int = 58) -> str:
    return dim(uni("─", "-") * width)


def banner(subtitle: str = "mission control") -> str:
    mark = uni("◉", "*")
    return (f"\n{green(bold(mark + ' owibot'))} {dim(subtitle)}\n{rule()}")


def steps(current: int, total: int, label: str) -> str:
    on, off = uni("●", "*"), uni("○", "-")
    dots = " ".join(green(on) if i < current else dim(off) for i in range(total))
    return f"\n{dots}  {bold(f'[{current}/{total}] {label}')}"


def box(title: str, lines: list[str], width: int = 58) -> str:
    tl, tr, bl, br, h, v = (uni("┌", "+"), uni("┐", "+"), uni("└", "+"),
                            uni("┘", "+"), uni("─", "-"), uni("│", "|"))
    inner = width - 2
    out = [green(f"{tl}{h * inner}{tr}")]
    out.append(green(v) + " " + bold(title.ljust(inner - 1)) + green(v))
    out.append(green(v) + dim(h * inner) + green(v))
    for ln in lines:
        for chunk in (ln[i:i + inner] for i in range(0, max(len(ln), 1), inner)):
            out.append(green(v) + " " + chunk.ljust(inner - 1) + green(v))
    out.append(green(f"{bl}{h * inner}{br}"))
    return "\n".join(out)


def ask(prompt: str, default: str = "", secret: bool = False) -> str:
    hint = f" {dim('[' + default + ']')}" if default else ""
    reader = __import__("getpass").getpass if secret else input
    try:
        raw = reader(f"  {green(ARROW())} {prompt}{hint}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raw = ""
    return raw or default


def menu(question: str, options: list[str]) -> int:
    print(f"\n  {bold(question)}")
    for i, opt in enumerate(options, start=1):
        print(f"    {green(str(i) + ')')} {opt}")
    while True:
        raw = ask(f"pilih [1-{len(options)}]", "1")
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        print(f"  {yellow('nomor tidak valid, coba lagi.')}")
