from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Optional

from ..agent import Agent
from ..provider.provider import LLMProvider

CONFIG_DIR_NAME = ".owibot"
DEFAULT_API_BASE = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_CONFIG = {
    "api_base": DEFAULT_API_BASE,
    "model": DEFAULT_MODEL,
    "api_key": "",
}


def app_home() -> Path:
    return (Path.home() / CONFIG_DIR_NAME).expanduser().resolve()


def write_config(path: Path, config: dict) -> None:
    temp_path = path.with_suffix(".json.tmp")
    serialized = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    temp_path.write_text(serialized, encoding="utf-8")
    temp_path.replace(path)


def load_config(path: Path) -> dict:
    if not path.exists():
        raise RuntimeError(f"File konfigurasi tidak ditemukan: {path}")

    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
    except (json.JSONDecodeError, OSError) as err:
        raise RuntimeError(f"Format konfigurasi tidak valid ({path}): {err}") from err

    if not isinstance(data, dict):
        raise RuntimeError(f"Format konfigurasi harus berupa JSON object: {path}")

    if not str(data.get("api_base", "")).strip():
        raise RuntimeError(f"Kunci konfigurasi 'api_base' wajib diisi di {path}")
    if not str(data.get("model", "")).strip():
        raise RuntimeError(f"Kunci konfigurasi 'model' wajib diisi di {path}")

    return data


def ensure_global_config() -> Path:
    directory = app_home()
    directory.mkdir(parents=True, exist_ok=True)
    config_file = directory / "config.json"

    if config_file.exists():
        try:
            content = config_file.read_text(encoding="utf-8").strip()
            if content:
                json.loads(content)
                return config_file
        except (json.JSONDecodeError, OSError):
            pass

    write_config(config_file, dict(DEFAULT_CONFIG))
    return config_file


def get_secret(config: dict) -> str:
    if str(config.get("api_base", "")).strip().lower() == "codex":
        return str(config.get("api_key", "")).strip()

    key = str(config.get("api_key", "")).strip()
    if key:
        return key
    raise RuntimeError("Kunci 'api_key' belum diisi di konfigurasi.")


def ensure_workspace_layout() -> Path:
    workspace = (app_home() / "workspace").resolve()
    for sub in ("projects", "memory", "memory/history", "cron", "skills"):
        (workspace / sub).mkdir(parents=True, exist_ok=True)

    prompts_dir = Path(__file__).resolve().parent.parent / "prompts"
    for filename in ("AGENTS.md",):
        src = prompts_dir / filename
        dst = workspace / filename
        if src.is_file() and not dst.exists():
            shutil.copyfile(src, dst)

    memory_src = prompts_dir / "MEMORY.md"
    memory_dst = workspace / "memory" / "MEMORY.md"
    if memory_src.is_file() and not memory_dst.exists():
        shutil.copyfile(memory_src, memory_dst)

    builtin_skills = Path(__file__).resolve().parent.parent / "skills"
    if builtin_skills.exists():
        for skill_dir in builtin_skills.iterdir():
            skill_file = skill_dir / "SKILL.md"
            if skill_dir.is_dir() and skill_file.is_file():
                dest_dir = workspace / "skills" / skill_dir.name
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_file = dest_dir / "SKILL.md"
                if not dest_file.exists():
                    shutil.copyfile(skill_file, dest_file)

    return workspace


def build_agent_from_config(config: dict, chat_id: str = "default") -> Agent:
    workspace = ensure_workspace_layout()
    model_name = str(config.get("model", "")).strip()
    api_key = get_secret(config)
    api_base = str(config.get("api_base", "")).strip()

    from ..mcp import MCPManager
    from ..observability import configure_logging

    configure_logging(app_home() / "owibot.log")

    mcp_mgr: MCPManager | None = None
    if config.get("mcp_servers"):
        mcp_mgr = MCPManager()
        mcp_mgr.load_from_config(config, cwd=str(workspace))

    return Agent(
        workspace=workspace,
        llm=LLMProvider(
            model=model_name,
            api_key=api_key,
            base_url=api_base,
            cwd=str(workspace),
        ),
        chat_id=chat_id,
        mcp_manager=mcp_mgr,
    )


def _parse_telegram_settings(config: dict) -> tuple[bool, str, list[str]]:
    channels = config.get("channels") if isinstance(config.get("channels"), dict) else {}
    telegram = channels.get("telegram") if isinstance(channels.get("telegram"), dict) else {}
    token = str(telegram.get("token", "")).strip()
    raw_allow = telegram.get("allow_from", [])
    allow_from = [
        str(v).lstrip("@").strip()
        for v in (raw_allow if isinstance(raw_allow, list) else [])
        if str(v).strip()
    ]
    return bool(telegram), token, allow_from


