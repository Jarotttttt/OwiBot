"""Test Security: PathGuard, CommandGuard, SecretRedactor."""
from pathlib import Path
import pytest

from owibot.security import (
    CommandGuard,
    PathGuard,
    PathTraversalError,
    SecretRedactor,
)


def test_path_guard_safe_resolution(tmp_path):
    guard = PathGuard(tmp_path)
    safe = guard.resolve_safe_path("projects/my_app/main.py")
    assert safe == (tmp_path / "projects/my_app/main.py").resolve()
    assert guard.resolve_safe_path(".") == tmp_path.resolve()


def test_path_guard_detects_traversal(tmp_path):
    guard = PathGuard(tmp_path)
    with pytest.raises(PathTraversalError):
        guard.resolve_safe_path("../../etc/passwd")

    with pytest.raises(PathTraversalError):
        guard.resolve_safe_path("foo/bar/../../../escaped")

    with pytest.raises(PathTraversalError):
        guard.resolve_safe_path("file\x00.txt")


def test_command_guard_blocks_dangerous():
    guard = CommandGuard()
    is_safe, reason, _ = guard.evaluate_command("sudo rm -rf /")
    assert not is_safe
    assert "diblokir" in reason

    is_safe, reason, _ = guard.evaluate_command("shutdown /s /t 0")
    assert not is_safe

    is_safe, reason, _ = guard.evaluate_command("mkfs.ext4 /dev/sda1")
    assert not is_safe

    is_safe, reason, _ = guard.evaluate_command("rm -rf /")
    assert not is_safe
    assert "root" in reason


def test_command_guard_allows_safe_tools():
    guard = CommandGuard()
    is_safe, reason, tokens = guard.evaluate_command("python script.py --arg value")
    assert is_safe
    assert tokens == ["python", "script.py", "--arg", "value"]

    is_safe, _, tokens = guard.evaluate_command("git status")
    assert is_safe


def test_secret_redactor_masks_credentials():
    raw_telegram = "Pesan berisi token bot 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567 berhasil login"
    cleaned = SecretRedactor.redact(raw_telegram)
    assert "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567" not in cleaned
    assert "[REDACTED_TELEGRAM_TOKEN]" in cleaned

    raw_openai = "Menggunakan sk-1234567890abcdef1234567890abcdef untuk autentikasi"
    cleaned_ai = SecretRedactor.redact(raw_openai)
    assert "sk-1234567890abcdef" not in cleaned_ai
    assert "[REDACTED_API_KEY]" in cleaned_ai

    raw_bearer = "Authorization: Bearer my_secret_token_1234567890abcdef"
    cleaned_bearer = SecretRedactor.redact(raw_bearer)
    assert "my_secret_token_1234567890abcdef" not in cleaned_bearer
