#!/usr/bin/env python3
import asyncio
import os
import shlex
import sys
import fcntl
import re
import pexpect
from typing import Optional, List

from dotenv import load_dotenv
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0") or 0)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_BIN = os.getenv("GEMINI_BIN", "/usr/local/share/npm-global/bin/gemini").strip()
GEMINI_MODEL_DEFAULT = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
GEMINI_WORKDIR = os.getenv("GEMINI_WORKDIR", os.getcwd()).strip()
GEMINI_APPROVAL_MODE = os.getenv("GEMINI_APPROVAL_MODE", "yolo").strip()  # default|auto_edit|yolo|plan
GEMINI_SANDBOX = os.getenv("GEMINI_SANDBOX", "true").strip().lower() in ("1", "true", "yes", "on")

AVAILABLE_MODELS = {
    "auto-gemini-3": "Gemini 3 (자동 최신)",
    "gemini-3.1-pro-preview": "Gemini 3.1 Pro",
    "gemini-3-flash-preview": "Gemini 3 Flash",
    "auto-gemini-2.5": "Gemini 2.5 (자동)",
    "gemini-2.5-pro": "Gemini 2.5 Pro",
    "gemini-2.5-flash": "Gemini 2.5 Flash",
}

TELEGRAM_MAX = 4096
MSG_CHUNK = 3800
LOCK_FILE = "/tmp/tg_gemini_bot.lock"
_lock_fp = None


class PersistentGemini:
    def __init__(self, binary: str, model: Optional[str] = None):
        self.binary = binary
        self.model = model
        self.child: Optional[pexpect.spawn] = None
        self.lock = asyncio.Lock()

    def _clean_ansi(self, text: str) -> str:
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', text)

    async def start(self):
        async with self.lock:
            if self.child and self.child.isalive():
                self.child.terminate(force=True)

            env = os.environ.copy()
            env["TERM"] = "dumb"
            env["COLUMNS"] = "100"
            env["LINES"] = "50"
            if GEMINI_API_KEY:
                env["GEMINI_API_KEY"] = GEMINI_API_KEY

            cmd = f"{self.binary} --approval-mode default"
            if self.model:
                cmd += f" -m {self.model}"
            
            # Interactive mode by default
            self.child = pexpect.spawn(cmd, env=env, encoding='utf-8', timeout=60)
            # Wait for initial prompt or some marker
            try:
                # Prompt is usually " > " or "Enter your query: "
                # We'll wait for the block character or some indicator
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self.child.expect([">", "Ready"], timeout=20)
                )
            except:
                pass

    async def query(self, text: str) -> str:
        async with self.lock:
            if not self.child or not self.child.isalive():
                await self.start()
            
            self.child.sendline(text)
            
            # Use run_in_executor for pexpect synchronous calls
            def wait_for_response():
                try:
                    # Wait for next prompt
                    self.child.expect([">"], timeout=60)
                    return self.child.before
                except pexpect.TIMEOUT:
                    return self.child.before + "\n[Timeout waiting for prompt]"
                except Exception as e:
                    return f"Error: {str(e)}"

            loop = asyncio.get_event_loop()
            raw_out = await loop.run_in_executor(None, wait_for_response)
            
            # Clean up output
            cleaned = self._clean_ansi(raw_out or "")
            # Remove the echoed command from the beginning if possible
            if cleaned.startswith(text):
                cleaned = cleaned[len(text):].strip()
            
            return cleaned.strip() or "(No response)"

    async def restart(self, model: Optional[str] = None):
        if model:
            self.model = model
        await self.start()

    def stop(self):
        if self.child and self.child.isalive():
            self.child.terminate(force=True)

persistent_gemini = PersistentGemini(GEMINI_BIN, GEMINI_MODEL_DEFAULT)
# 텔레그램 업데이트가 동시에 들어와 응답 순서가 꼬이지 않도록 직렬화
RUN_LOCK = asyncio.Lock()


