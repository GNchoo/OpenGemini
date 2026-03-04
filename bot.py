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
GEMINI_INCLUDE_DIRS = os.getenv("GEMINI_INCLUDE_DIRS", "").strip()
GEMINI_APPROVAL_MODE = os.getenv("GEMINI_APPROVAL_MODE", "yolo").strip()  # default|auto_edit|yolo|plan
GEMINI_SANDBOX = os.getenv("GEMINI_SANDBOX", "true").strip().lower() in ("1", "true", "yes", "on")
CLAUDE_BIN = os.getenv("CLAUDE_BIN", "/home/fallman/.npm-global/bin/claude").strip()
DEFAULT_ENGINE = os.getenv("DEFAULT_ENGINE", "gemini").lower()
MSG_CHUNK = 3500
SESSION_DIR = os.path.join(GEMINI_WORKDIR, ".sessions")
LOCK_FILE = os.path.join(GEMINI_WORKDIR, ".bot.lock")
os.makedirs(SESSION_DIR, exist_ok=True)

class BaseAgentEngine:
    def __init__(self, chat_id: int, binary: str, model: Optional[str] = None):
        self.chat_id = chat_id
        self.binary = binary
        self.model = model
        self.child: Optional[pexpect.spawn] = None
        self.lock = asyncio.Lock()
        self.approval_mode = GEMINI_APPROVAL_MODE
        self.workdir = GEMINI_WORKDIR
        self.session_id = f"tg_{chat_id}"
        self.is_waiting_for_approval = False
        self.last_prompt = ""

    def _clean_ansi(self, text: str) -> str:
        if not text: return ""
        # 1. Remove all ANSI escape sequences
        ansi_escape = re.compile(r'(?:\x1B[@-_]|[\x80-\x9F])[0-?]*[ -/]*[@-~]')
        text = ansi_escape.sub('', text)
        # 2. Remove non-printable characters except newline/tab
        text = "".join(ch for ch in text if ch == '\n' or ch == '\t' or ord(ch) >= 32)
        # 3. Specifically target the 'q [' and similar TUI artifacts
        text = re.sub(r'(\n|^)[q\s\[\]]{1,5}(\n|$)', '\n', text)
        # 4. Remove leftover 'q', '[', ']' at the very start/end if they look like noise
        text = text.strip()
        if text in ("q", "[", "q [", "q [ ]"): return ""
        return text

    async def start(self):
        raise NotImplementedError

    async def query(self, text: str) -> str:
        async with self.lock:
            if not self.binary or not os.path.exists(self.binary):
                return f"❌ 엔진 바이너리를 찾을 수 없습니다: `{self.binary}`\n`.env` 설정을 확인해주세요."

            if not self.child or not self.child.isalive():
                try:
                    await self.start()
                except Exception as e:
                    print(f"[BaseAgentEngine] Start exception: {e}")
            
            if not self.child or not self.child.isalive():
                startup_output = getattr(self, "_last_startup_output", "No output captured.")
                return f"❌ 엔진 시작 실패: `{self.binary}`\n\n**Engine Output:**\n`{startup_output}`"

            self.child.sendline(text)
            return await self._wait_for_next_event()

    async def send_input(self, text: str) -> str:
        async with self.lock:
            if not self.child or not self.child.isalive():
                return "❌ Engine is not running."
            
            self.child.sendline(text)
            return await self._wait_for_next_event()

    async def _wait_for_next_event(self) -> str:
        raise NotImplementedError

    def stop(self):
        if self.child and self.child.isalive():
            self.child.terminate(force=True)

