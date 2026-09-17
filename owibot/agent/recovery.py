from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from .verifier import VerificationResult, VerificationStatus

logger = logging.getLogger("owibot.agent.recovery")


class RecoveryFailureType(str, Enum):
    FILE_MISSING = "file_missing"
    PERMISSION_ERROR = "permission_error"
    COMMAND_FAILURE = "command_failure"
    INVALID_OUTPUT = "invalid_output"
    VERIFICATION_MISMATCH = "verification_mismatch"
    GENERIC_FAILURE = "generic_failure"


@dataclass
class RecoveryAttempt:
    attempt_id: str
    failed_step_id: str
    reason: str
    previous_evidence: str
    corrective_action: str
    result: str = ""
    verification_result: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BaseRecoveryStrategy(ABC):
    @abstractmethod
    def can_handle(self, failure_type: RecoveryFailureType) -> bool:
        pass

    @abstractmethod
    def formulate_action(
        self,
        attempt: int,
        failed_step: Any,
        verification_res: VerificationResult,
        last_record: Any | None,
    ) -> str:
        pass


class FileMissingStrategy(BaseRecoveryStrategy):
    def can_handle(self, failure_type: RecoveryFailureType) -> bool:
        return failure_type == RecoveryFailureType.FILE_MISSING

    def formulate_action(
        self,
        attempt: int,
        failed_step: Any,
        verification_res: VerificationResult,
        last_record: Any | None,
    ) -> str:
        target = verification_res.verified_target or "berkas"
        if attempt == 1:
            return (
                f"Berkas pada {target} tidak ditemukan di disk. Periksa struktur folder saat ini "
                f"menggunakan tool `list_dir` untuk memastikan nama direktori induk dan path relatif sudah tepat."
            )
        if attempt == 2:
            return (
                f"Upaya kedua: Pastikan direktori tujuan sudah dibuat. Gunakan `write_file` dengan path relatif "
                f"bersih di dalam workspace (misal di folder 'projects/')."
            )
        return (
            f"Upaya terakhir: Tulis berkas langsung di root workspace dengan nama sederhana "
            f"dan verifikasi kembali keberadaannya."
        )


class CommandFailureStrategy(BaseRecoveryStrategy):
    def can_handle(self, failure_type: RecoveryFailureType) -> bool:
        return failure_type == RecoveryFailureType.COMMAND_FAILURE

    def formulate_action(
        self,
        attempt: int,
        failed_step: Any,
        verification_res: VerificationResult,
        last_record: Any | None,
    ) -> str:
        args = last_record.arguments if last_record else {}
        cmd = args.get("command", "")
        if attempt == 1:
            return (
                f"Perintah `{cmd}` menghasilkan non-zero exit code. Evaluasi pesan stderr di atas, "
                f"perbaiki argumen/opsi perintah, dan pastikan berkas dependensi yang dibutuhkan ada."
            )
        if attempt == 2:
            return (
                f"Upaya kedua: Hindari sintaks shell yang kompleks. Pecah perintah menjadi langkah terpisah "
                f"atau periksa kelayakan interpreter lingkungan terlebih dahulu."
            )
        return (
            "Upaya terakhir: Gunakan pendekatan alternatif (misal menulis script python pembantu "
            "dan mengeksekusinya) daripada perintah terminal langsung."
        )


class InvalidOutputStrategy(BaseRecoveryStrategy):
    def can_handle(self, failure_type: RecoveryFailureType) -> bool:
        return failure_type == RecoveryFailureType.INVALID_OUTPUT

    def formulate_action(
        self,
        attempt: int,
        failed_step: Any,
        verification_res: VerificationResult,
        last_record: Any | None,
    ) -> str:
        if attempt == 1:
            return (
                "Berkas fisik yang dibuat ternyata kosong (0 byte) atau luaran tool tidak lengkap. "
                "Tulis ulang dengan payload konten yang utuh dan non-kosong."
            )
        return (
            "Upaya lanjutan: Verifikasi parameter konten sebelum penulisan dan pastikan string konten "
            "tidak terpotong atau bernilai None."
        )


