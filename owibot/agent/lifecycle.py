from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from ..observability import AgentTracer
from ..provider.base import LLMResponse, TokenUsage
from .recovery import RecoveryAttempt, RecoveryManager
from .verifier import StepVerificationManager, VerificationResult, VerificationStatus

logger = logging.getLogger("owibot.agent.lifecycle")


class AgentPhase(str, Enum):
    UNDERSTAND = "understand"
    PLAN = "plan"
    EXECUTE = "execute"
    VERIFY = "verify"
    RECOVER = "recover"
    FINALIZE = "finalize"


class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PlanStep:
    id: str
    description: str
    status: StepStatus = StepStatus.PENDING
    result: str = ""
    verification_status: VerificationStatus = VerificationStatus.UNKNOWN
    verification_evidence: str = ""
    verification_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status.value if isinstance(self.status, StepStatus) else str(self.status),
            "result": self.result,
            "verification_status": (
                self.verification_status.value
                if isinstance(self.verification_status, VerificationStatus)
                else str(self.verification_status)
            ),
            "verification_evidence": self.verification_evidence,
            "verification_reason": self.verification_reason,
        }


def formulate_plan_steps(user_message: str) -> list[PlanStep]:
    clean_text = (user_message or "").strip()

    # 1. Deteksi langkah bernomor eksplisit (1. ..., 2. ...)
    numbered_matches = re.findall(
        r"(?:^|\n)\s*(\d+)[\.\)]\s*(.+?)(?=(?:\n\s*\d+[\.\)]|\Z))",
        clean_text,
        re.DOTALL,
    )
    if numbered_matches:
        steps: list[PlanStep] = []
        for idx, desc in numbered_matches:
            steps.append(
                PlanStep(
                    id=f"step_{idx}",
                    description=desc.strip().replace("\n", " "),
                    status=StepStatus.PENDING,
                    result="",
                )
            )
        if steps:
            return steps

    # 2. Deteksi sekuens kata penghubung (lalu, kemudian, setelah itu)
    connectors = ["lalu", "kemudian", "setelah itu"]
    for conn in connectors:
        pattern = rf"\s+{conn}\s+"
        if re.search(pattern, clean_text, re.IGNORECASE):
            parts = re.split(pattern, clean_text, flags=re.IGNORECASE)
            valid_parts = [p.strip() for p in parts if p.strip()]
            if len(valid_parts) > 1:
                return [
                    PlanStep(
                        id=f"step_{i}",
                        description=part[:100],
                        status=StepStatus.PENDING,
                        result="",
                    )
                    for i, part in enumerate(valid_parts, start=1)
                ]

    # 3. Heuristik tugas kompleks multi-tahap
    text_lower = clean_text.lower()
    if any(k in text_lower for k in ("buatkan", "bangun", "implementasi", "refactor", "coding", "bikin", "analisis dan")):
        return [
            PlanStep(id="step_1", description="Analisis konteks dan periksa kebutuhan berkas", status=StepStatus.PENDING, result=""),
            PlanStep(id="step_2", description="Eksekusi implementasi kode atau modifikasi file", status=StepStatus.PENDING, result=""),
            PlanStep(id="step_3", description="Verifikasi dan konfirmasi hasil eksekusi", status=StepStatus.PENDING, result=""),
        ]

    # 4. Tugas tunggal
    fallback_desc = clean_text[:80] if clean_text else "Eksekusi instruksi pengguna"
    return [
        PlanStep(id="step_1", description=fallback_desc, status=StepStatus.PENDING, result="")
    ]


