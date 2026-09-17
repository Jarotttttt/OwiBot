from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple


class SecretFinding(NamedTuple):
    file_path: str
    line_number: int
    secret_type: str
    snippet: str


SECRET_RULES = [
    (
        "Telegram Bot Token",
        re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{34,36}\b"),
        {"1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567", "1111222233:AAEFakeTokenForTesting1234567890"},
    ),
    (
        "OpenAI / OpenRouter API Key",
        re.compile(r"\bsk-(?:or-v1-)?[A-Za-z0-9_-]{32,}\b"),
        {"sk-1234567890abcdef1234567890abcdef"},
    ),
    (
        "GitHub Token",
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}\b"),
        set(),
    ),
    (
        "Private Key",
        re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |)PRIVATE KEY-----"),
        set(),
    ),
]

IGNORE_DIRS = {
    ".git", ".pytest_cache", "__pycache__", "node_modules", "dist", "build",
    "venv", ".venv", "env", "owibot.egg-info",
}

IGNORE_EXTENSIONS = {
    ".pyc", ".png", ".jpg", ".jpeg", ".ico", ".svg", ".lock",
}


def scan_file(file_path: Path) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return findings

    for line_idx, line in enumerate(content.splitlines(), start=1):
        for rule_name, regex, whitelist in SECRET_RULES:
            matches = regex.findall(line)
            for match in matches:
                if match in whitelist or "REDACTED" in line or "placeholder" in line.lower():
                    continue
                snippet = line.strip()[:100]
                findings.append(
                    SecretFinding(
                        file_path=str(file_path),
                        line_number=line_idx,
                        secret_type=rule_name,
                        snippet=snippet,
                    )
                )

    return findings


def scan_directory(root_path: Path) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for path in root_path.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in IGNORE_EXTENSIONS:
            continue

        findings.extend(scan_file(path))

    return findings