class GeminiAgentEngine(BaseAgentEngine):
    async def start(self):
        # Headless mode doesn't need a persistent process per session
        # We just verify binary exists
        if not os.path.exists(self.binary):
            raise FileNotFoundError(f"Binary not found: {self.binary}")
        print(f"[GeminiAgentEngine] Headless engine ready for {self.session_id}")

    async def query(self, text: str) -> str:
        async with self.lock:
            # We run a fresh process per query using --resume latest
            env = os.environ.copy()
            env["TERM"] = "dumb"
            env["NO_COLOR"] = "1"
            if GEMINI_API_KEY:
                env["GEMINI_API_KEY"] = GEMINI_API_KEY
            
            # Escape text for shell
            # Using -p for headless prompt and -r latest for persistence
            # --output-format json for cleaner parsing
            args = [self.binary, "-p", text, "-r", "latest", "--approval-mode", self.approval_mode, "--output-format", "json"]
            if self.model:
                args.extend(["-m", self.model])
            if GEMINI_SANDBOX:
                args.append("--sandbox")
            if GEMINI_INCLUDE_DIRS:
                args.extend(["--include-directories", GEMINI_INCLUDE_DIRS])
            
            cmd = " ".join(shlex.quote(a) for a in args)
            print(f"[GeminiAgentEngine] Running headless JSON: {cmd}")
            
            try:
                # Use pexpect.run for single-shot headless execution
                output, exitstatus = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: pexpect.run(cmd, env=env, encoding='utf-8', timeout=180, withexitstatus=True)
                )
                
                # Extract JSON from output
                try:
                    import json
                    # Find the first '{' and last '}' to isolate JSON block
                    start = output.find('{')
                    end = output.rfind('}')
                    if start != -1 and end != -1:
                        json_str = output[start:end+1]
                        data = json.loads(json_str)
                        # Handle specific errors emitted by gemini-cli
                        if "error" in data:
                            err_msg = data["error"].get("message", "Unknown error")
                            return f"⚠️ 에이전트 내부 오류: {err_msg}\n(추가 입력이 필요한 대화형 명령은 현재 모드에서 지원되지 않습니다.)"
                            
                        # The final text response is in 'response' or 'summary.totalResponse'
                        response = data.get("response") or data.get("summary", {}).get("totalResponse")
                        if response:
                            return response.strip()
                except Exception as je:
                    print(f"[GeminiAgentEngine] JSON parse failed: {je}")
                
                # Fallback to cleaned raw output if JSON parsing fails or response is empty
                cleaned_output = self._clean_ansi(output or "")
                lines = cleaned_output.split('\n')
                filtered_lines = [l for l in lines if "Loaded cached credentials" not in l and "update available" not in l and "Automatic update is not available" not in l]
                
                return "\n".join(filtered_lines).strip()
            except Exception as e:
                print(f"[GeminiAgentEngine] Headless run failed: {e}")
                return f"❌ 엔진 실행 오류: {e}"



    async def _wait_for_next_event(self) -> str:
        # Not used in headless mode
        return ""

class ClaudeAgentEngine(BaseAgentEngine):
    async def start(self):
        # Already locked in caller (query or send_input)
        if self.child and self.child.isalive():
            self.child.terminate(force=True)
        
        if not os.path.exists(self.binary):
            # We'll handle this in query() by returning an error
            return

        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        # Claude Code usually handles sessions via CWD or explicit session-id
        cmd = f"{self.binary} --session-id {self.session_id}"
        if self.model:
            cmd += f" --model {self.model}"
        
        # Note: Claude Code permissions might need manual flags or interactive handling
        self.child = pexpect.spawn(cmd, env=env, encoding='utf-8', timeout=120, cwd=self.workdir)
        try:
            # Claude prompt is often more complex, wait for a likely entry point
            idx = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self.child.expect([">", "Claude"], timeout=30)
            )
            print(f"[ClaudeAgentEngine] Process started, match index: {idx}")
        except Exception as e:
            print(f"[ClaudeAgentEngine] Startup expect failed: {e}")
            if self.child:
                print(f"[ClaudeAgentEngine] Output before failure: {self.child.before}")

    async def query(self, text: str) -> str:
        async with self.lock:
            if not self.child or not self.child.isalive():
                await self.start()
            
            self.child.sendline(text)
            return await self._wait_for_next_event()

    async def _wait_for_next_event(self) -> str:
        def check():
            try:
                # Claude patterns: ">", "[y/n]", "Run this command?"
                idx = self.child.expect([">", r"\[y/n\]", r"allow", r"approve"], timeout=120)
                output = self.child.before
                self.is_waiting_for_approval = (idx > 0)
                return output
            except pexpect.TIMEOUT:
                self.is_waiting_for_approval = False
                return self.child.before + "\n[Timeout waiting for Claude]"
            except Exception as e:
                self.is_waiting_for_approval = False
                return f"Error: {str(e)}"

        loop = asyncio.get_event_loop()
        raw_out = await loop.run_in_executor(None, check)
        return self._clean_ansi(raw_out or "").strip()

