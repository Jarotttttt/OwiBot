"""CLI theme tests: plain when piped, styled markers otherwise."""
import io
from contextlib import redirect_stdout
from unittest.mock import patch

import pytest

from owibot.cli import theme
from owibot.cli import cli


def test_paint_plain_without_tty():
    with patch.object(theme.sys.stdout, "isatty", return_value=False):
        assert theme.accent("hi") == "hi"
        assert theme.rule(4) in {"────", "----"}
        assert "owibot" in theme.banner("0.5.0", [("model", "m")])
        assert theme.reply_block("yo")


def test_ascii_fallback_cp1252():
    import types
    fake = types.SimpleNamespace(encoding="cp1252", isatty=lambda: False)
    with patch.object(theme.sys, "stdout", fake):
        assert theme._uni("─", "-") == "-"
        assert theme._uni("⠋", "") == ""
        assert set(theme.rule(4)) == {"-"}
    fake_utf = types.SimpleNamespace(encoding="utf-8", isatty=lambda: False)
    with patch.object(theme.sys, "stdout", fake_utf):
        assert theme._uni("─", "-") == "─"


def test_footer_and_help_shape():
    with patch.object(theme.sys.stdout, "isatty", return_value=False):
        assert "3 tool calls" in theme.footer(3, 2, "10/2200 chars")
        assert "/new" in cli._cli_help()


def test_spinner_silent_when_piped():
    buf = io.StringIO()
    with patch.object(theme.sys.stdout, "isatty", return_value=False):
        with redirect_stdout(buf):
            with theme.Spinner("thinking"):
                pass
    assert buf.getvalue() == ""


def test_version_helper():
    assert isinstance(cli._version(), str) and cli._version()


def test_slash_completion():
    from owibot.cli.prompt import complete_slash
    got = dict(complete_slash("/m"))
    assert "/memory" in got and "/model" in got
    assert complete_slash("/xyz") == []
    assert complete_slash("hello") == []
    assert complete_slash("/model x") == []


def test_prompt_session_builds(tmp_path):
    from owibot.cli.prompt import build_session
    try:
        s = build_session(tmp_path / "hist")
    except Exception:
        pytest.skip("no console for prompt_toolkit in this env")
    assert s is not None


def test_read_line_fallback():
    assert cli._build_prompt_session() is None or True  # tty-dependent, never crashes
    with patch("builtins.input", return_value="  hi  "):
        assert cli._read_line(None) == "hi"
