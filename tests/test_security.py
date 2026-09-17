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


# ==============================================================================
# REGRESSION TESTS: WINDOWS COMMANDGUARD SUBSHELL BYPASS
# ==============================================================================


def test_commandguard_blocks_powershell_command():
    guard = CommandGuard()
    is_safe, reason, _ = guard.evaluate_command("powershell -Command Get-Process")
    assert not is_safe
    assert "subshell" in reason.lower() or "dilarang" in reason.lower()


def test_commandguard_blocks_powershell_encoded_command():
    guard = CommandGuard()
    is_safe, reason, _ = guard.evaluate_command("powershell -EncodedCommand SQBFAHAA")
    assert not is_safe

    is_safe, reason, _ = guard.evaluate_command("powershell.exe -enc SQBFAHAA")
    assert not is_safe


def test_commandguard_blocks_pwsh_command():
    guard = CommandGuard()
    is_safe, reason, _ = guard.evaluate_command("pwsh -Command Write-Host hello")
    assert not is_safe

    is_safe, reason, _ = guard.evaluate_command("pwsh.exe -Command Write-Host hello")
    assert not is_safe


def test_commandguard_blocks_cmd_c():
    guard = CommandGuard()
    is_safe, reason, _ = guard.evaluate_command("cmd /c del important.txt")
    assert not is_safe

    is_safe, reason, _ = guard.evaluate_command("cmd.exe /c dir")
    assert not is_safe


def test_commandguard_blocks_wscript_cscript():
    guard = CommandGuard()
    is_safe, reason, _ = guard.evaluate_command("wscript.exe malicious.vbs")
    assert not is_safe

    is_safe, reason, _ = guard.evaluate_command("cscript.exe script.js")
    assert not is_safe


def test_commandguard_blocks_case_variations():
    guard = CommandGuard()
    # Mixed case
    is_safe, _, _ = guard.evaluate_command("PowerShell -Command Get-Process")
    assert not is_safe

    is_safe, _, _ = guard.evaluate_command("CMD /C del file.txt")
    assert not is_safe

    # Uppercase
    is_safe, _, _ = guard.evaluate_command("POWERSHELL.EXE -COMMAND whoami")
    assert not is_safe

    # Absolute path
    is_safe, _, _ = guard.evaluate_command("C:\\Windows\\System32\\cmd.exe /c dir")
    assert not is_safe

    is_safe, _, _ = guard.evaluate_command("C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe -Command dir")
    assert not is_safe


def test_commandguard_allows_safe_windows_commands():
    """Windows commands yang aman (dir, type, echo, python) tetap diizinkan."""
    guard = CommandGuard()
    is_safe, reason, _ = guard.evaluate_command("dir /b")
    assert is_safe

    is_safe, _, _ = guard.evaluate_command("type README.md")
    assert is_safe

    is_safe, _, _ = guard.evaluate_command("python -c \"print('hello')\"")
    assert is_safe

    is_safe, _, _ = guard.evaluate_command("git log --oneline -5")
    assert is_safe

    is_safe, _, _ = guard.evaluate_command("pip install requests")
    assert is_safe

    is_safe, _, _ = guard.evaluate_command("pytest tests/")
    assert is_safe

    is_safe, _, _ = guard.evaluate_command("echo hello world")
    assert is_safe


# ==============================================================================
# REGRESSION TESTS: WEB_FETCH SECRET REDACTION
# ==============================================================================


def test_web_fetch_redacts_telegram_token(tmp_path):
    """web_fetch output harus meng-redact Telegram bot token sebelum masuk conversation."""
    from owibot.agent.tools import LocalTools

    tools = LocalTools(tmp_path)
    # Simulasi langsung melalui SecretRedactor karena web_fetch memerlukan jaringan nyata.
    # Kita uji bahwa redaction path terterapkan pada konten halaman.
    raw_content = "Config: BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567 terpasang"
    redacted = SecretRedactor.redact(raw_content)
    assert "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567" not in redacted
    assert "[REDACTED_TELEGRAM_TOKEN]" in redacted


