"""Fullscreen TUI (OpenCode-style): header, scrollable transcript, input box.

Design: the prompt_toolkit Application owns ONLY the input box. Each Enter
closes the app and returns one line; the outer loop runs the agent turn
(synchronously — the status line says so) and re-opens the app. No threads,
no invalidation races. Pending approvals render as text cards answered with
/approve, /deny, /answer.
"""
from __future__ import annotations

from dataclasses import dataclass, field

STYLE = {
    "title": "ansigreen bold",
    "status": "ansiblack",
    "user": "ansigreen bold",
    "bot": "ansiwhite",
    "sys": "ansiyellow",
    "dim": "#666666",
    "input": "ansigreen",
}


@dataclass
class MessageStore:
    messages: list[tuple[str, str]] = field(default_factory=list)

    def add(self, role: str, text: str) -> None:
        self.messages.append((role, (text or "").strip() or "(empty)"))

    def formatted(self):
        """prompt_toolkit formatted text for the transcript control."""
        out = []
        for role, text in self.messages:
            if role == "user":
                out += [("class:user", "› "), ("", text + "\n")]
            elif role == "bot":
                out += [("class:bot", text + "\n")]
            else:
                out += [("class:sys", text + "\n")]
            out += [("class:dim", "─" * 40 + "\n")]
        return out


def status_line(model: str, exchanges: int, tool_calls: int, mem: str, busy: bool) -> list:
    state = "● working…" if busy else "○ ready"
    return [("class:status", f" {state} │ {model} │ {exchanges} exchanges │ "
                             f"{tool_calls} tool calls │ mem {mem} │ /help")]  # noqa


def parse_local(text: str):
    """Split a line into (command, args). command is '' for plain chat."""
    t = (text or "").strip()
    if t.startswith("/") and " " in t:
        cmd, _, rest = t[1:].partition(" ")
        return cmd.lower(), rest.strip()
    if t.startswith("/"):
        return t[1:].lower(), ""
    return "", t


def build_app(store: MessageStore, status_frags: list, history_path: str):
    """Construct the prompt_toolkit Application (needs a real console to run)."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.completion import Completer, Completion, FuzzyCompleter
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import (
        FormattedTextControl, HSplit, Layout, ScrollablePane, Window,
    )
    from prompt_toolkit.layout.controls import BufferControl
    from prompt_toolkit.styles import Style
    from prompt_toolkit.widgets import TextArea

    from .prompt import complete_slash

    transcript = TextArea(
        text=lambda: store.formatted(),
        read_only=True, scrollbar=True, focusable=False,
        style="class:transcript",
    )
    header = Window(FormattedTextControl([("class:title", " ◉ owibot "),
                                          ("class:dim", "telegram agent console")]),
                    height=1)
    status = Window(FormattedTextControl(lambda: status_frags()),
                    height=1, style="reverse")

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
    field = Window(BufferControl(buffer=buf, input_processors=[]), height=3,
                   style="class:input")
    kb = KeyBindings()

    @kb.add("c-c")
    def _(event):
        event.app.exit(result="/__quit__")

    layout = Layout(HSplit([header, ScrollablePane(transcript), status, field]),
                    focused_element=field)
    app = Application(layout=layout, key_bindings=kb, full_screen=True,
                      style=Style.from_dict({**STYLE, "transcript": "", "input": "ansigreen",
                                             "status": "ansiblack"}),
                      mouse_support=False)
    return app
