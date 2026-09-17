from __future__ import annotations
import asyncio
import os
import tempfile
import time
from contextlib import suppress
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Callable
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters
from owibot.agent.core import Agent
from owibot.agent.tools import parse_pending_marker
from owibot.scheduler.cron import CronStore

AgentFactory = Callable[..., Agent]


@dataclass
class TelegramSettings:
    token: str = ""
    allow_from: list[str] | None = None


class TelegramGateway:
    BOT_COMMANDS = [BotCommand("start", "Show startup guide"), BotCommand("new", "Reset current chat"), BotCommand("model", "Show or change model"), BotCommand("retry", "Retry last message"), BotCommand("undo", "Remove last exchange"), BotCommand("compress", "Compress context"), BotCommand("usage", "Session + memory usage"), BotCommand("sessions", "Recent prompts in this chat"), BotCommand("memory", "Memory budgets"), BotCommand("skills", "List installed skills"), BotCommand("learn", "Save workflow as skill"), BotCommand("bg", "Run prompt in background"), BotCommand("stop", "Stop the running task"), BotCommand("help", "List command usage")]
    TXT = {
        "help": ("Available commands:\n/new, /model [name] [--global|--once], /retry, /undo,\n/compress, /usage, /sessions, /memory, /skills,\n/learn <name> | <material>, /bg <prompt>, /stop, /help\n\nSend a voice memo and I'll transcribe it when your provider allows.\nTip: /new at task boundaries — memory pays off on fresh sessions."),
        "unauth": "Unauthorized user.",
        "unauth_start": "You are not on the allowlist. Ask the owner to add your Telegram ID in channels.telegram.allow_from.",
        "start": "OwiBot gateway is online.\nUse /new to start a clean session.\nUse /help to view command usage.",
        "new": "Started a new conversation (memory snapshot reloaded).",
        "busy": "Still processing your previous message. /stop to cancel, or wait and try again.",
        "stopped": "Stopped the running task.",
        "idle": "No running task.",
        "pending_first": "Resolve the pending request above first (/approve or /deny button, or answer the question). Your message was not processed — resend it after.",
        "voice_unsupported": "Voice memos need an OpenAI audio endpoint; your provider has none configured. Send text instead.",
    }

    def __init__(self, settings: TelegramSettings, agent_factory: AgentFactory, cron_path: Path, save_global_model=None, voice_transcribe=None):
        self.settings, self.agent_factory = settings, agent_factory
        self._save_global_model = save_global_model
        self._voice_transcribe = voice_transcribe
        self._app, self._agents, self._active, self._cron, self._cron_task = None, {}, {}, CronStore(cron_path), None
        self._bg: dict[str, str] = {}
        self._model_once: dict[str, str] = {}

    def _allowed(self, uid, username):
        allow, sid, uname = self.settings.allow_from or [], str(uid), (username or "").lstrip("@")
        return bool(allow) and ("*" in allow or sid in allow or (uname and uname in allow))

    async def _access(self, update, denied=None):
        if not (m := update.message) or not (u := update.effective_user): return False
        if self._allowed(u.id, u.username): return True
        await m.reply_text(denied or self.TXT["unauth"]); return False

    def _agent(self, cid):
        if cid not in self._agents:
            try: agent = self.agent_factory(cid)
            except TypeError: agent = self.agent_factory()
            agent.chat_id = cid
            self._agents[cid] = agent
        return self._agents[cid]

    def _pending_of(self, agent) -> tuple[str, dict] | tuple[None, None]:
        for pid, entry in agent.pending.items():
            return pid, entry
        return None, None

    def _card(self, agent, pid: str, trailing: str):
        """Render a pending request as (text, markup) with inline buttons."""
        entry = agent.pending.get(pid)
        if entry is None:
            return "That request already expired. Send your message again.", None
        op = entry["op"]
        if op.get("kind") == "clarify":
            lines = [f"❓ {op.get('question', '')}"]
            buttons = []
            for i, opt in enumerate(op.get("options") or []):
                lines.append(f"{i + 1}. {opt}")
                buttons.append([InlineKeyboardButton(f"{i + 1}. {opt[:40]}", callback_data=f"cl:{pid}:{i}")])
            if not buttons:
                lines.append("Reply with your answer.")
            return "\n".join(lines), InlineKeyboardMarkup(buttons) if buttons else None
        text = f"🔐 {trailing or 'Approval needed.'}"
        return text, InlineKeyboardMarkup([[InlineKeyboardButton("✅ Allow", callback_data=f"ap:{pid}"),
                                            InlineKeyboardButton("❌ Deny", callback_data=f"dn:{pid}")]])

    async def _deliver(self, chat_id: int, out: str, agent, edit_msg=None):
        if pid := parse_pending_marker(out):
            trailing = out.split("⟫", 1)[1].strip() if "⟫" in out else ""
            text, markup = self._card(agent, pid, trailing)
            if edit_msg is not None:
                await edit_msg.edit_text(text, reply_markup=markup)
            else:
                await self._app.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)
            return
        if edit_msg is not None:
            try: await edit_msg.delete()
            except Exception: pass
        for chunk in _chunks(out):
            await self._app.bot.send_message(chat_id=chat_id, text=chunk)

    async def _reply_cmd(self, update, text):
        await update.message.reply_text(text)

    async def _on_cmd(self, update, context, key, denied=None, reset=False):
        if not await self._access(update, denied): return
        if reset:
            cid = str(update.message.chat_id)
            try: self._agents[cid] = self.agent_factory(cid)
            except TypeError: self._agents[cid] = self.agent_factory()
            self._agents[cid].chat_id = cid
        await self._reply_cmd(update, self.TXT[key])

    async def _on_simple(self, update, context, fn):
        if not await self._access(update): return
        await self._reply_cmd(update, fn(self._agent(str(update.message.chat_id))))

    async def _on_model(self, update, context):
        if not await self._access(update): return
        cid = str(update.message.chat_id)
        raw = (update.message.text or "")[6:].strip()
        if not raw:
            await self._reply_cmd(update, f"Current model: {self._agent(cid).llm.model}\nUsage: /model <provider:model> [--global|--once]")
            return
        once = raw.endswith("--once"); glob = raw.endswith("--global")
        name = raw[: -len("--once") if once else -len("--global") if glob else len(raw)].strip()
        if not name:
            await self._reply_cmd(update, "Usage: /model <provider:model> [--global|--once]"); return
        if glob and self._save_global_model:
            self._save_global_model(name)
            self._agents.pop(cid, None)
            await self._reply_cmd(update, f"Global model set to {name}.")
        elif once:
            self._model_once[cid] = name
            await self._reply_cmd(update, f"Next turn only will use {name}.")
        else:
            await self._reply_cmd(update, self._agent(cid).set_model(name))

    async def _on_sessions(self, update, context):
        if not await self._access(update): return
        agent = self._agent(str(update.message.chat_id))
        items = agent.memory.recent_prompts(agent.chat_id)
        await self._reply_cmd(update, "Recent prompts in this chat:\n" + "\n".join(items) if items else "No history in this chat yet.")

    async def _on_memory(self, update, context):
        if not await self._access(update): return
        agent = self._agent(str(update.message.chat_id))
        st = agent.memory.stats(agent.chat_id)
        await self._reply_cmd(update, f"MEMORY.md: {st['memory']}\nUSER.md: {st['user']}\nHistory turns: {st['turns']} (~{st['chars']} chars)")

    async def _on_skills(self, update, context):
        if not await self._access(update): return
        agent = self._agent(str(update.message.chat_id))
        idx = agent.skills.index_text()
        await self._reply_cmd(update, "Installed skills:\n" + idx if idx else "No skills installed yet.")

    async def _on_learn(self, update, context):
        if not await self._access(update): return
        cid = str(update.message.chat_id)
        raw = (update.message.text or "")[6:].strip()
        if "|" not in raw or not raw.split("|", 1)[0].strip():
            await self._reply_cmd(update, "Usage: /learn <skill-name> | <workflow, URL, or 'how I just ...'>"); return
        if (r := self._active.get(cid)) and not r.done():
            await self._reply_cmd(update, self.TXT["busy"]); return
        name, material = (p.strip() for p in raw.split("|", 1))
        await self._run_turn(update, context, cid, Agent.learn_prompt(name, material))

    async def _on_bg(self, update, context):
        if not await self._access(update): return
        cid = str(update.message.chat_id)
        prompt = (update.message.text or "")[3:].strip()
        if not prompt:
            await self._reply_cmd(update, "Usage: /bg <prompt> — runs in a separate session, result arrives here."); return
        bkey = f"{cid}:bg"
        if (r := self._active.get(bkey)) and not r.done():
            await self._reply_cmd(update, "A background task is already running in this chat."); return
        tid = f"bg_{int(time.time())}"
        self._bg[tid] = cid
        await self._reply_cmd(update, f"🔄 Background task started ({tid}). Main chat stays free.")
        task = asyncio.create_task(self._run_bg(cid, bkey, tid, prompt))
        self._active[bkey] = task

    async def _run_bg(self, cid: str, bkey: str, tid: str, prompt: str):
        try:
            agent = self._agent(bkey)
            agent.reset()
            out = await asyncio.to_thread(agent.ask, prompt, {"chat_id": bkey})
            if parse_pending_marker(out):
                out = ("Background task needs your approval — rerun it in the main chat "
                       "so you can tap Allow/Deny.")
            await self._send_chunks(int(cid), f"✅ Background task complete ({tid}):\n{out}")
        except asyncio.CancelledError:
            pass
        except Exception as err:
            try: await self._send_chunks(int(cid), f"❌ Background task failed ({tid}): {err}")
            except Exception: pass
        finally:
            self._active.pop(bkey, None)
            self._bg.pop(tid, None)

    async def _on_stop(self, update, context):
        if not await self._access(update): return
        cid = str(update.message.chat_id)
        stopped = False
        for key in (cid, f"{cid}:bg"):
            if (r := self._active.get(key)) and not r.done():
                r.cancel(); stopped = True
        self._agent(cid).pending = {}
        await self._reply_cmd(update, self.TXT["stopped"] if stopped else self.TXT["idle"])

    async def _on_callback(self, update: Update, context):
        q = update.callback_query
        if not q or not q.message:
            return
        if not self._allowed(q.from_user.id, q.from_user.username):
            await q.answer("Unauthorized"); return
        await q.answer()
        cid = str(q.message.chat_id)
        agent = self._agent(cid)
        data = q.data or ""
        try:
            if data.startswith("ap:"):
                out = await asyncio.to_thread(agent.approve, data[3:])
            elif data.startswith("dn:"):
                out = await asyncio.to_thread(agent.deny, data[3:])
            elif data.startswith("cl:"):
                _, pid, idx = data.split(":", 2)
                entry = agent.pending.get(pid)
                opts = (entry["op"].get("options") or []) if entry else []
                try: answer = opts[int(idx)]
                except (ValueError, IndexError): answer = ""
                out = await asyncio.to_thread(agent.answer_clarify, pid, answer)
            else:
                return
        except Exception as err:
            out = f"Error: {err}"
        try:
            await self._deliver(q.message.chat_id, out, agent, edit_msg=q.message)
        except Exception:
            for chunk in _chunks(out):
                await q.message.reply_text(chunk)

    async def _on_voice(self, update, context):
        if not update.message or not update.message.voice or not await self._access(update): return
        cid = str(update.message.chat_id)
        if (r := self._active.get(cid)) and not r.done():
            await update.message.reply_text(self.TXT["busy"]); return
        if self._voice_transcribe is None:
            await update.message.reply_text(self.TXT["voice_unsupported"]); return
        try:
            tg_file = await update.message.voice.get_file()
        except Exception as err:
            await update.message.reply_text(f"Could not download voice memo: {err}"); return
        tmp = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
        tmp.close()
        try:
            await tg_file.download_to_drive(tmp.name)
            text = await asyncio.to_thread(self._voice_transcribe, tmp.name)
        except Exception as err:
            await update.message.reply_text(f"Transcription failed: {err}"); return
        finally:
            with suppress(OSError): os.unlink(tmp.name)
        if not (text or "").strip():
            await update.message.reply_text("(empty transcription)"); return
        await self._run_turn(update, context, cid, f"[Voice memo transcript] {text.strip()}")

    async def _send_chunks(self, chat_id: int, text: str):
        if not self._app: return
        for chunk in _chunks(text): await self._app.bot.send_message(chat_id=chat_id, text=chunk)

    async def _ask(self, cid, prompt, is_cron=False):
        agent = self._agent(cid)
        if not is_cron and cid in self._model_once:
            prev, agent.llm.model = agent.llm.model, self._model_once.pop(cid)
            try:
                task = asyncio.create_task(asyncio.to_thread(agent.ask, prompt, {"chat_id": cid, "is_cron": is_cron}))
                self._active[cid] = task
                return await task
            finally:
                agent.llm.model = prev; self._active.pop(cid, None)
        task = asyncio.create_task(asyncio.to_thread(agent.ask, prompt, {"chat_id": cid, "is_cron": is_cron})); self._active[cid] = task
        try: return await task
        finally: self._active.pop(cid, None)

    async def _run_turn(self, update, context, cid, prompt):
        async def typing():
            while True:
                try: await context.bot.send_chat_action(chat_id=update.message.chat_id, action="typing")
                except Exception: pass
                await asyncio.sleep(4)
        t = asyncio.create_task(typing())
        try: result = await self._ask(cid, prompt)
        except asyncio.CancelledError: await update.message.reply_text(self.TXT["stopped"]); return
        except Exception as err: await update.message.reply_text(f"Error: {err}"); return
        finally:
            t.cancel()
            with suppress(asyncio.CancelledError): await t
        if pid := parse_pending_marker(result):
            trailing = result.split("⟫", 1)[1].strip() if "⟫" in result else ""
            text, markup = self._card(self._agent(cid), pid, trailing)
            await update.message.reply_text(text, reply_markup=markup)
            return
        for chunk in _chunks(result): await update.message.reply_text(chunk)

    async def run_forever(self):
        token = self.settings.token.strip()
        if not token: raise RuntimeError("Missing Telegram token")
        self._app = Application.builder().token(token).build()
        for c, kw in (("start", {"key": "start", "denied": self.TXT["unauth_start"]}), ("new", {"key": "new", "reset": True}), ("help", {"key": "help"})):
            self._app.add_handler(CommandHandler(c, partial(self._on_cmd, **kw)))
        self._app.add_handler(CommandHandler("retry", partial(self._on_simple, fn=lambda a: a.retry())))
        self._app.add_handler(CommandHandler("undo", partial(self._on_simple, fn=lambda a: a.undo())))
        self._app.add_handler(CommandHandler("compress", partial(self._on_simple, fn=lambda a: a.compress())))
        self._app.add_handler(CommandHandler("usage", partial(self._on_simple, fn=lambda a: a.usage())))
        self._app.add_handler(CommandHandler("model", self._on_model))
        self._app.add_handler(CommandHandler("sessions", self._on_sessions))
        self._app.add_handler(CommandHandler("memory", self._on_memory))
        self._app.add_handler(CommandHandler("skills", self._on_skills))
        self._app.add_handler(CommandHandler("learn", self._on_learn))
        self._app.add_handler(CommandHandler("bg", self._on_bg))
        self._app.add_handler(CommandHandler("stop", self._on_stop))
        self._app.add_handler(CallbackQueryHandler(self._on_callback))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message))
        self._app.add_handler(MessageHandler(filters.VOICE, self._on_voice))
        await self._app.initialize(); await self._app.start(); await self._app.bot.set_my_commands(self.BOT_COMMANDS)
        await self._app.updater.start_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=True)
        self._cron_task = asyncio.create_task(self._cron_loop())
        try:
            while True: await asyncio.sleep(1)
        finally: await self.shutdown()

    async def shutdown(self):
        for t in list(self._active.values()): t.cancel()
        self._active.clear(); task, self._cron_task = self._cron_task, None
        if task and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError): await task
        if self._app: await self._app.updater.stop(); await self._app.stop(); await self._app.shutdown(); self._app = None

    async def _on_message(self, update, context):
        if not update.message or not update.message.text or not await self._access(update): return
        cid, text = str(update.message.chat_id), update.message.text.strip()
        if not text: return
        agent = self._agent(cid)
        for pid, entry in list(agent.pending.items()):
            if entry["op"].get("kind") == "clarify":
                if (r := self._active.get(cid)) and not r.done():
                    await update.message.reply_text(self.TXT["busy"]); return
                await self._run_turn_clarify(update, context, cid, agent, pid, text)
                return
        if agent.pending:
            await update.message.reply_text(self.TXT["pending_first"]); return
        if (r := self._active.get(cid)) and not r.done(): await update.message.reply_text(self.TXT["busy"]); return
        await self._run_turn(update, context, cid, text)

    async def _run_turn_clarify(self, update, context, cid, agent, pid, answer):
        async def typing():
            while True:
                try: await context.bot.send_chat_action(chat_id=update.message.chat_id, action="typing")
                except Exception: pass
                await asyncio.sleep(4)
        t = asyncio.create_task(typing())
        try: result = await asyncio.to_thread(agent.answer_clarify, pid, answer)
        except Exception as err: await update.message.reply_text(f"Error: {err}"); return
        finally:
            t.cancel()
            with suppress(asyncio.CancelledError): await t
        if npid := parse_pending_marker(result):
            trailing = result.split("⟫", 1)[1].strip() if "⟫" in result else ""
            text, markup = self._card(agent, npid, trailing)
            await update.message.reply_text(text, reply_markup=markup)
            return
        for chunk in _chunks(result): await update.message.reply_text(chunk)

    async def _cron_loop(self):
        while True:
            try:
                await asyncio.sleep(20)
                if not self._app: continue
                for job in self._cron.due():
                    cid, job_id = str(job.get("chat_id", "")), str(job.get("id", ""))
                    if not cid or not job_id: continue
                    if (r := self._active.get(cid)) and not r.done(): continue
                    prompt = str(job.get("prompt", "")).strip()
                    if not prompt: self._cron.remove(chat_id=None, job_id=job_id); continue
                    try: tg_chat_id = int(cid)
                    except Exception: self._cron.remove(chat_id=None, job_id=job_id); continue
                    try:
                        await self._send_chunks(tg_chat_id, await self._ask(cid, prompt, is_cron=True))
                    except Exception as err:
                        try: await self._send_chunks(tg_chat_id, f"error: {err}")
                        except Exception: pass
                    self._cron.mark_ran(job_id=job_id)
            except asyncio.CancelledError:
                return
            except Exception:
                await asyncio.sleep(1)


def _chunks(text, max_len=3900):
    text = (text or "").strip() or "(empty response)"
    if len(text) <= max_len: return [text]
    out = []
    while text:
        if len(text) <= max_len: out.append(text); break
        piece = text[:max_len]; pivot = max(piece.rfind("\n"), piece.rfind(" "))
        out.append(text[: pivot if pivot >= 0 else max_len]); text = text[pivot if pivot >= 0 else max_len :].lstrip()
    return out
