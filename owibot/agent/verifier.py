from __future__ import annotations

import json
import logging
import os
import re

logger = logging.getLogger("owibot.agent.verifier")
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ..security.path_guard import PathGuard


class VerificationStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass
class VerificationResult:
    status: VerificationStatus
    evidence: str
    reason: str
    verified_target: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value if isinstance(self.status, VerificationStatus) else str(self.status),
            "evidence": self.evidence,
            "reason": self.reason,
            "verified_target": self.verified_target,
        }

    def format_for_context(self) -> str:
        status_str = self.status.value.upper() if isinstance(self.status, VerificationStatus) else str(self.status).upper()
        return (
            f"[Phase: Verify - {status_str}]:\n"
            f"• Target: {self.verified_target}\n"
            f"• Evidence: {self.evidence}\n"
            f"• Evaluasi: {self.reason}"
        )


class BaseToolVerifier(ABC):
    @abstractmethod
    def can_verify(self, tool_name: str) -> bool:
        """Menentukan apakah verifier menangani tool ini."""
        pass

    @abstractmethod
    def verify(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        output: str,
        workspace: Path,
    ) -> VerificationResult:
        """Memverifikasi luaran tool berdasarkan evidence nyata sistem/filesystem."""
        pass


class WriteFileVerifier(BaseToolVerifier):
    def can_verify(self, tool_name: str) -> bool:
        return tool_name in {"write_file", "create_file"}

    def verify(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        output: str,
        workspace: Path,
    ) -> VerificationResult:
        target_path_str = str(arguments.get("path", "")).strip()
        expected_content = arguments.get("content")

        target_desc = f"{tool_name}({target_path_str})"

        if not target_path_str:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                evidence="Argumen 'path' kosong.",
                reason="Verifikasi gagal karena path target tidak ditentukan.",
                verified_target=target_desc,
            )

        # 1. Cek keamanan path & resolusi ke filesystem nyata
        guard = PathGuard(workspace)
        try:
            resolved_file = guard.resolve_safe_path(target_path_str)
        except Exception as exc:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                evidence=f"Path traversal terdeteksi: {exc}",
                reason="File berada di luar batas direktori workspace yang diizinkan.",
                verified_target=target_desc,
            )

        # 2. Cek evidence fisik berkas di filesystem
        if not resolved_file.exists():
            return VerificationResult(
                status=VerificationStatus.FAILED,
                evidence=f"Berkas fisik tidak ditemukan di disk pada: {resolved_file}",
                reason="Tool mengklaim berhasil atau selesai, tetapi berkas tidak tercipta di filesystem nyata.",
                verified_target=target_desc,
            )

        if not resolved_file.is_file():
            return VerificationResult(
                status=VerificationStatus.FAILED,
                evidence=f"Path '{resolved_file}' adalah direktori, bukan file biasa.",
                reason="Target yang dibuat bukan berkas reguler.",
                verified_target=target_desc,
            )

        # 3. Cek ukuran dan integritas konten berkas
        try:
            file_size = resolved_file.stat().st_size
            actual_content = resolved_file.read_text(encoding="utf-8", errors="ignore")
        except OSError as os_err:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                evidence=f"Gagal membaca status berkas di disk: {os_err}",
                reason="Berkas ada tetapi tidak dapat diakses untuk verifikasi integritas.",
                verified_target=target_desc,
            )

        if expected_content is not None and len(expected_content) > 0 and file_size == 0:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                evidence=f"Berkas '{target_path_str}' ada di disk namun kosong (0 byte). Konten yang diharapkan: {len(expected_content)} karakter.",
                reason="Isi file tidak terisi sesuai dengan instruksi penulisan.",
                verified_target=target_desc,
            )

        # 4. Evaluasi respon output tool
        if output.startswith("ERROR:"):
            return VerificationResult(
                status=VerificationStatus.FAILED,
                evidence=f"Output tool melaporkan kesalahan: {output[:150]}",
                reason="Operasi tool menghasilkan error saat penulisan.",
                verified_target=target_desc,
            )

        return VerificationResult(
            status=VerificationStatus.PASSED,
            evidence=f"Berkas '{target_path_str}' terverifikasi ada di disk ({file_size} byte). Lokasi: {resolved_file.relative_to(workspace)}",
            reason="Tujuan pembuatan/penulisan berkas berhasil diverifikasi di filesystem nyata.",
            verified_target=target_desc,
        )