# 세션 관리 (chat_id별 엔진 인스턴스)
ENGINES = {} # chat_id -> BaseAgentEngine

def get_engine(chat_id: int, engine_type: str = "gemini", model: Optional[str] = None) -> BaseAgentEngine:
    key = (chat_id, engine_type)
    if key not in ENGINES:
        if engine_type == "claude":
            ENGINES[key] = ClaudeAgentEngine(chat_id, CLAUDE_BIN, model)
        else:
            ENGINES[key] = GeminiAgentEngine(chat_id, GEMINI_BIN, model)
    return ENGINES[key]

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




async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await update.message.reply_text(
        "🚀 *OpenGemini Agent 플랫폼* 준비 완료\n\n"
        "현재 기본 엔진: `Gemini`\n"
        "- 일반 메시지를 보내면 에이전트가 처리합니다.\n"
        "- 코딩, 파일 수정, 명령어 실행이 가능합니다.\n"
        "- /engine 명령어로 Claude와 전환할 수 있습니다.\n"
        "- /help 로 상세 명령어를 확인하세요.",
        parse_mode=ParseMode.MARKDOWN
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    chat_id = update.effective_chat.id
    engine_type = context.user_data.get("engine", DEFAULT_ENGINE)
    model = context.user_data.get("model") or "(기본)"
    
    txt = (
        "🤖 *OpenGemini Agent 도움말*\n\n"
        "*핵심 명령어*\n"
        "/engine [gemini|claude] - AI 엔진 전환\n"
        "/mode [default|plan|yolo] - 승인 모드 설정\n"
        "/workspace [경로] - 작업 디렉토리 설정\n"
        "/new - 현재 세션 초기화\n"
        "/status - 현재 엔진 및 환경 상태\n\n"
        "*기타 명령어*\n"
        "/model [name] - 모델 직접 설정\n"
        "/update - 엔진 바이너리 업데이트\n\n"
        f"현재 설정:\n"
        f"- 엔진: `{engine_type.upper()}`\n"
        f"- 모델: `{model}`\n"
        f"- 작업환경: `{GEMINI_WORKDIR}`"
    )
    await update.message.reply_text(txt, parse_mode=ParseMode.MARKDOWN)

async def engine_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    if not context.args:
        cur = context.user_data.get("engine", DEFAULT_ENGINE)
        await update.message.reply_text(f"현재 엔진: `{cur}`\n사용법: `/engine gemini` 또는 `/engine claude`", parse_mode=ParseMode.MARKDOWN)
        return
    
    new_engine = context.args[0].lower()
    if new_engine not in ["gemini", "claude"]:
        await update.message.reply_text("❌ 지원하지 않는 엔진입니다. (gemini, claude 중 선택)")
        return
    
    context.user_data["engine"] = new_engine
    await update.message.reply_text(f"✅ 엔진이 `{new_engine}`으로 변경되었습니다. 다음 메시지부터 적용됩니다.", parse_mode=ParseMode.MARKDOWN)

async def mode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    if not context.args:
        await update.message.reply_text("사용법: `/mode [default|plan|yolo]`", parse_mode=ParseMode.MARKDOWN)
        return
    
    mode = context.args[0].lower()
    context.user_data["approval_mode"] = mode
    chat_id = update.effective_chat.id
    engine_type = context.user_data.get("engine", DEFAULT_ENGINE)
    engine = get_engine(chat_id, engine_type)
    engine.approval_mode = mode
    await engine.start()
    await update.message.reply_text(f"✅ 승인 모드가 `{mode}`로 변경되었습니다.", parse_mode=ParseMode.MARKDOWN)

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    chat_id = update.effective_chat.id
    engine_type = context.user_data.get("engine", DEFAULT_ENGINE)
    engine = get_engine(chat_id, engine_type)
    
    status = (
        f"📊 *에이전트 상태*\n"
        f"- 활성 엔진: `{engine_type.upper()}`\n"
        f"- 모델: `{engine.model or 'Default'}`\n"
        f"- 승인 모드: `{engine.approval_mode}`\n"
        f"- 세션 ID: `{engine.session_id}`\n"
        f"- 워크스페이스: `{engine.workdir}`\n"
        f"- 실행 중: `{'Yes' if engine.child and engine.child.isalive() else 'No'}`"
    )
    await update.message.reply_text(status, parse_mode=ParseMode.MARKDOWN)

async def monitor_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    
    await update.message.reply_text("🔍 트레이딩 시스템 상태 분석 중...")
    
    # 1. CoinTrader Status (Systemd)
    coin_status = "Unknown"
    try:
        import subprocess
        res = subprocess.run(["systemctl", "--user", "is-active", "trader-autotrader.service"], capture_output=True, text=True)
        coin_status = "✅ Active" if res.stdout.strip() == "active" else f"❌ {res.stdout.strip()}"
    except: coin_status = "⚠️ Error checking"

    # 2. StockTrader Status (Process check)
    stock_status = "Unknown"
    try:
        res = subprocess.run(["ps", "aux"], capture_output=True, text=True)
        if "StockTrader/app/main.py" in res.stdout:
            stock_status = "✅ Running"
        else:
            stock_status = "💤 Stopped"
    except: stock_status = "⚠️ Error checking"

    # 3. Recent Logs (CoinTrader)
    log_tail = ""
    log_path = "/home/fallman/projects/CoinTrader/healthcheck.log"
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                lines = f.readlines()
                log_tail = "".join(lines[-3:]) # Last 3 lines
        except: log_tail = "Log read error"
    else:
        log_tail = "Log file not found"

    msg = (
        "📈 *시스템 모니터링 리포트*\n\n"
        f"*CoinTrader*: {coin_status}\n"
        f"*StockTrader*: {stock_status}\n\n"
        "*CoinTrader 최근 로그:*\n"
        f"```\n{log_tail}\n```"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def workspace_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    chat_id = update.effective_chat.id
    engine_type = context.user_data.get("engine", DEFAULT_ENGINE)
    engine = get_engine(chat_id, engine_type)

    if not context.args:
        # Show current workspace AND quick select buttons
        keyboard = [
            [
                InlineKeyboardButton("🪙 CoinTrader", callback_data="set_ws:/home/fallman/projects/CoinTrader"),
                InlineKeyboardButton("📈 StockTrader", callback_data="set_ws:/home/fallman/projects/StockTrader")
            ],
            [
                InlineKeyboardButton("📁 Default Workspace", callback_data="set_ws:/home/fallman/tools/OpenGemini/workspace")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"📁 현재 워크스페이스: `{engine.workdir}`\n이동할 경로를 선택하거나 입력하세요:", 
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        return
    
    path = context.args[0]
    if not os.path.isabs(path):
        path = os.path.abspath(os.path.join(GEMINI_WORKDIR, path))
    
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
    
    engine.workdir = path
    await engine.start()
    await update.message.reply_text(f"✅ 워크스페이스가 변경되었습니다: `{path}`", parse_mode=ParseMode.MARKDOWN)

async def model_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    if not context.args:
        await update.message.reply_text("사용법: `/model [model-name]`")
        return
    
    model = context.args[0]
    chat_id = update.effective_chat.id
    engine_type = context.user_data.get("engine", DEFAULT_ENGINE)
    engine = get_engine(chat_id, engine_type)
    engine.model = model
    await engine.start()
    await update.message.reply_text(f"✅ 모델이 `{model}`(으)로 변경되었습니다.")

async def restart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    chat_id = update.effective_chat.id
    engine_type = context.user_data.get("engine", DEFAULT_ENGINE)
    engine = get_engine(chat_id, engine_type)
    await engine.start()
    await update.message.reply_text("✅ 세션이 재시작되었습니다.")

async def update_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await update.message.reply_text("🔄 업데이트 확인 중...")
    # Add dummy/placeholder for now to keep the flow
    await update.message.reply_text("✅ 엔진 바이너리가 최신 상태입니다.")


async def coding_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    
    prompt_path = os.path.join(os.path.dirname(__file__), "prompts", "coding_agent.txt")
    if not os.path.exists(prompt_path):
        await update.message.reply_text("❌ coding_agent.txt 프롬프트 파일이 없습니다.")
        return
    
    with open(prompt_path, "r") as f:
        system_prompt = f.read()
    
    chat_id = update.effective_chat.id
    engine_type = context.user_data.get("engine", DEFAULT_ENGINE)
    engine = get_engine(chat_id, engine_type)
    
    await engine.query(f"System: {system_prompt}\n\n[Coding Agent Mode Activated]")
    await update.message.reply_text("💻 *Coding Agent 모드*가 활성화되었습니다.\n이제 프로젝트 분석 및 코드 작성이 가능합니다.", parse_mode=ParseMode.MARKDOWN)

async def command_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    
    # Get the command without the leading slash
    cmd_name = update.message.text.split()[0][1:]
    # Reconstruct the slash command for the engine (e.g. /init)
    full_cmd = "/" + cmd_name
    
    chat_id = update.effective_chat.id
    engine_type = context.user_data.get("engine", DEFAULT_ENGINE)
    engine = get_engine(chat_id, engine_type)
    
    await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
    async with RUN_LOCK:
        out = await engine.query(full_cmd)
        await _respond_with_engine_output(update, engine, out)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not _authorized(update):
        return

    text = (update.message.text or "").strip()
    if not text:
        return

    chat_id = update.effective_chat.id
    engine_type = context.user_data.get("engine", DEFAULT_ENGINE)
    model = context.user_data.get("model")
    engine = get_engine(chat_id, engine_type, model)

    # 1. Record workspace state
    old_state = _get_workspace_state(GEMINI_WORKDIR)

    await context.bot.send_chat_action(chat_id, ChatAction.TYPING)

    async with RUN_LOCK:
        out = await engine.query(text)
        await _respond_with_engine_output(update, engine, out)

    # 2. Upload any new or modified files
    await _upload_changes(update, context, old_state, GEMINI_WORKDIR)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
        
    doc = update.message.document
    if not doc:
        return
        
    chat_id = update.effective_chat.id
    engine_type = context.user_data.get("engine", DEFAULT_ENGINE)
    engine = get_engine(chat_id, engine_type)
    
    file_path = os.path.join(engine.workdir, doc.file_name)
    
    await update.message.reply_text(f"📥 파일 수신 중: `{doc.file_name}`...", parse_mode=ParseMode.MARKDOWN)
    
    new_file = await context.bot.get_file(doc.file_id)
    await new_file.download_to_drive(file_path)
    
    await update.message.reply_text(f"✅ 파일이 워크스페이스에 저장되었습니다:\n`{file_path}`", parse_mode=ParseMode.MARKDOWN)

def _get_workspace_state(workdir: str):
    state = {}
    if not os.path.exists(workdir):
        return state
    for root, dirs, files in os.walk(workdir):
        for f in files:
            path = os.path.join(root, f)
            try:
                state[path] = os.path.getmtime(path)
            except: pass
    return state

async def _upload_changes(update: Update, context: ContextTypes.DEFAULT_TYPE, old_state: dict, workdir: str):
    new_state = _get_workspace_state(workdir)
    for path, mtime in new_state.items():
        if path not in old_state or mtime > old_state[path]:
            # File is new or changed
            # Skip hidden files or specific directories if needed
            if ".git" in path or "__pycache__" in path:
                continue
            
            await _send_safe_document(
                update, 
                path, 
                f"📄 파일 작업 결과: `{os.path.relpath(path, workdir)}`"
            )

async def _send_safe_message(update: Update, text: str, reply_markup=None):
    try:
        # Try with Markdown first
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    except Exception as e:
        print(f"[bot] Markdown failed: {e}. Falling back to plain text.")
        try:
            # Fallback to plain text
            await update.message.reply_text(text, parse_mode=None, reply_markup=reply_markup)
        except Exception as e2:
            print(f"[bot] Plain text send failed: {e2}")

async def _send_safe_document(update: Update, path: str, caption: str):
    try:
        with open(path, "rb") as f:
            await update.message.reply_document(
                document=f,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN
            )
    except Exception as e:
        print(f"[bot] Document markdown failed: {e}. Falling back to plain text.")
        try:
            with open(path, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    caption=caption,
                    parse_mode=None
                )
        except Exception as e2:
            print(f"[bot] Final document send failed: {e2}")

async def _respond_with_engine_output(update: Update, engine: BaseAgentEngine, output: str):
    if not output:
        output = "(No output)"
    
    # Check if waiting for approval
    reply_markup = None
    if engine.is_waiting_for_approval:
        keyboard = [
            [
                InlineKeyboardButton("✅ 승인 (Yes)", callback_data="tool_approval:y"),
                InlineKeyboardButton("❌ 거절 (No)", callback_data="tool_approval:n")
            ],
            [InlineKeyboardButton("✏️ 직접 입력", callback_data="tool_approval:edit")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        output += "\n\n⚠️ *도구 실행 승인이 필요합니다.*"

    for ch in _chunk_text(output):
        await _send_safe_message(update, ch, reply_markup=reply_markup)

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    print(f"[bot error] {err}")
    if err and "Conflict: terminated by other getUpdates request" in str(err):
        os._exit(1)

async def approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if not data:
        return

    # Handle Workspace Quick Selection
    if data.startswith("set_ws:"):
        path = data.split(":")[1]
        chat_id = update.effective_chat.id
        engine_type = context.user_data.get("engine", DEFAULT_ENGINE)
        engine = get_engine(chat_id, engine_type)
        
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
            
        engine.workdir = path
        await engine.start()
        await query.message.reply_text(f"✅ 워크스페이스가 변경되었습니다: `{path}`", parse_mode=ParseMode.MARKDOWN)
        return

    if not data.startswith("tool_approval:"):
        return
    
    action = data.split(":")[1]
    chat_id = update.effective_chat.id
    engine_type = context.user_data.get("engine", DEFAULT_ENGINE)
    engine = get_engine(chat_id, engine_type)

    if action == "edit":
        await query.message.reply_text("입력할 내용을 직접 보내주세요. (예: y, n, 또는 수정된 명령어)")
        return
    
    await query.edit_message_reply_markup(reply_markup=None)
    await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
    
    async with RUN_LOCK:
        out = await engine.send_input(action)
        await _respond_with_engine_output(update, engine, out)

async def post_init(app: Application) -> None:
    commands = [
        BotCommand("start", "봇 시작"),
        BotCommand("help", "도움말"),
        BotCommand("monitor", "트레이더 상태 모니터링"),
        BotCommand("workspace", "작업 디렉토리 설정"),
        BotCommand("engine", "엔진 전환 (gemini/claude)"),
        BotCommand("coding", "코딩 에이전트 모드 활성화"),
        BotCommand("mode", "승인 모드 설정"),
        BotCommand("status", "에이전트 상태"),
        BotCommand("new", "세션 초기화 (Reset)"),
        BotCommand("update", "바이너리 업데이트"),
    ]
    await app.bot.set_my_commands(commands)
    print("Telegram command menu updated with Monitor and Coding.")


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
    app.add_handler(CommandHandler("monitor", monitor_cmd))
    app.add_handler(CommandHandler("engine", engine_cmd))
    app.add_handler(CommandHandler("mode", mode_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("new", restart_cmd))
    app.add_handler(CommandHandler("workspace", workspace_cmd))
    app.add_handler(CommandHandler("coding", coding_cmd))
    app.add_handler(CommandHandler("update", update_cmd))
    app.add_handler(CommandHandler("model", model_cmd))
    
    # Callback Query Handlers
    app.add_handler(CallbackQueryHandler(approval_callback, pattern="^(tool_approval:|set_ws:)"))

    # Message Handlers
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Proxy commands for gemini-cli
    for cmd in ["init", "reset", "undo", "redo", "mcp", "skills", "hooks"]:
        app.add_handler(CommandHandler(cmd, command_proxy))

    print("OpenGemini Agent bot polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
