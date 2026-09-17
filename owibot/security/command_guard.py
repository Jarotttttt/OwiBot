from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path
from typing import Tuple

_IS_WINDOWS = sys.platform == "win32"

BLOCKED_BINARY_NAMES = {
    "sudo", "su", "dd", "mkfs", "fdisk", "shutdown", "reboot", "halt",
    "poweroff", "chmod", "chown", "chgrp", "format", "reg", "del",
    "rmdir", "attrib", "takeown", "icacls", "diskpart",
}

SAFE_DEVELOPER_TOOLS = {
    "python", "python3", "pip", "git", "ls", "dir", "cat", "type",
    "echo", "node", "npm", "npx", "uv", "pytest", "ruff", "pwd",
    "mkdir", "cp", "copy", "mv", "move", "head", "tail", "find", "grep",
}

# Interpreter/subshell Windows yang dapat digunakan untuk mem-bypass CommandGuard.
# Nama dinormalisasi: lowercase, tanpa ekstensi.
_WINDOWS_SHELL_INTERPRETERS = {
    "cmd", "powershell", "pwsh", "wscript", "cscript",
}

# Flag interpreter yang menandakan inline command execution.
# Diperiksa setelah normalisasi lowercase.
_SHELL_EXEC_FLAGS = {
    "/c", "/k",                        # cmd.exe
    "-command", "-encodedcommand",      # PowerShell
    "-enc", "-c", "-e",                # PowerShell alias singkat
    "-file",                           # PowerShell script file
}


class CommandSecurityError(Exception):
    pass


class CommandGuard:
    def __init__(
        self,
        blocked_commands: set[str] | None = None,
        safe_commands: set[str] | None = None,
    ):
        self.blocked = blocked_commands or set(BLOCKED_BINARY_NAMES)
        self.safe = safe_commands or set(SAFE_DEVELOPER_TOOLS)

    def evaluate_command(self, command_line: str) -> Tuple[bool, str, list[str]]:
        """Mengevaluasi perintah shell.

        Mengembalikan tuple: (is_safe: bool, reason: str, tokenized_args: list[str])
        """
        clean_command = (command_line or "").strip()
        if not clean_command:
            return False, "Perintah tidak boleh kosong.", []

        try:
            # Pada Windows, gunakan posix=False agar backslash path tidak di-strip
            tokens = shlex.split(clean_command, posix=not _IS_WINDOWS)
        except ValueError as err:
            return False, f"Format perintah shell tidak valid: {err}", []

        if not tokens:
            return False, "Perintah tidak valid.", []

        # Strip kutip sisa dari posix=False jika ada
        tokens = [t.strip("'\"") if t.startswith(("'", '"')) and t.endswith(("'", '"')) else t for t in tokens]

        binary_name = Path(tokens[0]).name.lower()
        # Menghapus ekstensi Windows (.exe, .cmd, .bat) untuk normalisasi
        base_binary = binary_name.split(".")[0]

        if binary_name in self.blocked or base_binary in self.blocked:
            return False, f"Perintah diblokir demi keamanan sistem: '{binary_name}'", tokens

        # === Deteksi Windows shell/subshell bypass ===
        shell_blocked, shell_reason = self._check_windows_shell_bypass(tokens, clean_command)
        if shell_blocked:
            return False, shell_reason, tokens

        # Cek argumen berbahaya seperti `rm -rf /` atau flag penghapusan sistem
        joined_lower = clean_command.lower()
        if "rm -rf /" in joined_lower or "rm -r /" in joined_lower:
            return False, "Penghapusan direktori root '/' dilarang.", tokens

        return True, "OK", tokens

    @staticmethod
    def _check_windows_shell_bypass(tokens: list[str], raw_command: str = "") -> Tuple[bool, str]:
        """Memeriksa apakah perintah menggunakan interpreter/subshell Windows untuk bypass.

        Mengembalikan (is_blocked: bool, reason: str).
        """
        if not tokens:
            return False, ""

        # 1. Cek binary utama: apakah itu interpreter Windows?
        primary_bin = Path(tokens[0]).name.lower()
        primary_base = primary_bin.split(".")[0]

        if primary_base in _WINDOWS_SHELL_INTERPRETERS:
            return True, (
                f"Interpreter subshell Windows dilarang: '{tokens[0]}'. "
                "Jalankan perintah secara langsung tanpa membungkus dengan cmd, powershell, pwsh, wscript, atau cscript."
            )

        # 2. Scan seluruh argumen: cek apakah ada interpreter Windows yang disusupkan
        for i, arg in enumerate(tokens[1:], start=1):
            arg_lower = Path(arg).name.lower()
            arg_base = arg_lower.split(".")[0]
            if arg_base in _WINDOWS_SHELL_INTERPRETERS:
                # Cek apakah diikuti flag eksekusi
                remaining_lower = [t.lower() for t in tokens[i + 1:]]
                if any(flag in remaining_lower for flag in _SHELL_EXEC_FLAGS):
                    return True, (
                        f"Deteksi subshell interpreter '{arg}' dengan flag eksekusi dalam argumen. "
                        "Perintah diblokir untuk mencegah bypass keamanan."
                    )

        # 3. Fallback: scan raw command string untuk menangkap kasus di mana
        #    shlex menghilangkan backslash dari path Windows (misalnya C:\Windows\System32\cmd.exe)
        if raw_command:
            cmd_lower = raw_command.lower()
            for interpreter in _WINDOWS_SHELL_INTERPRETERS:
                # Cari pola: interpreter (mungkin diawali path) diikuti spasi dan flag eksekusi
                # Contoh: "C:\...\cmd.exe /c ..." atau "powershell -Command ..."
                pattern = re.compile(
                    rf"(?:^|[\\/\s])(?:[a-z]:\\[^\s]*[\\/])?{re.escape(interpreter)}(?:\.exe|\.cmd|\.bat)?\s",
                    re.IGNORECASE,
                )
                if pattern.search(cmd_lower):
                    return True, (
                        f"Interpreter subshell Windows terdeteksi dalam perintah: '{interpreter}'. "
                        "Jalankan perintah secara langsung tanpa membungkus dengan cmd, powershell, pwsh, wscript, atau cscript."
                    )

        return False, ""
