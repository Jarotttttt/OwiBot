from __future__ import annotations

import re

SECRET_PATTERNS = [
    # Telegram bot token (e.g. 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567)
    (re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{32,36}\b"), "[REDACTED_TELEGRAM_TOKEN]"),
    # OpenAI / OpenRouter sk-* keys
    (re.compile(r"\bsk-(?:or-v1-)?[A-Za-z0-9_-]{20,}\b"), "[REDACTED_API_KEY]"),
    # Generic bearer tokens
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9_\-\.]{20,}"), r"\1[REDACTED_TOKEN]"),
    # Key-value secret assignments (api_key="...", password='...')
    (
        re.compile(r"(?i)(api[_-]?key|password|secret|token)([\"'\s:=]+)[\"']?[A-Za-z0-9_\-\.]{12,}[\"']?"),
        r"\1\2[REDACTED_SECRET]",
    ),
]


class SecretRedactor:
    @staticmethod
    def redact(text: str) -> str:
        if not text:
            return ""

        result = str(text)
        for pattern, replacement in SECRET_PATTERNS:
            result = pattern.sub(replacement, result)
        return result
