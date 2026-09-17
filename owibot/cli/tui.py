"""Fullscreen console in the shape of OpenCode: top bar, tool rows, framed input.

Roles in MessageStore: user / bot / tool(dict) / sys.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

STYLE = {
    "title": "ansigreen bold",
    "model": "ansigreen",
    "ctx": "#888888",
    "user": "ansigreen bold",
    "bot": "ansiwhite",
    "tool": "ansicyan",
    "toolout": "#888888",
    "sys": "ansiyellow",
    "dim": "#666666",
    "input": "ansigreen",
}


@dataclass
class MessageStore:
    messages: list[tuple[str, object]] = field(default_factory=list)
    verbose: bool = False

    def add(self, role: str, text: object) -> None:
        if isinstance(text, str) and not text.strip():
            text = "(empty)"
        self.messages.append((role, text))

    def formatted(self):
        out = []
        for role, text in self.messages:
            if role == "user":
                out += [("class:user", "❯ "), ("", str(text) + "\n")]
            elif role == "tool" and isinstance(text, dict):
                out += _tool_frags(text, self.verbose)
            elif role == "sys":
                out += [("class:sys", str(text) + "\n")]
            else:
                out += [("class:bot", str(text) + "\n")]
        return out


def summarize_args(tool: str, args: object) -> str:
    if not isinstance(args, dict):
        return ""
    for key in ("command", "path", "query", "url", "task", "question", "prompt", "name"):
        if args.get(key):
            return str(args[key])[:60]
    return ""


def _tool_frags(entry: dict, verbose: bool):
    tool, secs = entry.get("tool", "?"), entry.get("secs", 0)
    head = [("class:tool", f"⏺ {tool}"), ("class:dim", f"({summarize_args(tool, entry.get('args'))})"),
            ("class:dim", f" · {secs}s\n")]
    preview = str(entry.get("preview", "") or "").strip().splitlines()
    if not preview:
        return head
    shown = preview if verbose else preview[:5]
    for line in shown:
        head.append(("class:toolout", f"  {line[:160]}\n"))
    if not verbose and len(preview) > 5:
        head.append(("class:dim", f"  … {len(preview) - 5} more lines (/verbose)\n"))
    return head


def top_frags(project: str, model: str, pct: int):
    return [("class:title", "◉ owibot"), ("class:dim", f"  {project}"),
            ("", " "),
            ("class:model", f"{model}"), ("class:ctx", f" · ctx ~{pct}%")]


def status_frags():
    return [("class:dim", " tab: build/plan · ↑↓: history · /: commands · ctrl+c: quit")]


def parse_local(text: str):
    """Split a line into (command, args). command is '' for plain chat."""
    t = (text or "").strip()
    if t.startswith("/") and " " in t:
        cmd, _, rest = t[1:].partition(" ")
        return cmd.lower(), rest.strip()
    if t.startswith("/"):
        return t[1:].lower(), ""
    return "", t


def build_app(store: MessageStore, top_fn: Callable, status_fn: Callable,
              history_path: str, title: str = "build"):
    """Construct the prompt_toolkit Application (needs a real console to run)."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.completion import Completer, Completion, FuzzyCompleter
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import (
        FormattedTextControl, HSplit, Layout, ScrollablePane, VSplit, Window,
    )
    from prompt_toolkit.layout.controls import BufferControl
    from prompt_toolkit.styles import Style
    from prompt_toolkit.widgets import Frame, TextArea

    from .prompt import complete_slash

    transcript = TextArea(
        text=lambda: store.formatted(),
        read_only=True, scrollbar=True, focusable=False,
        style="class:transcript",
    )
    topbar = VSplit([
        Window(FormattedTextControl(top_fn), height=1),
    ], height=1)
    status = Window(FormattedTextControl(status_fn), height=1)

    class Slash(Completer):
        def get_completions(self, document, complete_event):
            for cmd, desc in complete_slash(document.text_before_cursor):
                yield Completion(cmd, start_position=-len(document.text_before_cursor),
                                 display_meta=desc)

    buf = Buffer(history=FileHistory(history_path),
                 completer=FuzzyCompleter(Slash()),
                 complete_while_typing=True,
                 auto_suggest=AutoSuggestFromHistory(),
                 multiline=False, accept_handler=lambda b: b.app.exit(result=b.text))
    entry = TextArea(buffer=buf, scrollbar=False, focusable=True,
                     style="class:input", height=3,
                     prompt="❯ ",
                     placeholder="type a command or ask anything")
    box = Frame(entry, title=f" {title} ")

    kb = KeyBindings()

    @kb.add("c-c")
    def _(event):
        event.app.exit(result="/__quit__")

    @kb.add("tab")
    def _(event):
        event.app.exit(result="/__tab__")

    layout = Layout(HSplit([topbar, ScrollablePane(transcript), status, box]),
                    focused_element=entry)
    app = Application(layout=layout, key_bindings=kb, full_screen=True,
                      style=Style.from_dict({**STYLE, "transcript": "", "input": "ansigreen",
                                             "status": "ansiblack reverse"}),
                      mouse_support=False)
    return app