def map_tool_call_to_step(
    call: dict[str, Any],
    plan_steps: list[PlanStep],
    assigned_steps: set[str],
) -> PlanStep | None:
    """Memetakan pemanggilan tool ke plan step yang tepat."""
    tool_args = call.get("arguments", {})
    if isinstance(tool_args, str):
        try:
            tool_args = json.loads(tool_args)
        except Exception:
            tool_args = {}

    target_tokens: list[str] = []
    if "path" in tool_args:
        p_str = str(tool_args["path"]).strip()
        target_tokens.append(Path(p_str).name.lower())
        target_tokens.append(p_str.lower())
    if "command" in tool_args:
        cmd_tokens = [t.lower() for t in str(tool_args["command"]).split() if len(t) > 2]
        target_tokens.extend(cmd_tokens[:3])
    if "query" in tool_args:
        target_tokens.extend(str(tool_args["query"]).lower().split()[:3])

    # 1. Cari step PENDING/IN_PROGRESS yang secara eksplisit mencocokkan target_token
    for step in plan_steps:
        if step.status in (StepStatus.PENDING, StepStatus.IN_PROGRESS):
            step_desc_lower = step.description.lower()
            if any(token in step_desc_lower for token in target_tokens if len(token) > 1):
                return step

    # 2. Fallback deterministik: petakan ke step aktif saat ini yang belum selesai
    # (Jangan melompat ke step pending berikutnya jika tidak ada kecocokan eksplisit)
    for step in plan_steps:
        if step.status == StepStatus.IN_PROGRESS:
            return step
    for step in plan_steps:
        if step.status == StepStatus.PENDING:
            return step

    return None


@dataclass
class ToolExecutionRecord:
    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    output: str
    duration_s: float
    is_error: bool = False


@dataclass
class LifecycleState:
    chat_id: str
    user_message: str
    effective_prompt: str
    phase: AgentPhase = AgentPhase.UNDERSTAND
    step: int = 0
    max_steps: int = 30
    recovery_attempts: int = 0
    max_recovery_attempts: int = 3
    tool_executions: list[ToolExecutionRecord] = field(default_factory=list)
    plan_steps: list[PlanStep] = field(default_factory=list)
    verification_notes: list[str] = field(default_factory=list)
    recovery_history: list[RecoveryAttempt] = field(default_factory=list)
    step_recovery_counts: dict[str, int] = field(default_factory=dict)
    final_response: str = ""
    is_finished: bool = False
    is_cron: bool = False
    on_progress: Callable[[str], None] | None = None

    def get_current_step(self) -> PlanStep | None:
        for s in self.plan_steps:
            if s.status == StepStatus.IN_PROGRESS:
                return s
        for s in self.plan_steps:
            if s.status == StepStatus.PENDING:
                return s
        return None

    def format_plan_status(self) -> str:
        lines = []
        for s in self.plan_steps:
            res_preview = f" => {s.result[:40]}..." if s.result else ""
            v_tag = f" [{s.verification_status.value.upper()}]" if s.verification_status != VerificationStatus.UNKNOWN else ""
            lines.append(f"- [{s.status.value.upper()}]{v_tag} {s.id}: {s.description}{res_preview}")
        return "\n".join(lines)


