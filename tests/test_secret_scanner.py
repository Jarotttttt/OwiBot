"""Test Automated Secret Scanning to prevent committing sensitive credentials."""
from pathlib import Path
import pytest

from owibot.security import scan_directory, scan_file


def test_scanner_detects_real_looking_token(tmp_path):
    dirty_file = tmp_path / "leaked.env"
    fake_token = "9988776655" + ":" + "AAEz9876543210zyxwvutsrqponmlkjihg"
    dirty_file.write_text(f"BOT_TOKEN={fake_token}\n", encoding="utf-8")

    findings = scan_file(dirty_file)
    assert len(findings) == 1
    assert findings[0].secret_type == "Telegram Bot Token"


def test_scanner_allows_whitelisted_placeholders(tmp_path):
    clean_file = tmp_path / "config.example.json"
    clean_file.write_text('{"token": "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567"}\n', encoding="utf-8")

    findings = scan_file(clean_file)
    assert len(findings) == 0


def test_entire_repository_is_clean_of_secrets():
    repo_root = Path(__file__).resolve().parent.parent
    findings = scan_directory(repo_root)

    if findings:
        report = "\n".join(f"{f.file_path}:{f.line_number} [{f.secret_type}] -> {f.snippet}" for f in findings)
        pytest.fail(f"Ditemukan credential/rahasia yang tidak tersensor di repository:\n{report}")