class ReadFileVerifier(BaseToolVerifier):
    def can_verify(self, tool_name: str) -> bool:
        return tool_name == "read_file"

    def verify(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        output: str,
        workspace: Path,
    ) -> VerificationResult:
        target_path_str = str(arguments.get("path", "")).strip()
        target_desc = f"read_file({target_path_str})"

        if output.startswith("ERROR:"):
            return VerificationResult(
                status=VerificationStatus.FAILED,
                evidence=f"Output tool: {output[:150]}",
                reason="Pembacaan berkas gagal karena file tidak ditemukan atau error akses.",
                verified_target=target_desc,
            )

        return VerificationResult(
            status=VerificationStatus.PASSED,
            evidence=f"Konten berkas '{target_path_str}' berhasil dibaca ({len(output)} karakter diperoleh).",
            reason="Informasi berkas berhasil dimuat ke dalam konteks.",
            verified_target=target_desc,
        )


class ExecCommandVerifier(BaseToolVerifier):
    def can_verify(self, tool_name: str) -> bool:
        return tool_name in {"exec", "execute_code"}

    def verify(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        output: str,
        workspace: Path,
    ) -> VerificationResult:
        cmd_str = str(arguments.get("command", arguments.get("code", ""))).strip()
        target_desc = f"{tool_name}({cmd_str[:40]})"

        if output.startswith("ERROR:"):
            return VerificationResult(
                status=VerificationStatus.FAILED,
                evidence=f"Tool error: {output[:200]}",
                reason="Perintah ditolak oleh guard keamanan atau gagal dieksekusi oleh subprocess.",
                verified_target=target_desc,
            )

        # Cari exit code pada format standar "exit=X"
        exit_match = re.search(r"\bexit=(-?\d+)\b", output)
        if exit_match:
            exit_code = int(exit_match.group(1))
            if exit_code != 0:
                # Cari cuplikan stderr jika ada
                stderr_match = re.search(r"stderr:\n(.*?)(?=\nstdout:|\Z)", output, re.DOTALL)
                stderr_snippet = stderr_match.group(1).strip()[:200] if stderr_match else "Tanpa pesan stderr"
                return VerificationResult(
                    status=VerificationStatus.FAILED,
                    evidence=f"Perintah selesai dengan non-zero exit code ({exit_code}). Stderr: {stderr_snippet}",
                    reason=f"Proses terminal mengembalikan error status {exit_code}.",
                    verified_target=target_desc,
                )

        return VerificationResult(
            status=VerificationStatus.PASSED,
            evidence=f"Perintah selesai dengan exit code 0. Luaran proses: {len(output)} karakter.",
            reason="Eksekusi terminal sukses tanpa error.",
            verified_target=target_desc,
        )


class MemoryUpdateVerifier(BaseToolVerifier):
    def can_verify(self, tool_name: str) -> bool:
        return tool_name == "update_memory"

    def verify(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        output: str,
        workspace: Path,
    ) -> VerificationResult:
        target_desc = "update_memory"
        mem_file = workspace / "memory" / "MEMORY.md"

        if output.startswith("ERROR:"):
            return VerificationResult(
                status=VerificationStatus.FAILED,
                evidence=f"Output: {output[:150]}",
                reason="Pembaruan memori ditolak.",
                verified_target=target_desc,
            )

        if not mem_file.is_file():
            return VerificationResult(
                status=VerificationStatus.FAILED,
                evidence="File MEMORY.md tidak ditemukan di direktori memori.",
                reason="Berkas penyimpanan memori fisik tidak ada di disk.",
                verified_target=target_desc,
            )

        expected_snippet = str(arguments.get("content", "")).strip()[:50]
        actual_mem = mem_file.read_text(encoding="utf-8", errors="ignore")
        if expected_snippet and expected_snippet not in actual_mem:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                evidence="Konten baru tidak ditemukan di dalam berkas MEMORY.md fisik.",
                reason="Operasi dilaporkan berhasil tetapi data tidak persisten di disk.",
                verified_target=target_desc,
            )

        return VerificationResult(
            status=VerificationStatus.PASSED,
            evidence=f"MEMORY.md terverifikasi di disk ({len(actual_mem)} karakter).",
            reason="Catatan memori jangka panjang berhasil diperbarui.",
            verified_target=target_desc,
        )


