"""Setup UI + flags tests (mocked network)."""
from unittest.mock import patch

from owibot.cli import ui
from owibot.cli.setup_wizard import run_setup_flags


def test_ui_basics():
    assert "judul" in ui.box("judul", ["baris satu"])
    assert "[2/4]" in ui.steps(2, 4, "Tes")
    assert ui.green("x") == "x" or "\033[" in ui.green("x")  # tty-dependent


def test_uni_fallback():
    import types
    fake = types.SimpleNamespace(encoding="cp1252", isatty=lambda: False)
    with patch.object(ui.sys, "stdout", fake):
        assert ui.uni("─", "-") == "-"
    fake_utf = types.SimpleNamespace(encoding="utf-8", isatty=lambda: False)
    with patch.object(ui.sys, "stdout", fake_utf):
        assert ui.uni("─", "-") == "─"


def test_run_setup_flags():
    args = ["--api-base", "http://x/v1", "--api-key", "k", "--model", "m",
            "--token", "tok", "--allow", "1,2", "--mem-gate", "--yes"]
    with patch("owibot.cli.setup_wizard.check_telegram", return_value="@bot"), \
         patch("owibot.cli.setup_wizard.test_chat", return_value="OK"):
        cfg = run_setup_flags({}, args)
    assert cfg["model"] == "m"
    assert cfg["channels"]["telegram"]["allow_from"] == ["1", "2"]
    assert cfg["memory"] == {"write_approval": True}
    assert cfg["skills"] == {"write_approval": False}


def test_run_setup_flags_needs_yes():
    with patch("owibot.cli.setup_wizard.test_chat", return_value="OK"):
        try:
            run_setup_flags({}, ["--model", "m"])
        except RuntimeError as e:
            assert "--yes" in str(e)
        else:
            raise AssertionError("expected RuntimeError")