class PermissionErrorStrategy(BaseRecoveryStrategy):
    def can_handle(self, failure_type: RecoveryFailureType) -> bool:
        return failure_type == RecoveryFailureType.PERMISSION_ERROR

    def formulate_action(
        self,
        attempt: int,
        failed_step: Any,
        verification_res: VerificationResult,
        last_record: Any | None,
    ) -> str:
        return (
            "Operasi ditolak karena batasan keamanan (path traversal atau hak akses). "
            "Ubah path target agar berada sepenuhnya di dalam direktori workspace atau folder 'projects/'."
        )


class VerificationMismatchStrategy(BaseRecoveryStrategy):
    def can_handle(self, failure_type: RecoveryFailureType) -> bool:
        return failure_type == RecoveryFailureType.VERIFICATION_MISMATCH

    def formulate_action(
        self,
        attempt: int,
        failed_step: Any,
        verification_res: VerificationResult,
        last_record: Any | None,
    ) -> str:
        return (
            "Tool melaporkan status sukses namun verifikasi bukti nyata di disk gagal. "
            "Periksa lokasi berkas sebenarnya dengan `list_dir` dan sinkronkan path penulisan."
        )


class GenericFailureStrategy(BaseRecoveryStrategy):
    def can_handle(self, failure_type: RecoveryFailureType) -> bool:
        return True

    def formulate_action(
        self,
        attempt: int,
        failed_step: Any,
        verification_res: VerificationResult,
        last_record: Any | None,
    ) -> str:
        return (
            f"Verifikasi langkah gagal: {verification_res.reason}. "
            "Ubah strategi atau perbaiki parameter yang salah pada percobaan ini."
        )


class RecoveryManager:
    """Manajer strategi pemulihan terarah berbasis bukti kegagalan."""

    def __init__(self):
        self.strategies: list[BaseRecoveryStrategy] = [
            FileMissingStrategy(),
            CommandFailureStrategy(),
            InvalidOutputStrategy(),
            PermissionErrorStrategy(),
            VerificationMismatchStrategy(),
            GenericFailureStrategy(),  # Fallback
        ]

    def classify_failure(self, verification_res: VerificationResult, last_record: Any | None) -> RecoveryFailureType:
        evidence = (verification_res.evidence or "").lower()
        reason = (verification_res.reason or "").lower()
        output = (last_record.output if last_record else "").lower()

        if "di luar direktori" in evidence or "path traversal" in evidence or "ditolak" in reason:
            return RecoveryFailureType.PERMISSION_ERROR
        if "tidak ditemukan di disk" in evidence or "file tidak ditemukan" in output:
            return RecoveryFailureType.FILE_MISSING
        if "kosong (0 byte)" in evidence or "isi file tidak terisi" in reason:
            return RecoveryFailureType.INVALID_OUTPUT
        if "exit code" in evidence or "non-zero exit code" in evidence or "exit=" in output:
            return RecoveryFailureType.COMMAND_FAILURE
        if "tetapi" in reason and "tidak" in reason:
            return RecoveryFailureType.VERIFICATION_MISMATCH

        return RecoveryFailureType.GENERIC_FAILURE

    def create_recovery_attempt(
        self,
        attempt_number: int,
        step_id: str,
        failed_step: Any,
        verification_res: VerificationResult,
        last_record: Any | None,
    ) -> RecoveryAttempt:
        failure_type = self.classify_failure(verification_res, last_record)

        strategy = next(
            (s for s in self.strategies if s.can_handle(failure_type)),
            GenericFailureStrategy(),
        )

        action = strategy.formulate_action(
            attempt=attempt_number,
            failed_step=failed_step,
            verification_res=verification_res,
            last_record=last_record,
        )

        attempt = RecoveryAttempt(
            attempt_id=f"rec_{step_id}_{attempt_number}_{int(time.time()*1000)%100000}",
            failed_step_id=step_id,
            reason=verification_res.reason,
            previous_evidence=verification_res.evidence,
            corrective_action=action,
        )
        return attempt
