"""Best-effort voice memo transcription.

Supported: OpenAI-compatible endpoints that expose
POST {base_url}/audio/transcriptions (OpenAI, Azure-style).
Anything else raises VoiceNotSupported so the gateway can reply honestly.
"""
from __future__ import annotations

import io
import json
import os
import uuid
from urllib.parse import urlparse
from urllib.request import Request, urlopen

TRANSCRIBE_MODEL = "whisper-1"
MAX_BYTES = 25 * 1024 * 1024


class VoiceNotSupported(RuntimeError):
    pass


def build_multipart(file_bytes: bytes, filename: str, fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = f"----owibot{uuid.uuid4().hex}"
    buf = io.BytesIO()
    for key, value in fields.items():
        buf.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode())
    buf.write((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
               "Content-Type: audio/ogg\r\n\r\n").encode())
    buf.write(file_bytes)
    buf.write(f"\r\n--{boundary}--\r\n".encode())
    return buf.getvalue(), boundary


def transcribe_openai(base_url: str, api_key: str, path: str,
                      model: str = TRANSCRIBE_MODEL) -> str:
    host = (urlparse(base_url or "").hostname or "").lower()
    if host not in {"api.openai.com"}:
        raise VoiceNotSupported(
            "Voice transcription needs an OpenAI-compatible audio endpoint; "
            "current provider does not offer one. Send text instead."
        )
    if not api_key or api_key == "local":
        raise VoiceNotSupported("No API key configured for transcription. Send text instead.")
    size = os.path.getsize(path)
    if size > MAX_BYTES:
        raise VoiceNotSupported("Voice memo too large (>25MB). Send a shorter one or text.")
    with open(path, "rb") as f:
        raw = f.read()
    body, boundary = build_multipart(raw, "memo.ogg", {"model": model})
    req = Request(f"{base_url.rstrip('/')}/audio/transcriptions", data=body, method="POST",
                  headers={"Authorization": f"Bearer {api_key}",
                           "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    text = str(data.get("text", "")).strip()
    if not text:
        raise RuntimeError("Transcription returned empty text.")
    return text


def make_transcriber(base_url: str, api_key: str):
    """Return a path->text callable, or None when the provider can't transcribe."""
    host = (urlparse(base_url or "").hostname or "").lower()
    if host not in {"api.openai.com"} or not api_key or api_key == "local":
        return None
    return lambda path: transcribe_openai(base_url, api_key, path)