def _acquire_singleton_lock() -> None:
    global _lock_fp
    _lock_fp = open(LOCK_FILE, "w")
    try:
        fcntl.flock(_lock_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_fp.write(str(os.getpid()))
        _lock_fp.flush()
    except BlockingIOError:
        raise RuntimeError("Another tg_gemini bot instance is already running")


def _authorized(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id == ALLOWED_USER_ID)


def _chunk_text(text: str, size: int = MSG_CHUNK) -> List[str]:
    if len(text) <= size:
        return [text]
    chunks: List[str] = []
    cur = ""
    for line in text.splitlines(True):
        if len(cur) + len(line) > size:
            chunks.append(cur)
            cur = line
        else:
            cur += line
    if cur:
        chunks.append(cur)
    return chunks


async def _run_gemini(prompt: str, model: Optional[str] = None, timeout_sec: int = 60) -> tuple[int, str, str]:
    env = os.environ.copy()
    if GEMINI_API_KEY:
        env["GEMINI_API_KEY"] = GEMINI_API_KEY

    cmd = [GEMINI_BIN]
    if model:
        cmd += ["-m", model]

    # 비대화형 + 확인창 차단(텔레그램 봇에서 멈춤 방지)
    cmd += [
        "--approval-mode", GEMINI_APPROVAL_MODE,
        "--output-format", "text",
    ]
    if GEMINI_SANDBOX:
        cmd += ["--sandbox"]

    # headless prompt
    cmd += ["-p", prompt]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=GEMINI_WORKDIR,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, "", f"Gemini timeout after {timeout_sec}s"

    out = out_b.decode("utf-8", errors="replace").strip()
    err = err_b.decode("utf-8", errors="replace").strip()
    return proc.returncode, out, err


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await update.message.reply_text(
        "✅ N100 Gemini Bot 준비 완료\n"
        "- 일반 메시지를 보내면 Gemini CLI로 처리합니다.\n"
        "- /help 로 명령어 확인"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    model = context.application.bot_data.get("model") or GEMINI_MODEL_DEFAULT or "(기본)"
    txt = (
        "🤖 *N100 Gemini Bot*\n\n"
        "*명령어*\n"
        "/start - 시작\n"
        "/help - 도움말\n"
        "/model [name] - 모델 조회/설정\n"
        "/status - 실행 상태\n"
        "/restart - 세션 재시작\n"
        "/new - 세션 초기화 (대화 기록 삭제)\n"
        "/input [내용] - CLI로 직접 텍스트 입력 전달\n"
        "/update - Gemini CLI 업데이트\n\n"
        f"현재 모델: `{model}`\n"
        f"Gemini 바이너리: `{GEMINI_BIN}`\n"
        f"approval_mode: `{GEMINI_APPROVAL_MODE}`\n"
        f"sandbox: `{GEMINI_SANDBOX}`\n"
        f"작업 디렉토리: `{GEMINI_WORKDIR}`"
    )
    await update.message.reply_text(txt, parse_mode=ParseMode.MARKDOWN)


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return

    model = context.application.bot_data.get("model") or GEMINI_MODEL_DEFAULT or "(기본)"
    try:
        proc = await asyncio.create_subprocess_exec(
            GEMINI_BIN,
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        ver = (out.decode().strip() or err.decode().strip() or "unknown")
    except Exception as e:
        ver = f"error: {e}"

    await update.message.reply_text(
        f"상태\n- model: {model}\n- gemini: {ver}\n- workdir: {GEMINI_WORKDIR}"
    )


async def model_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return

    if not context.args:
        cur = context.application.bot_data.get("model") or GEMINI_MODEL_DEFAULT or "(기본)"
        await update.message.reply_text(f"현재 모델: {cur}\n사용법: /model gemini-1.5-flash\n다양한 모델을 선택하려면 /models 를 입력하세요.")
        return

    model = " ".join(context.args).strip()

    await update.message.reply_text(f"모델 검증 중: {model}")
    rc, out, err = await _run_gemini("say ok", model=model, timeout_sec=20)
    if rc != 0:
        msg = (
            f"❌ 모델 설정 실패: {model}\n"
            f"오류: {(err or out or 'unknown')[:500]}\n"
            "권장: /model gemini-1.5-flash"
        )
        await update.message.reply_text(msg)
        return

    context.application.bot_data["model"] = model
    await persistent_gemini.restart(model=model)
    await update.message.reply_text(f"✅ 모델 설정 완료 및 세션 재시작: {model}")


async def models_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return

    keyboard = []
    # 2열로 배치
    it = iter(AVAILABLE_MODELS.items())
    for (m1_id, m1_name) in it:
        row = [InlineKeyboardButton(m1_name, callback_data=f"set_model:{m1_id}")]
        try:
            m2_id, m2_name = next(it)
            row.append(InlineKeyboardButton(m2_name, callback_data=f"set_model:{m2_id}"))
        except StopIteration:
            pass
        keyboard.append(row)

    reply_markup = InlineKeyboardMarkup(keyboard)
    cur = context.application.bot_data.get("model") or GEMINI_MODEL_DEFAULT or "(기본)"
    await update.message.reply_text(
        f"현재 모델: `{cur}`\n변경할 모델을 선택하세요:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )


async def model_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("set_model:"):
        return

    model = data.split(":", 1)[1]
    await query.edit_message_text(text=f"🔄 모델 변경 중: {model}...")

    rc, out, err = await _run_gemini("say verified", model=model, timeout_sec=20)
    if rc != 0:
        await query.edit_message_text(f"❌ '{model}' 검증 실패. 다시 시도해 주세요.\nError: {err or out}")
        return

    context.application.bot_data["model"] = model
    await persistent_gemini.restart(model=model)
    await query.edit_message_text(text=f"✅ 모델이 설정되었습니다: {model}")


async def restart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await update.message.reply_text("🔄 세션 초기화 중...")
    model = context.application.bot_data.get("model") or GEMINI_MODEL_DEFAULT
    await persistent_gemini.restart(model=model)
    await update.message.reply_text("✅ 세션이 재시작되었습니다.")


async def input_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("사용법: /input 1 (도구 승인 등의 입력을 직접 보낼 때 사용)")
        return
    
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    out = await persistent_gemini.query(text)
    for ch in _chunk_text(out):
        await update.message.reply_text(ch)


async def update_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return

    await update.message.reply_text("Gemini CLI 업데이트 중...")
    cmd = "npm install -g @google/gemini-cli --force"
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out_b, err_b = await proc.communicate()
    out = out_b.decode("utf-8", errors="replace")
    err = err_b.decode("utf-8", errors="replace")

    result = f"[Update Result]\nexit={proc.returncode}\n\n{out}"
    if err.strip():
        result += f"\n\nErrors:\n{err}"

    for ch in _chunk_text(result):
        await update.message.reply_text(ch)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id if user else 0
    text = (update.message.text or "").strip()

    print(f"[msg] From {user_id}: {text[:50]}")

    if not _authorized(update):
        print(f"[auth] Unauthorized access attempt from user_id: {user_id}")
        return
    if not text:
        return

    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)

    # 업데이트 동시 처리 시 응답 순서 꼬임 방지
    async with RUN_LOCK:
        model = context.application.bot_data.get("model") or GEMINI_MODEL_DEFAULT
        rc, out, err = await _run_gemini(text, model=model, timeout_sec=90)

        if rc != 0:
            msg = f"❌ Gemini 실행 실패 (exit={rc})\n{(err or out or '응답 없음')[:1500]}"
            for ch in _chunk_text(msg):
                await update.message.reply_text(ch)
            return

        out = (out or "").strip() or "(응답 없음)"
        for ch in _chunk_text(out):
            await update.message.reply_text(ch)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    print(f"[bot error] {err}")
    if err and "Conflict: terminated by other getUpdates request" in str(err):
        print("Another polling instance detected. Exiting this process.")
        os._exit(1)


async def post_init(app: Application) -> None:
    commands = [
        BotCommand("start", "봇 시작"),
        BotCommand("help", "도움말"),
        BotCommand("model", "모델 수동 설정"),
        BotCommand("models", "모델 선택 (목록)"),
        BotCommand("status", "실행 상태"),
        BotCommand("restart", "세션 재시작"),
        BotCommand("new", "새 대화 시작"),
        BotCommand("input", "직접 입력 전달"),
        BotCommand("update", "Gemini CLI 업데이트"),
    ]
    await app.bot.set_my_commands(commands)


def main() -> None:
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is missing")
    if ALLOWED_USER_ID == 0:
        raise RuntimeError("ALLOWED_USER_ID is missing")
    if not os.path.exists(GEMINI_BIN):
        raise RuntimeError(f"GEMINI_BIN not found: {GEMINI_BIN}")

    _acquire_singleton_lock()

    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    app.add_error_handler(on_error)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("model", model_cmd))
    app.add_handler(CommandHandler("models", models_cmd))
    app.add_handler(CallbackQueryHandler(model_callback))
    app.add_handler(CommandHandler("restart", restart_cmd))
    app.add_handler(CommandHandler("new", restart_cmd))
    app.add_handler(CommandHandler("input", input_cmd))
    app.add_handler(CommandHandler("update", update_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("N100 Gemini bot polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