class AgentLifecycleEngine:
    """Mesin pengendali lifecycle Agent:

    understand -> plan -> execute -> verify -> recover -> finalize
    """

    def __init__(self, agent: Any):
        self.agent = agent
        self.verifier = StepVerificationManager(self.agent.workspace)
        self.agent.verifier = self.verifier
        self.recovery_mgr = RecoveryManager()
        self.agent.recovery_mgr = self.recovery_mgr

    def notify_progress(self, state: LifecycleState, message: str) -> None:
        if callable(state.on_progress):
            state.on_progress(message)

    def run(self, user_message: str, context: dict[str, Any] | None = None) -> str:
        ctx = dict(context or {})
        is_cron = bool(ctx.get("is_cron"))
        on_progress = ctx.get("on_progress")

        state = LifecycleState(
            chat_id=self.agent.chat_id,
            user_message=user_message,
            effective_prompt=(
                f"[Tugas Terjadwal] Waktu pengingat tiba.\nInstruksi: {user_message.strip()}."
                if is_cron
                else user_message
            ),
            max_steps=getattr(self.agent, "max_steps", 30),
            is_cron=is_cron,
            on_progress=on_progress,
        )

        self.agent.tracer.start_turn(prompt=user_message)

        # 1. UNDERSTAND
        state.phase = AgentPhase.UNDERSTAND
        conversation = self._phase_understand(state)

        # 2. PLAN (Menyusun struktur plan_steps stateful)
        state.phase = AgentPhase.PLAN
        self._phase_plan(state, conversation)

        # 3. EXECUTE - VERIFY - RECOVER LOOP
        while state.step < state.max_steps and not state.is_finished:
            state.step += 1
            state.phase = AgentPhase.EXECUTE

            llm_response = self._step_llm_call(state, conversation)
            tool_calls = llm_response.get("tool_calls", [])

            if not tool_calls:
                state.final_response = (llm_response.get("text") or "").strip() or "(respons kosong)"
                conversation.append({"role": "assistant", "content": state.final_response})
                state.is_finished = True
                break

            # Menjalankan batch tool calls dengan pemetaan step terisolasi
            execution_pairs = self._step_execute_tools(state, conversation, tool_calls)

            # 4. VERIFY (Evaluasi hasil per-step berbasis evidence nyata)
            state.phase = AgentPhase.VERIFY
            self.notify_progress(state, "🛡️ Memverifikasi evidence hasil eksekusi...")

            steps_with_records: dict[str, tuple[PlanStep, list[ToolExecutionRecord]]] = {}
            for step_obj, rec in execution_pairs:
                if step_obj:
                    if step_obj.id not in steps_with_records:
                        steps_with_records[step_obj.id] = (step_obj, [])
                    steps_with_records[step_obj.id][1].append(rec)

            turn_had_verification_failure = False

            for step_id, (step_obj, step_recs) in steps_with_records.items():
                verification_res = self.verifier.verify_batch(step_recs)

                step_obj.verification_status = verification_res.status
                step_obj.verification_evidence = verification_res.evidence
                step_obj.verification_reason = verification_res.reason
                state.verification_notes.append(
                    f"{step_obj.id}: [{verification_res.status.value.upper()}] {verification_res.reason}"
                )

                if state.recovery_history and state.recovery_history[-1].failed_step_id == step_id and not state.recovery_history[-1].verification_result:
                    last_attempt = state.recovery_history[-1]
                    last_attempt.verification_result = verification_res.status.value
                    last_attempt.result = "\n".join(f"{r.tool_name} -> {r.output[:120]}" for r in step_recs)

                conversation.append({
                    "role": "system",
                    "content": verification_res.format_for_context(),
                })

                if verification_res.status == VerificationStatus.FAILED:
                    turn_had_verification_failure = True

                    attempts = state.step_recovery_counts.get(step_id, 0) + 1
                    state.step_recovery_counts[step_id] = attempts
                    state.recovery_attempts += 1

                    if attempts <= 3:
                        # Tetap IN_PROGRESS selama dalam batas recovery (maksimal 3 percobaan)
                        step_obj.status = StepStatus.IN_PROGRESS
                        state.phase = AgentPhase.RECOVER
                        last_record = step_recs[-1] if step_recs else None
                        attempt_record = self.recovery_mgr.create_recovery_attempt(
                            attempt_number=attempts,
                            step_id=step_id,
                            failed_step=step_obj,
                            verification_res=verification_res,
                            last_record=last_record,
                        )
                        state.recovery_history.append(attempt_record)

                        self.notify_progress(
                            state,
                            f"🔧 Pemulihan #{attempts} pada {step_id}: {attempt_record.corrective_action[:50]}...",
                        )

                        recovery_prompt = (
                            f"[Phase: Recover - Percobaan {attempts}/3 untuk {step_id}]:\n"
                            f"• Evidence Kegagalan: {verification_res.evidence}\n"
                            f"• Analisis Masalah: {verification_res.reason}\n"
                            f"• Tindakan Korektif: {attempt_record.corrective_action}\n"
                            "Lakukan tindakan korektif di atas sekarang. Jangan mengulang perintah atau parameter yang persis sama."
                        )
                        conversation.append({"role": "system", "content": recovery_prompt})
                        break
                    else:
                        # Melebihi batas maksimal 3 attempt: tandai FAILED secara permanen
                        step_obj.status = StepStatus.FAILED
                        self.notify_progress(state, f"❌ Pemulihan gagal setelah 3 percobaan pada {step_id}")
                        state.final_response = (
                            f"Tugas dihentikan: Langkah '{step_id}' gagal diverifikasi setelah 3 kali percobaan pemulihan.\n"
                            f"• Target: {verification_res.verified_target}\n"
                            f"• Alasan Terakhir: {verification_res.reason}\n"
                            f"• Evidence Terakhir: {verification_res.evidence}"
                        )
                        state.is_finished = True
                        break
                else:
                    # Verifikasi passed
                    step_obj.status = StepStatus.COMPLETED

            if state.is_finished:
                break

            if turn_had_verification_failure:
                continue

            next_step = state.get_current_step()
            if next_step:
                conversation.append({
                    "role": "system",
                    "content": f"[Plan Progress]: Langkah selesai terverifikasi. Langkah selanjutnya: {next_step.id}: {next_step.description}",
                })

        if not state.final_response:
            state.final_response = (
                "Batas langkah eksekusi tercapai sebelum tugas selesai. "
                "Silakan ulangi dengan instruksi yang lebih spesifik."
            )

        # 6. FINALIZE
        state.phase = AgentPhase.FINALIZE
        return self._phase_finalize(state)

    def _phase_understand(self, state: LifecycleState) -> list[dict]:
        self.notify_progress(state, "⏳ Menganalisis dan memahami permintaan...")
        current_time = time.strftime("%Y-%m-%dT%H:%M:%S")
        conversation = self.agent._assemble_prompt(state.effective_prompt, timestamp_iso=current_time)
        return conversation

    def _phase_plan(self, state: LifecycleState, conversation: list[dict]) -> None:
        state.plan_steps = formulate_plan_steps(state.user_message)

        is_complex = len(state.plan_steps) > 1 or any(
            k in state.user_message.lower()
            for k in ("buatkan", "bangun", "implementasi", "refactor", "analisis dan", "lalu")
        )

        if is_complex and not state.is_cron:
            self.notify_progress(state, "📋 Menyusun strategi eksekusi...")

        plan_summary = state.format_plan_status()
        conversation.append({
            "role": "system",
            "content": (
                f"[Phase: Plan]:\n{plan_summary}\n"
                "Eksekusi tugas mengikuti urutan langkah rencana di atas secara sistematis."
            ),
        })

    def _step_llm_call(self, state: LifecycleState, conversation: list[dict]) -> LLMResponse:
        llm_start = time.monotonic()
        available_tools = self.agent.get_available_tools()
        response = self.agent.llm.chat(conversation, tools=available_tools)
        latency = round(time.monotonic() - llm_start, 3)

        usage = response.get("usage", TokenUsage())
        if isinstance(usage, dict):
            usage = TokenUsage(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
            )

        self.agent.tracer.record_llm_call(
            model=response.get("model", self.agent.llm.model),
            usage=usage,
            latency_s=latency,
        )
        return response

    def _step_execute_tools(
        self,
        state: LifecycleState,
        conversation: list[dict],
        tool_calls: list[dict],
    ) -> list[tuple[PlanStep | None, ToolExecutionRecord]]:
        conversation.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                    },
                }
                for call in tool_calls
            ],
        })

        assigned_step_ids: set[str] = set()
        execution_pairs: list[tuple[PlanStep | None, ToolExecutionRecord]] = []

        for call in tool_calls:
            tool_name = call["name"]
            tool_args = call.get("arguments", {})

            matched_step = map_tool_call_to_step(call, state.plan_steps, assigned_step_ids)
            if matched_step:
                assigned_step_ids.add(matched_step.id)
                if matched_step.status == StepStatus.PENDING:
                    matched_step.status = StepStatus.IN_PROGRESS

            progress_desc = self.agent.format_tool_progress(tool_name, tool_args)
            self.notify_progress(state, progress_desc)

            t_start = time.monotonic()
            raw_output = self.agent.dispatch_tool(tool_name, tool_args)
            duration = round(time.monotonic() - t_start, 3)

            is_err = raw_output.startswith("ERROR:") or "exit=1" in raw_output
            record = ToolExecutionRecord(
                call_id=call["id"],
                tool_name=tool_name,
                arguments=tool_args,
                output=raw_output,
                duration_s=duration,
                is_error=is_err,
            )
            state.tool_executions.append(record)
            execution_pairs.append((matched_step, record))

            self.agent.tracer.record_tool_call(
                tool_name=tool_name,
                args=tool_args,
                duration_s=duration,
                status="ERROR" if is_err else "OK",
            )

            conversation.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "name": tool_name,
                "content": raw_output[:5000],
            })

        step_to_records: dict[str, list[ToolExecutionRecord]] = {}
        for step, rec in execution_pairs:
            if step:
                step_to_records.setdefault(step.id, []).append(rec)

        for step in state.plan_steps:
            if step.id in step_to_records:
                s_recs = step_to_records[step.id]
                step.result = "\n".join(f"{r.tool_name} -> {r.output[:150]}" for r in s_recs)

        return execution_pairs

    def _phase_finalize(self, state: LifecycleState) -> str:
        self.notify_progress(state, "📝 Menyusun jawaban akhir...")
        final_text = state.final_response

        has_failed_step = any(s.status == StepStatus.FAILED for s in state.plan_steps)
        has_unfinished_step = any(s.status in (StepStatus.PENDING, StepStatus.IN_PROGRESS) for s in state.plan_steps)
        is_timeout = (state.step >= state.max_steps) and has_unfinished_step

        if is_timeout:
            # PRIORITAS 1: Tandai langkah yang belum selesai sebagai FAILED, bukan COMPLETED
            for s in state.plan_steps:
                if s.status in (StepStatus.PENDING, StepStatus.IN_PROGRESS):
                    s.status = StepStatus.FAILED
                    s.verification_status = VerificationStatus.FAILED
                    s.verification_reason = "Langkah tidak selesai karena batas langkah eksekusi tercapai (timeout)."
                    s.verification_evidence = f"Batas max_steps={state.max_steps} tercapai sebelum langkah ini dieksekusi atau diverifikasi."
            has_failed_step = True
            if not final_text or "Batas langkah" not in final_text:
                final_text = (
                    f"Tugas tidak tuntas: Batas langkah eksekusi tercapai (max_steps={state.max_steps}). "
                    "Beberapa langkah dalam rencana gagal diselesaikan."
                )

        # Hanya untuk percakapan langsung tanpa pemanggilan tool sama sekali
        if not state.tool_executions and len(state.plan_steps) == 1 and not has_failed_step:
            single_step = state.plan_steps[0]
            if single_step.status == StepStatus.PENDING:
                single_step.status = StepStatus.COMPLETED
                single_step.verification_status = VerificationStatus.PASSED
                single_step.verification_evidence = "Respons percakapan langsung dari model."
                single_step.verification_reason = "Tuntas pada respons final."
                single_step.result = final_text[:150]

        self.agent.last_plan = state.plan_steps
        self.agent.last_lifecycle_state = state

        self.agent.recent_history.append({"role": "user", "content": state.user_message})
        self.agent.recent_history.append({"role": "assistant", "content": final_text})
        self.agent.recent_history = self.agent.recent_history[-10:]

        self.agent.memory.append_turn(state.user_message, final_text, chat_id=state.chat_id)

        # PRIORITAS 4: Telemetri turn mencatat error jika terjadi kegagalan / timeout
        if has_failed_step:
            self.agent.tracer.finish_turn(final_response=final_text, error=final_text[:200])
        else:
            self.agent.tracer.finish_turn(final_response=final_text)

        return final_text
