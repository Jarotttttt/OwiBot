from __future__ import annotations

import json
import subprocess
import time
from typing import Any, Optional

from .base import BaseLLMProvider, LLMResponse, TokenUsage


def _format_codex_prompt(messages: list[dict], tools: Optional[list[dict]]) -> str:
    turns = []
    for msg in messages:
        if isinstance(msg, dict) and msg.get("content"):
            role = msg.get("role", "user").upper()
            turns.append(f"{role}:\n{msg.get('content')}")

    base_prompt = "\n\n".join(turns).strip()
    if not tools:
        return base_prompt

    tool_specs = [
        {
            "name": (t.get("function") or {}).get("name"),
            "description": (t.get("function") or {}).get("description", ""),
            "parameters": (t.get("function") or {}).get("parameters", {}),
        }
        for t in tools
        if isinstance(t, dict)
    ]

    instructions = (
        "\n\nAvailable tools (JSON):\n"
        + json.dumps(tool_specs, ensure_ascii=False)
        + "\nReturn ONLY JSON with shape: "
        + '{"text":"...","tool_calls":[{"name":"tool_name","arguments":{}}]}.\n'
        + "When a tool is needed, set tool_calls; when final, set tool_calls to [] and put answer in text."
    )
    return base_prompt + instructions


def _parse_codex_output(raw_output: str, model: str, latency: float) -> LLMResponse:
    text = (raw_output or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2 and lines[-1].strip().startswith("```"):
            text = "\n".join(lines[1:-1]).strip()
        else:
            text = "\n".join(lines[1:]).strip()

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return LLMResponse(text=raw_output or "(respons kosong)", model=model, latency_s=latency)

    if not isinstance(data, dict):
        return LLMResponse(text=raw_output or "(respons kosong)", model=model, latency_s=latency)

    parsed_calls = []
    for idx, call in enumerate(data.get("tool_calls") or [], start=1):
        if isinstance(call, dict) and call.get("name"):
            args = call.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {"raw": args}
            parsed_calls.append({
                "id": f"codex_call_{idx}",
                "name": call["name"],
                "arguments": args if isinstance(args, dict) else {},
            })

    return LLMResponse(
        text=str(data.get("text", "")),
        tool_calls=parsed_calls,
        model=model,
        latency_s=latency,
    )


class CodexCLIProvider(BaseLLMProvider):
    def __init__(self, model: str = "codex", cwd: Optional[str] = None):
        super().__init__(model=model, base_url="codex", api_key="")
        self.cwd = cwd

    def chat(self, messages: list[dict], tools: Optional[list[dict]] = None) -> LLMResponse:
        prompt_text = _format_codex_prompt(messages, tools)
        command = [
            "codex", "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
            prompt_text,
        ]

        start_time = time.monotonic()
        try:
            proc = subprocess.run(
                command,
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except FileNotFoundError as err:
            raise RuntimeError("CLI Codex tidak ditemukan di PATH.") from err

        latency = round(time.monotonic() - start_time, 3)

        if proc.returncode != 0:
            err_output = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"Gagal menjalankan Codex CLI: {err_output or proc.returncode}")

        raw_stdout = (proc.stdout or proc.stderr or "").strip()
        if tools:
            return _parse_codex_output(raw_stdout, model=self.model, latency=latency)

        return LLMResponse(text=raw_stdout or "(respons kosong)", model=self.model, latency_s=latency)
