from __future__ import annotations

import shlex
from pathlib import Path
from typing import Tuple

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
            tokens = shlex.split(clean_command)
        except ValueError as err:
            return False, f"Format perintah shell tidak valid: {err}", []

        if not tokens:
            return False, "Perintah tidak valid.", []

        binary_name = Path(tokens[0]).name.lower()
        # Menghapus ekstensi Windows (.exe, .cmd, .bat) untuk normalisasi
        base_binary = binary_name.split(".")[0]

        if binary_name in self.blocked or base_binary in self.blocked:
            return False, f"Perintah diblokir demi keamanan sistem: '{binary_name}'", tokens

        # Cek argumen berbahaya seperti `rm -rf /` atau flag penghapusan sistem
        joined_lower = clean_command.lower()
        if "rm -rf /" in joined_lower or "rm -r /" in joined_lower:
            return False, "Penghapusan direktori root '/' dilarang.", tokens

        return True, "OK", tokens
