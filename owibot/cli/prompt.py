"""Interactive prompt: `/` command completion + Up/Down history + ghost autosuggest.

prompt_toolkit is optional at runtime — the chat loop falls back to plain
input() when it is missing or stdin is not a tty.
"""
from __future__ import annotations

from pathlib import Path

COMMANDS: list[tuple[str, str]] = [
    ("/new", "fresh session, reload memory snapshot"),
    ("/retry", "re-run the last message"),
    ("/undo", "drop the last exchange"),
    ("/compress", "summarize live context to a file"),
    ("/usage", "session + memory usage"),
    ("/memory", "budgets · pending · approve · reject"),
    ("/skills", "list · pending · approve · diff"),
    ("/model", "show or switch model"),
    ("/learn", "save workflow as skill: /learn name | material"),
    ("/help", "list commands"),
    ("exit", "quit"),
]


def complete_slash(text: str) -> list[tuple[str, str]]:
    """Pure helper: commands matching a leading `/` fragment. Tested offline."""
    if not text.startswith("/") or " " in text:
        return []
    frag = text.lower()
    return [(cmd, desc) for cmd, desc in COMMANDS if cmd.startswith(frag)]


def build_session(history_path: Path):
    """Build a hacker-green PromptSession. Raises ImportError without the dep."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import Completer, Completion, FuzzyCompleter
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.styles import Style

    outer = complete_slash

    class SlashCompleter(Completer):
        def get_completions(self, document, complete_event):
            for cmd, desc in outer(document.text_before_cursor):
                yield Completion(cmd, start_position=-len(document.text_before_cursor),
                                 display_meta=desc)

    history_path.parent.mkdir(parents=True, exist_ok=True)
    return PromptSession(
        history=FileHistory(str(history_path)),
        completer=FuzzyCompleter(SlashCompleter()),
        auto_suggest=AutoSuggestFromHistory(),
        complete_while_typing=True,
        style=Style.from_dict({"prompt": "ansigreen bold", "": "ansigreen"}),
    )


def prompt_text(session) -> str:
    from prompt_toolkit.formatted_text import HTML
    return session.prompt(HTML("<prompt>\u279c</prompt> "))