def run_gateway_command(args: list[str] | None = None) -> int:
    from .daemon import is_running, start_detached, stop

    args = args or []
    if "--stop" in args:
        print(stop(app_home()))
        return 0

    config = load_config(ensure_global_config())
    is_enabled, token, allow_from = _parse_telegram_settings(config)

    if not is_enabled:
        print("Telegram belum diaktifkan. Jalankan `owibot setup` terlebih dahulu.")
        return 1
    if not token:
        print("Token bot Telegram belum diisi. Jalankan `owibot setup`.")
        return 1
    if not allow_from:
        print("Allowlist Telegram belum diisi. Jalankan `owibot setup`.")
        return 1

    if "--fg" not in args and "--fg-child" not in args:
        try:
            pid, log_file = start_detached(app_home())
        except RuntimeError as err:
            print(f"Gateway: {err}")
            return 1
        print(f"OwiBot gateway berjalan di background (PID: {pid}).\nLog: {log_file}\nStop: owibot gateway --stop")
        return 0

    if "--fg-child" not in args and (pid := is_running(app_home())) is not None:
        print(f"Gateway sudah berjalan di background (PID: {pid}). Hentikan terlebih dahulu: owibot gateway --stop")
        return 1

    try:
        from ..channels import TelegramGateway, TelegramSettings
    except ImportError as err:
        print(f"Dependensi Telegram tidak ditemukan: {err}")
        return 1

    cron_file = app_home() / "workspace" / "cron" / "cron.json"
    gateway = TelegramGateway(
        settings=TelegramSettings(token=token, allow_from=allow_from),
        agent_factory=lambda cid="default": build_agent_from_config(config, chat_id=cid),
        cron_path=cron_file,
    )

    print("OwiBot gateway aktif (Telegram). Tekan Ctrl+C untuk berhenti.")
    try:
        asyncio.run(gateway.run_forever())
    except KeyboardInterrupt:
        print("\nOwiBot gateway dihentikan.")
    return 0


def run_setup_command() -> int:
    from .setup_wizard import run_setup_flags, run_wizard

    config_path = ensure_global_config()
    try:
        config = load_config(config_path)
    except RuntimeError:
        config = dict(DEFAULT_CONFIG)

    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    extra_args = sys.argv[2:]

    if any(arg.startswith("--") for arg in extra_args):
        if "--help-flags" in extra_args:
            print(
                "owibot setup [flags]:\n"
                "  --api-base URL    Endpoint LLM\n"
                "  --api-key KEY     API key provider\n"
                "  --model MODEL     Nama model\n"
                "  --token TOK       Token bot Telegram\n"
                "  --allow ID1,ID2   User ID Telegram (allowlist)\n"
                "  --yes             Konfirmasi penyimpanan"
            )
            return 0
        try:
            config = run_setup_flags(config, extra_args)
        except RuntimeError as err:
            print(f"Setup gagal: {err}")
            return 1

        ensure_workspace_layout()
        write_config(config_path, config)
        print(f"\nKonfigurasi berhasil disimpan: {config_path}")
        return 0

    if not interactive:
        print("Terminal non-interaktif terdeteksi. Gunakan `owibot setup --help-flags` untuk parameter langsung.")
        return 1

    try:
        config = run_wizard(config)
    except RuntimeError as err:
        print(f"Setup dibatalkan: {err}")
        return 1

    ensure_workspace_layout()
    write_config(config_path, config)
    print(f"\nKonfigurasi berhasil disimpan: {config_path}")
    print("Langkah selanjutnya: jalankan `owibot gateway` untuk memulai bot.")
    return 0


def run_service_command(args: list[str]) -> int:
    from .service import install, status, uninstall

    action = (args[0] if args else "status").lower()
    try:
        if action == "install":
            print(install(scheduled="--scheduled" in args[1:], on_start="--on-start" in args[1:]))
        elif action == "uninstall":
            print(uninstall())
        else:
            print(status())
    except RuntimeError as err:
        print(f"Layanan autostart error: {err}")
        return 1
    return 0


def run_doctor_command() -> int:
    from . import ui

    print(ui.banner("diagnosa sistem"))
    print(f"  Python   : {sys.version.split()[0]} ({sys.executable})")
    print(f"  Console  : stdin_tty={sys.stdin.isatty()} stdout_tty={sys.stdout.isatty()} encoding={getattr(sys.stdout, 'encoding', '?')}")

    try:
        config = load_config(ensure_global_config())
        print(f"  Config   : {ui.green('OK')} ({config.get('model')} @ {config.get('api_base')})")
        is_enabled, token, allow_list = _parse_telegram_settings(config)
        print(f"  Telegram : {'Terkonfigurasi' if (is_enabled and token) else 'Belum terkonfigurasi'}")
        mcp_count = len(config.get("mcp_servers", {})) if isinstance(config.get("mcp_servers"), dict) else 0
        print(f"  MCP      : {mcp_count} server terkonfigurasi")
    except RuntimeError as err:
        print(f"  Config   : {ui.red(str(err))}")

    try:
        from .service import bat_path
        service_active = bat_path().exists()
    except Exception:
        service_active = False

    print(f"  Service  : {'Aktif' if service_active else 'Tidak aktif'} (jalankan `owibot service install` untuk memasang)")
    return 0


def print_usage() -> None:
    from . import ui

    icon = ui.uni(chr(0x25C9), "*")
    print(f"{ui.green(icon + ' owibot')} - Asisten AI Telegram")
    print("  owibot setup               Konfigurasi terpandu (LLM & Telegram)")
    print("  owibot setup --help-flags  Daftar parameter setup non-interaktif")
    print("  owibot gateway             Jalankan gateway bot di background")
    print("  owibot gateway --fg        Jalankan gateway di foreground")
    print("  owibot gateway --stop      Hentikan gateway background")
    print("  owibot service install     Pasang autostart saat login Windows")
    print("  owibot doctor              Periksa status sistem dan konfigurasi")


def main() -> None:
    subcommand = sys.argv[1].lower() if len(sys.argv) >= 2 else ""

    if subcommand == "doctor":
        run_doctor_command()
        return
    if subcommand in {"setup", "onboard"}:
        run_setup_command()
        return
    if subcommand == "gateway":
        run_gateway_command(sys.argv[2:])
        return
    if subcommand == "service":
        run_service_command(sys.argv[2:])
        return

    print_usage()


if __name__ == "__main__":
    main()
