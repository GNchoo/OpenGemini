#!/usr/bin/env python3
import asyncio
import os
import shlex
import sys
import fcntl
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
    "gemini-3.1-pro-preview": "Gemini 3.1 Pro (최신)",
    "gemini-3-flash-preview": "Gemini 3 Flash (속도)",
    "gemini-1.5-pro": "Gemini 1.5 Pro",
    "gemini-1.5-flash": "Gemini 1.5 Flash",
}

TELEGRAM_MAX = 4096
MSG_CHUNK = 3800
LOCK_FILE = "/tmp/tg_gemini_bot.lock"
_lock_fp = None


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


async def _run_gemini(prompt: str, model: Optional[str] = None, timeout_sec: int = 45) -> tuple[int, str, str]:
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
        "/restart - 봇 프로세스 재기동 안내\n"
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
    await update.message.reply_text(f"✅ 모델 설정 완료: {model}")


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
    await query.edit_message_text(text=f"✅ 모델이 설정되었습니다: {model}")


async def restart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await update.message.reply_text("ℹ️ 이 봇은 요청마다 Gemini를 headless로 실행하므로 별도 세션 재시작이 필요 없습니다.")


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
    if not _authorized(update):
        return

    text = (update.message.text or "").strip()
    if not text:
        return

    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)

    model = context.application.bot_data.get("model") or GEMINI_MODEL_DEFAULT or None
    rc, out, err = await _run_gemini(text, model=model)

    if rc != 0:
        hint = ""
        em = (err or out or "")
        if "ModelNotFoundError" in em or "Requested entity was not found" in em:
            hint = "\n\n모델명이 잘못됐을 가능성이 큽니다. `/model gemini-2.5-pro`로 변경해 보세요."
        elif "timeout" in em.lower():
            hint = "\n\n요청이 오래 걸려 타임아웃됐습니다. 짧은 질문으로 다시 시도해 주세요."

        msg = (
            "❌ Gemini 실행 실패\n"
            f"exit={rc}\n"
            f"stderr:\n{em or '(none)'}{hint}"
        )
        for ch in _chunk_text(msg):
            await update.message.reply_text(ch)
        return

    if not out:
        out = "(응답 없음)"

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
        BotCommand("status", "상태 확인"),
        BotCommand("restart", "재시작 안내"),
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
    app.add_handler(CommandHandler("update", update_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("N100 Gemini bot polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
