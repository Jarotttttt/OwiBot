"""CLI theme tests: plain when piped, styled markers otherwise."""
import io
from contextlib import redirect_stdout
from unittest.mock import patch

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