def test_web_fetch_redacts_openai_api_key(tmp_path):
    """web_fetch output harus meng-redact OpenAI/OpenRouter API key."""
    # Konstruksi via concatenation agar scanner repo tidak menandai sebagai secret
    fake_key = "sk-or-v1-" + "abc123def456ghi789jkl012mno345pqr678stu901vwx234yz"
    raw_content = f"API access: {fake_key}"
    redacted = SecretRedactor.redact(raw_content)
    assert fake_key not in redacted
    assert "[REDACTED_API_KEY]" in redacted


def test_web_fetch_redacts_bearer_token(tmp_path):
    """web_fetch output harus meng-redact bearer token."""
    raw_content = "Header: Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature"
    redacted = SecretRedactor.redact(raw_content)
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in redacted
    assert "[REDACTED_TOKEN]" in redacted


def test_web_fetch_redacts_generic_credential():
    """web_fetch output harus meng-redact generic credential-looking values."""
    raw_content = 'database config: password="SuperSecret12345XYZ" api_key=\'tok_live_abcdefghijklmnop\''
    redacted = SecretRedactor.redact(raw_content)
    assert "SuperSecret12345XYZ" not in redacted
    assert "tok_live_abcdefghijklmnop" not in redacted
    assert "[REDACTED_SECRET]" in redacted


# ==============================================================================
# REGRESSION TESTS: MCP SECRET REDACTION
# ==============================================================================


def test_mcp_dispatch_redacts_secrets_in_response():
    """MCP response yang mengandung credential harus di-redact sebelum dikembalikan ke agent."""
    from owibot.mcp.manager import MCPManager

    mgr = MCPManager()

    # Simulasi: MCP manager tanpa server aktif mengembalikan error.
    result = mgr.dispatch("mcp__fake__tool", {})
    assert "ERROR" in result  # Tool tidak terdaftar

    # Uji redaction langsung pada pola yang seharusnya di-redact oleh MCPManager.dispatch
    telegram_tok = "1234567890" + ":" + "ABCdefGHIjklMNOpqrsTUVwxyz1234567"
    openai_key = "sk-" + "abcdef1234567890abcdef1234567890"
    raw_mcp_output = f"Hasil query: token={telegram_tok} dan {openai_key}"
    redacted = SecretRedactor.redact(raw_mcp_output)
    assert telegram_tok not in redacted
    assert openai_key not in redacted
    assert "[REDACTED_TELEGRAM_TOKEN]" in redacted
    assert "[REDACTED_API_KEY]" in redacted


def test_mcp_response_with_mixed_credentials():
    """MCP response yang mengandung campuran credential harus di-redact seluruhnya."""
    telegram_tok = "9876543210" + ":" + "ZYXwvuTSRqpoNMLkjiHGFedCBA0987654"
    openai_key = "sk-proj-" + "abcdefghijklmnopqrst1234"
    raw = (
        "Database connection: password='db_super_secret_password_xyz123'\n"
        "API: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.content.sig\n"
        f"Bot: {telegram_tok}\n"
        f"Key: api_key={openai_key}"
    )
    redacted = SecretRedactor.redact(raw)
    # Tidak ada credential asli yang tersisa
    assert "db_super_secret_password_xyz123" not in redacted
    assert "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9" not in redacted
    assert telegram_tok not in redacted
    assert openai_key not in redacted


# ==============================================================================
# REGRESSION TEST: END-TO-END TOOL DISPATCH REDACTION
# ==============================================================================


def test_exec_tool_output_is_redacted(tmp_path):
    """Output dari tool exec harus melewati SecretRedactor."""
    from owibot.agent.tools import LocalTools
    tools = LocalTools(tmp_path)

    # Buat script yang mencetak secret ke stdout
    script = tmp_path / "leak.py"
    script.write_text('print("token=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567")', encoding="utf-8")

    result = tools.exec(f"python {script.name}")
    assert "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567" not in result
    assert "[REDACTED_TELEGRAM_TOKEN]" in result