class GenericToolVerifier(BaseToolVerifier):
    """Fallback verifier untuk tool umum lainnya (web_fetch, session_search, dll)."""

    def can_verify(self, tool_name: str) -> bool:
        return True

    def verify(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        output: str,
        workspace: Path,
    ) -> VerificationResult:
        target_desc = f"{tool_name}({json.dumps(arguments, ensure_ascii=False)[:40]})"

        if output.startswith("ERROR:"):
            return VerificationResult(
                status=VerificationStatus.FAILED,
                evidence=f"Tool error: {output[:150]}",
                reason=f"Tool '{tool_name}' gagal mengeksekusi aksi yang diminta.",
                verified_target=target_desc,
            )

        return VerificationResult(
            status=VerificationStatus.PASSED,
            evidence=f"Tool '{tool_name}' mengembalikan luaran valid ({len(output)} karakter).",
            reason="Operasi dieksekusi tanpa error.",
            verified_target=target_desc,
        )


class StepVerificationManager:
    """Registry dan orkestrator verifikasi berbasis evidence."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.verifiers: list[BaseToolVerifier] = [
            WriteFileVerifier(),
            ReadFileVerifier(),
            ExecCommandVerifier(),
            MemoryUpdateVerifier(),
            GenericToolVerifier(),  # Fallback di urutan terakhir
        ]

    def register_verifier(self, verifier: BaseToolVerifier, priority_first: bool = True) -> None:
        if priority_first:
            self.verifiers.insert(0, verifier)
        else:
            self.verifiers.append(verifier)

    def verify_tool_execution(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        output: str,
    ) -> VerificationResult:
        for verifier in self.verifiers:
            try:
                if verifier.can_verify(tool_name):
                    return verifier.verify(
                        tool_name=tool_name,
                        arguments=arguments,
                        output=output,
                        workspace=self.workspace,
                    )
            except Exception as exc:
                logger.error(
                    "Verifier %s mengalami crash tak terduga pada tool %s: %s",
                    type(verifier).__name__,
                    tool_name,
                    exc,
                )
                return VerificationResult(
                    status=VerificationStatus.FAILED,
                    evidence=f"Internal error pada verifier: {type(exc).__name__}",
                    reason=f"Verifier mengalami kegagalan internal saat memverifikasi luaran {tool_name}.",
                    verified_target=tool_name,
                )

        return VerificationResult(
            status=VerificationStatus.UNKNOWN,
            evidence=f"Tidak ada verifier spesifik untuk '{tool_name}'.",
            reason="Status verifikasi tidak dapat ditentukan.",
            verified_target=tool_name,
        )

    def verify_batch(
        self,
        records: list[Any],
    ) -> VerificationResult:
        """Memverifikasi seluruh eksekusi tool pada batch langkah saat ini."""
        if not records:
            return VerificationResult(
                status=VerificationStatus.PASSED,
                evidence="Tidak ada pemanggilan tool yang perlu diverifikasi pada tahap ini.",
                reason="Langkah tidak memerlukan verifikasi filesystem/perintah.",
                verified_target="no_tools",
            )

        results: list[VerificationResult] = []
        for record in records:
            res = self.verify_tool_execution(
                tool_name=record.tool_name,
                arguments=record.arguments,
                output=record.output,
            )
            results.append(res)

        # Jika ada satu saja verifikasi yang gagal, seluruh batch langkah dinyatakan FAILED
        failed_results = [r for r in results if r.status == VerificationStatus.FAILED]
        if failed_results:
            first_fail = failed_results[0]
            combined_evidence = " | ".join(r.evidence for r in failed_results)
            return VerificationResult(
                status=VerificationStatus.FAILED,
                evidence=combined_evidence,
                reason=f"Verifikasi gagal pada {first_fail.verified_target}: {first_fail.reason}",
                verified_target=first_fail.verified_target,
            )

        # Jika semua passed
        all_evidence = " | ".join(r.evidence for r in results)
        first_target = results[0].verified_target if results else "batch"
        return VerificationResult(
            status=VerificationStatus.PASSED,
            evidence=all_evidence,
            reason="Semua luaran tool berhasil diverifikasi terhadap evidence nyata.",
            verified_target=first_target,
        )
