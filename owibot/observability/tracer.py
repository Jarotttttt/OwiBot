from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from ..provider.base import TokenUsage


@dataclass
class TraceEvent:
    event_type: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    duration_s: float = 0.0


@dataclass
class TurnTelemetry:
    chat_id: str = "default"
    turn_id: str = ""
    prompt: str = ""
    final_response: str = ""
    events: list[TraceEvent] = field(default_factory=list)
    tokens: TokenUsage = field(default_factory=TokenUsage)
    llm_calls: int = 0
    tools_used: list[str] = field(default_factory=list)
    total_duration_s: float = 0.0
    status: str = "success"
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "chat_id": self.chat_id,
            "turn_id": self.turn_id,
            "prompt": self.prompt,
            "final_response": self.final_response,
            "llm_calls": self.llm_calls,
            "tools_used": self.tools_used,
            "tokens": self.tokens.to_dict(),
            "total_duration_s": self.total_duration_s,
            "status": self.status,
            "error_message": self.error_message,
            "events_count": len(self.events),
        }


class AgentTracer:
    def __init__(self, chat_id: str = "default"):
        self.chat_id = chat_id
        self.current_turn: TurnTelemetry | None = None
        self._turn_start_time: float = 0.0

    def start_turn(self, prompt: str, turn_id: str | None = None) -> TurnTelemetry:
        self._turn_start_time = time.monotonic()
        tid = turn_id or f"turn_{int(time.time() * 1000)}"
        self.current_turn = TurnTelemetry(
            chat_id=self.chat_id,
            turn_id=tid,
            prompt=prompt[:200],
        )
        self.record_event("turn_start", {"prompt": prompt[:200]})
        return self.current_turn

    def record_event(self, event_type: str, data: dict[str, Any], duration_s: float = 0.0) -> None:
        if not self.current_turn:
            return
        event = TraceEvent(event_type=event_type, data=data, duration_s=round(duration_s, 3))
        self.current_turn.events.append(event)

    def record_llm_call(self, model: str, usage: TokenUsage, latency_s: float) -> None:
        if not self.current_turn:
            return
        self.current_turn.llm_calls += 1
        self.current_turn.tokens.prompt_tokens += usage.prompt_tokens
        self.current_turn.tokens.completion_tokens += usage.completion_tokens
        self.current_turn.tokens.total_tokens += usage.total_tokens
        self.record_event(
            "llm_call",
            {"model": model, "usage": usage.to_dict(), "latency_s": latency_s},
            duration_s=latency_s,
        )

    def record_tool_call(self, tool_name: str, args: dict[str, Any], duration_s: float, status: str = "OK") -> None:
        if not self.current_turn:
            return
        self.current_turn.tools_used.append(tool_name)
        self.record_event(
            "tool_dispatch",
            {"tool": tool_name, "args": args, "status": status, "duration_s": duration_s},
            duration_s=duration_s,
        )

    def finish_turn(self, final_response: str, error: str | None = None) -> TurnTelemetry:
        if not self.current_turn:
            self.start_turn("")

        elapsed = round(time.monotonic() - self._turn_start_time, 3)
        self.current_turn.total_duration_s = elapsed
        self.current_turn.final_response = final_response[:200]
        if error:
            self.current_turn.status = "error"
            self.current_turn.error_message = error
            self.record_event("turn_error", {"error": error})
        else:
            self.current_turn.status = "success"
            self.record_event("turn_end", {"total_duration_s": elapsed})

        return self.current_turn
