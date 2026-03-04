import os
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from agent import Agent
from llm_client import LLMClient
from memory_store import MemoryStore
from session_store import SessionStore
from tools import FileTools

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
ALLOWED = {x.strip() for x in os.getenv("TELEGRAM_ALLOWED_USERS", "").split(",") if x.strip()}
WORKSPACE_ROOT = os.getenv("WORKSPACE_ROOT", os.getcwd())
DB_PATH = os.getenv("RUNTIME_DB", "runtime.db")

sessions = SessionStore(DB_PATH)
memory = MemoryStore(DB_PATH)
tools = FileTools(WORKSPACE_ROOT)
llm = LLMClient()
agent = Agent(llm, sessions, memory, tools)


def is_allowed(user_id: int) -> bool:
    if not ALLOWED:
        return True
    return str(user_id) in ALLOWED


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        await update.message.reply_text(f"허용되지 않은 사용자입니다. user_id={uid}")
        return
    await update.message.reply_text("OpenGemini runtime bot ready. 메시지를 보내면 처리합니다.")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    model = llm.get_model()
    await update.message.reply_text(
        "명령어\n"
        "/start - 시작\n"
        "/help - 도움말\n"
        "/status - 상태\n"
        "/model [name] - 모델 조회/변경\n"
        "/models - 추천 모델 목록\n"
        "/approve <id> - 파일수정 승인\n\n"
        f"현재 모델: {model}"
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    await update.message.reply_text(
        f"status\nmodel={llm.get_model()}\nworkspace={WORKSPACE_ROOT}\ndb={DB_PATH}"
    )


async def model_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return

    if not context.args:
        await update.message.reply_text(f"현재 모델: {llm.get_model()}\n사용법: /model auto-gemini-3")
        return

    new_model = " ".join(context.args).strip()
    # 경량 검증: 실제 CLI로 1회 실행 테스트
    import subprocess
    proc = subprocess.run(
        [llm.gemini_bin, "-m", new_model, "-p", "ok"],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "model check failed").strip()[:400]
        await update.message.reply_text(f"❌ 모델 검증 실패: {new_model}\n{err}")
        return

    llm.set_model(new_model)
    await update.message.reply_text(f"✅ 모델 변경: {new_model}")


async def models_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return

    await update.message.reply_text(
        "현재 gemini-cli에서 사용 가능한(검증된) 모델:\n"
        "- auto-gemini-3\n"
        "- gemini-3.1-pro-preview\n"
        "- gemini-3-flash-preview\n"
        "- auto-gemini-2.5\n"
        "- gemini-2.5-pro\n"
        "- gemini-2.5-flash\n\n"
        "변경 예시: /model auto-gemini-3"
    )


async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    if not context.args:
        await update.message.reply_text("usage: /approve <id>")
        return
    try:
        req_id = int(context.args[0])
    except Exception:
        await update.message.reply_text("usage: /approve <id>")
        return

    user_key = f"tg:{uid}"
    out = agent.approve_and_run(user_key, req_id)
    await update.message.reply_text(out)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = (update.message.text or "").strip()
    print(f"[rx] uid={uid} text={text[:80]}", flush=True)

    if not is_allowed(uid):
        await update.message.reply_text(f"허용되지 않은 사용자입니다. user_id={uid}")
        return

    if not text:
        return

    user_key = f"tg:{uid}"
    out = agent.handle(user_key, text)
    await update.message.reply_text(out[:4000])


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("처리 중 오류가 발생했습니다. 다시 시도해 주세요.")
    except Exception:
        pass


async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "시작"),
        BotCommand("help", "도움말"),
        BotCommand("status", "실행 상태"),
        BotCommand("model", "모델 조회/변경"),
        BotCommand("models", "모델 목록"),
        BotCommand("approve", "파일수정 승인"),
    ])


def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is required")

    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_error_handler(on_error)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("model", model_cmd))
    app.add_handler(CommandHandler("models", models_cmd))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()


if __name__ == "__main__":
    main()
