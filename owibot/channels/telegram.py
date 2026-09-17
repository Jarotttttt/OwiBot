from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Callable

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from owibot.agent import Agent
from owibot.scheduler.cron import CronStore

MAX_CHUNK_LENGTH = 3800
PROGRESS_EDIT_INTERVAL = 1.2


@dataclass
class TelegramSettings:
    token: str = ""
    allow_from: list[str] | None = None


def create_quick_actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Chat Baru", callback_data="action:new"),
            InlineKeyboardButton("📊 Status", callback_data="action:status"),
            InlineKeyboardButton("❓ Bantuan", callback_data="action:help"),
        ]
    ])


class TelegramGateway:
    BOT_COMMANDS = [
        BotCommand("start", "Mulai bot dan tampilkan menu"),
        BotCommand("new", "Mulai percakapan baru"),
        BotCommand("help", "Bantuan dan daftar perintah"),
    ]

    MESSAGES = {
        "help": (
            "*Perintah OwiBot:*\n"
            "• `/start` - Mulai interaksi dan menu cepat\n"
            "• `/new` - Bersihkan percakapan aktif\n"
            "• `/help` - Tampilkan panduan ini\n\n"
            "_Ketik pesan apa saja untuk memulai tugas atau pertanyaan._"
        ),
        "unauthorized": "Akses ditolak: Akun Telegram kamu belum terdaftar dalam daftar allowlist.",
        "unauthorized_start": (
            "Halo! Akun kamu belum terdaftar di allowlist OwiBot.\n"
            "Silakan hubungi pemilik bot untuk menambahkan User ID Telegram kamu."
        ),
        "start": (
            "✨ *OwiBot Siap Digunakan*\n\n"
            "Asisten AI pribadi untuk otomasi task dan kontrol workspace.\n"
            "Silakan ketik pertanyaan atau gunakan tombol cepat di bawah:"
        ),
        "new": "🔄 *Percakapan baru dimulai.* Konteks memori percakapan sebelumnya telah direset.",
        "busy": "⏳ *Sedang bekerja:* Bot masih memproses tugas sebelumnya. Mohon tunggu sebentar.",
    }

    def __init__(self, settings: TelegramSettings, agent_factory: Callable[[], Agent], cron_path: Path):
        self.settings = settings
        self.agent_factory = agent_factory
        self.cron_store = CronStore(cron_path)

        self.application: Application | None = None
        self.agents: dict[str, Agent] = {}
        self.active_tasks: dict[str, asyncio.Task] = {}
        self.cron_task: asyncio.Task | None = None

    def is_user_allowed(self, user_id: int | str, username: str | None) -> bool:
        allowlist = self.settings.allow_from or []
        if not allowlist:
            return False

        if "*" in allowlist:
            return True

        user_id_str = str(user_id)
        clean_username = (username or "").lstrip("@")

        return (user_id_str in allowlist) or (bool(clean_username) and clean_username in allowlist)

    async def verify_access(self, update: Update, custom_denied_message: str | None = None) -> bool:
        user = update.effective_user
        if not user:
            return False

        if self.is_user_allowed(user.id, user.username):
            return True

        denial_text = custom_denied_message or self.MESSAGES["unauthorized"]
        if update.message:
            await update.message.reply_text(denial_text)
        elif update.callback_query:
            await update.callback_query.answer(denial_text, show_alert=True)
        return False

    def _create_agent(self, chat_id: str) -> Agent:
        try:
            agent = self.agent_factory(chat_id)
        except TypeError:
            agent = self.agent_factory()
        agent.chat_id = str(chat_id)
        return agent

    def get_agent_for_chat(self, chat_id: str) -> Agent:
        if chat_id not in self.agents:
            self.agents[chat_id] = self._create_agent(chat_id)
        return self.agents[chat_id]

    async def send_rich_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        if not self.application:
            return

        chunks = split_into_chunks(text)
        for idx, chunk in enumerate(chunks):
            is_last = idx == len(chunks) - 1
            markup = reply_markup if is_last else None

            try:
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    parse_mode="Markdown",
                    reply_markup=markup,
                )
            except Exception:
                # Fallback ke plain text jika format markdown tidak valid
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    reply_markup=markup,
                )

    async def handle_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        message_key: str,
        denied_message: str | None = None,
        reset_agent: bool = False,
    ) -> None:
        if not await self.verify_access(update, denied_message):
            return

        chat_id = str(update.message.chat_id)
        if reset_agent:
            self.agents[chat_id] = self._create_agent(chat_id)

        keyboard = create_quick_actions_keyboard()
        await self.send_rich_message(
            chat_id=update.message.chat_id,
            text=self.MESSAGES[message_key],
            reply_markup=keyboard,
        )

    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query:
            return

        if not await self.verify_access(update):
            return

        await query.answer()
        chat_id = str(query.message.chat_id)
        action = query.data or ""

        if action == "action:new":
            self.agents[chat_id] = self._create_agent(chat_id)
            await query.message.reply_text(
                self.MESSAGES["new"],
                parse_mode="Markdown",
                reply_markup=create_quick_actions_keyboard(),
            )
        elif action == "action:help":
            await query.message.reply_text(
                self.MESSAGES["help"],
                parse_mode="Markdown",
                reply_markup=create_quick_actions_keyboard(),
            )
        elif action == "action:status":
            agent = self.get_agent_for_chat(chat_id)
            skills_count = len(agent.skills.list_skills())
            mem_stats = agent.memory.get_memory_stats()
            mcp_count = len(agent.mcp_manager.clients) if agent.mcp_manager else 0
            tokens_used = getattr(getattr(agent.llm, "cumulative_usage", None), "total_tokens", 0)

            status_report = (
                "📊 *Status Ekosistem OwiBot*\n\n"
                f"• *Model Utama*: `{agent.llm.model}`\n"
                f"• *Endpoint*: `{agent.llm.base_url}`\n"
                f"• *Skills Terdaftar*: `{skills_count}`\n"
                f"• *MCP Servers*: `{mcp_count}` aktif\n"
                f"• *Memori Curated*: `{mem_stats['memory_chars']}/{mem_stats['memory_limit']}` chars\n"
                f"• *Sesi Terindeks (FTS5)*: `{mem_stats['total_indexed_turns']}` turns\n"
                f"• *Kumulatif Token*: `{tokens_used}` total\n"
            )
            await query.message.reply_text(
                status_report,
                parse_mode="Markdown",
                reply_markup=create_quick_actions_keyboard(),
            )

    async def ask_agent_async(
        self,
        chat_id: str,
        prompt: str,
        on_progress: Callable[[str], None] | None = None,
        is_cron: bool = False,
    ) -> str:
        agent = self.get_agent_for_chat(chat_id)
        context = {
            "chat_id": chat_id,
            "is_cron": is_cron,
            "on_progress": on_progress,
        }

        task = asyncio.create_task(asyncio.to_thread(agent.ask, prompt, context))
        self.active_tasks[chat_id] = task
        try:
            return await task
        finally:
            self.active_tasks.pop(chat_id, None)

    async def handle_incoming_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.message.text:
            return
        if not await self.verify_access(update):
            return

        chat_id = str(update.message.chat_id)
        user_text = update.message.text.strip()
        if not user_text:
            return

        active_task = self.active_tasks.get(chat_id)
        if active_task and not active_task.done():
            await update.message.reply_text(self.MESSAGES["busy"], parse_mode="Markdown")
            return

        # Kirim progress status awal
        progress_message = None
        try:
            progress_message = await update.message.reply_text(
                "⏳ _Sedang memproses permintaan..._",
                parse_mode="Markdown",
            )
        except Exception:
            pass

        loop = asyncio.get_running_loop()
        last_edit_time = 0.0

        async def edit_progress_safe(new_text: str):
            if not progress_message:
                return
            try:
                await progress_message.edit_text(f"⏳ _{new_text}_", parse_mode="Markdown")
            except Exception:
                try:
                    await progress_message.edit_text(f"⏳ {new_text}")
                except Exception:
                    pass

        def on_progress_callback(status_text: str):
            nonlocal last_edit_time
            current_now = time.time()
            if current_now - last_edit_time >= PROGRESS_EDIT_INTERVAL:
                last_edit_time = current_now
                asyncio.run_coroutine_threadsafe(edit_progress_safe(status_text), loop)

        try:
            response_text = await self.ask_agent_async(
                chat_id=chat_id,
                prompt=user_text,
                on_progress=on_progress_callback,
            )
        except asyncio.CancelledError:
            return
        except Exception as error:
            response_text = f"❌ Terjadi kesalahan: {error}"
        finally:
            if progress_message:
                with suppress(Exception):
                    await progress_message.delete()

        # Kirim hasil akhir rich message beserta tombol interaktif
        keyboard = create_quick_actions_keyboard()
        await self.send_rich_message(
            chat_id=update.message.chat_id,
            text=response_text,
            reply_markup=keyboard,
        )

    async def run_cron_checker(self) -> None:
        while True:
            try:
                await asyncio.sleep(20)
                if not self.application:
                    continue

                for job in self.cron_store.due():
                    chat_id_str = str(job.get("chat_id", ""))
                    job_id = str(job.get("id", ""))
                    if not chat_id_str or not job_id:
                        continue

                    active_task = self.active_tasks.get(chat_id_str)
                    if active_task and not active_task.done():
                        continue

                    prompt = str(job.get("prompt", "")).strip()
                    if not prompt:
                        self.cron_store.remove(chat_id=None, job_id=job_id)
                        continue

                    try:
                        numeric_chat_id = int(chat_id_str)
                    except ValueError:
                        self.cron_store.remove(chat_id=None, job_id=job_id)
                        continue

                    try:
                        output = await self.ask_agent_async(chat_id_str, prompt, is_cron=True)
                        await self.send_rich_message(numeric_chat_id, output)
                    except Exception as err:
                        try:
                            await self.send_rich_message(numeric_chat_id, f"❌ Error pengingat: {err}")
                        except Exception:
                            pass

                    self.cron_store.mark_ran(job_id=job_id)
            except asyncio.CancelledError:
                return
            except Exception:
                await asyncio.sleep(1)

    async def run_forever(self) -> None:
        token = self.settings.token.strip()
        if not token:
            raise RuntimeError("Token bot Telegram belum dikonfigurasi.")

        self.application = Application.builder().token(token).build()

        commands_map = [
            ("start", {"message_key": "start", "denied_message": self.MESSAGES["unauthorized_start"]}),
            ("new", {"message_key": "new", "reset_agent": True}),
            ("help", {"message_key": "help"}),
        ]

        for command, params in commands_map:
            self.application.add_handler(CommandHandler(command, partial(self.handle_command, **params)))

        self.application.add_handler(CallbackQueryHandler(self.handle_callback_query))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_incoming_message))

        await self.application.initialize()
        await self.application.start()
        await self.application.bot.set_my_commands(self.BOT_COMMANDS)
        await self.application.updater.start_polling(
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=True,
        )

        self.cron_task = asyncio.create_task(self.run_cron_checker())
        try:
            while True:
                await asyncio.sleep(1)
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        for task in list(self.active_tasks.values()):
            task.cancel()
        self.active_tasks.clear()

        if self.cron_task and not self.cron_task.done():
            self.cron_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.cron_task
        self.cron_task = None

        if self.application:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
            self.application = None

        for agent in self.agents.values():
            if getattr(agent, "mcp_manager", None):
                agent.mcp_manager.close_all()


def split_into_chunks(text: str, max_length: int = MAX_CHUNK_LENGTH) -> list[str]:
    content = (text or "").strip() or "(respons kosong)"
    if len(content) <= max_length:
        return [content]

    chunks: list[str] = []
    remaining = content
    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        segment = remaining[:max_length]
        boundary = max(segment.rfind("\n"), segment.rfind(" "))
        split_idx = boundary if boundary >= 0 else max_length

        chunks.append(remaining[:split_idx].strip())
        remaining = remaining[split_idx:].lstrip()

    return chunks
