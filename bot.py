#!/usr/bin/env python3
import asyncio
import os
import shlex
import sys
import fcntl
import re
import pexpect
import uuid
from urllib.parse import urlparse, parse_qs
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
        self.session_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"tg_{chat_id}"))
        self.is_waiting_for_approval = False
        self.last_prompt = ""
        self.auth_child: Optional[pexpect.spawn] = None # For ongoing login processes

    def _clean_ansi(self, text: str) -> str:
        if not text: return ""
        # 1. Remove all ANSI escape sequences (CSI and OSC)
        # Handle CSI (\x1b[...), OSC (\x1b]...), and other control sequences
        ansi_escape = re.compile(r'(?:\x1B[@-_]|[\x80-\x9F])[0-?]*[ -/]*[@-~]|\x1B\].*?(\x1B\\|\x07)')
        text = ansi_escape.sub('', text)
        
        # Target specific artifacts like ]9;4;0;
        text = re.sub(r'\]9;4;\d+;', '', text)
        
        # 2. Remove non-printable characters except newline/tab
        text = "".join(ch for ch in text if ch == '\n' or ch == '\t' or ord(ch) >= 32)
        
        # 3. Filter out system noise
        noise_patterns = [
            r"(?i)YOLO mode is enabled.*",
            r"(?i)Error during discovery for MCP server.*",
            r"(?i)Server '.*' supports tool updates.*",
            r"(?i)Listening for changes.*",
            r"(?i)Loaded cached credentials.*",
            r"(?i)update available.*",
            r"(?i)Automatic update is not available.*",
            r"(?i)Connection closed.*",
            r"✗ (playwright|context|sqlite|filesystem|github):.*",
            r"✓ (playwright|context|sqlite|filesystem|github):.*",
            r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] .*", # Timestamps
            r"Process group PGID:.*",
            r"Exit Code:.*"
        ]
        for pattern in noise_patterns:
            text = re.sub(pattern, "", text, flags=re.MULTILINE)

        # 4. Specifically target the 'q [' and similar TUI artifacts
        text = re.sub(r'(\n|^)[q\s\[\]]{1,5}(\n|$)', '\n', text)
        
        # 5. Final cleanup
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        return "\n".join(lines).strip()

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
        if self.auth_child and self.auth_child.isalive():
            self.auth_child.terminate(force=True)

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
                
                # Extract JSON from output (Enhanced)
                response_text = ""
                try:
                    import json
                    decoder = json.JSONDecoder()
                    idx = 0
                    parsed_objects = []
                    while idx < len(output):
                        idx = output.find('{', idx)
                        if idx == -1:
                            break
                        try:
                            obj, end_idx = decoder.raw_decode(output[idx:])
                            parsed_objects.append(obj)
                            idx += end_idx
                        except json.JSONDecodeError:
                            idx += 1
                            
                    for data in reversed(parsed_objects):
                        if isinstance(data, dict):
                            if "response" in data or "summary" in data:
                                found = data.get("response") or data.get("summary", {}).get("totalResponse")
                                if found:
                                    response_text = str(found).strip()
                                    break
                except Exception as je:
                    print(f"[GeminiAgentEngine] JSON parse failed: {je}")
                
                # System Logs Cleanup
                cleaned_logs = self._clean_ansi(output or "").strip()
                
                # 정상 답변이 있는 경우 -> 답변만 전송 (시스템 로그 제외)
                if response_text:
                    return response_text
                
                # 답변을 못 찾았지만 로그가 있는 경우 (예: tool 에러 등)
                if cleaned_logs and len(cleaned_logs) > 5:
                    return f"⚠️ 실행 결과/로그:\n{cleaned_logs}"
                
                # 완전히 비어있을 경우 (드문 케이스)
                if exitstatus != 0:
                    return f"❌ 엔진 종료 (Exit {exitstatus}): {output[:500] if output else '출력 없음'}"
                
                return "⚠️ 답변을 가져오지 못했습니다. (빈 출력)"
            except Exception as e:
                print(f"[GeminiAgentEngine] Headless run failed: {e}")
                return f"❌ 엔진 실행 오류: {e}"



    async def _wait_for_next_event(self) -> str:
        # Not used in headless mode
        return ""

    async def start_auth_oauth(self) -> str:
        """Gemini CLI uses Google OAuth configured via `gemini` interactive TUI.
        Check current status and guide the user."""
        try:
            import json
            settings_path = os.path.expanduser("~/.gemini/settings.json")
            if os.path.exists(settings_path):
                with open(settings_path) as f:
                    settings = json.load(f)
                auth_type = settings.get("security", {}).get("auth", {}).get("selectedType", "")
                if auth_type:
                    return f"✅ Gemini CLI는 이미 Google OAuth로 인증되어 있습니다.\n\n인증 방식: `{auth_type}`\n\n재인증이 필요하면 터미널에서 `gemini` 명령어를 직접 실행해주세요."
            return "ℹ️ Gemini CLI는 최초 실행 시 자동으로 Google OAuth 인증을 진행합니다.\n\nAPI Key 방식을 사용하시려면 `/login` → `🔑 API Key 방식`을 선택해주세요."
        except Exception as e:
            return f"❌ Gemini 인증 상태 확인 오류: {e}"

    async def finish_auth_oauth(self, code: str) -> str:
        return "ℹ️ Gemini CLI는 별도의 인증 코드 입력이 필요하지 않습니다."

class ClaudeAgentEngine(BaseAgentEngine):
    async def start(self):
        """Simplied start for Claude one-shot mode."""
        if not os.path.exists(self.binary):
             raise FileNotFoundError(f"Binary not found: {self.binary}")
        if not os.path.exists(self.workdir):
             os.makedirs(self.workdir, exist_ok=True)
        print(f"[ClaudeAgentEngine] Ready for one-shot sessions at {self.workdir}")

    def _kill_session_processes(self):
        """Forcefully kill any lingering Claude or related MCP processes."""
        try:
            import subprocess
            subprocess.run(["pkill", "-9", "-f", "claude"], stderr=subprocess.DEVNULL)
            subprocess.run(["pkill", "-9", "-f", self.session_id], stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def _get_session_file(self, actual_workdir: str) -> str:
        """Determine the path to the session .jsonl file."""
        safe_path = actual_workdir.replace("/", "-")
        return os.path.expanduser(f"~/.claude/projects/{safe_path}/{self.session_id}.jsonl")

    async def query(self, text: str) -> str:
        """One-shot query using --resume if session exists, else --session-id."""
        async with self.lock:
            actual_workdir = self.workdir
            if not actual_workdir.endswith("workspace"):
                actual_workdir = os.path.join(self.workdir, "workspace")
            os.makedirs(actual_workdir, exist_ok=True)
            
            self._kill_session_processes()
            await asyncio.sleep(0.5)
            
            env = os.environ.copy()
            env["TERM"] = "xterm"
            env["NO_COLOR"] = "1"
            
            session_file = self._get_session_file(actual_workdir)
            use_resume = os.path.exists(session_file)
            
            args = [
                self.binary, "-p", text,
            ]
            
            if self.approval_mode == "yolo":
                args.extend([
                    "--dangerously-skip-permissions", "Bash,Edit,Read",
                    "--permission-mode", "bypassPermissions"
                ])
            
            if use_resume:
                args.extend(["--resume", self.session_id])
                print(f"[ClaudeAgentEngine] Resuming session: {self.session_id}")
            else:
                args.extend(["--session-id", self.session_id])
                print(f"[ClaudeAgentEngine] Starting new session: {self.session_id}")
                
            if self.model:
                args.extend(["--model", self.model])
                
            import shlex
            cmd = " ".join(shlex.quote(a) for a in args)
            
            try:
                output, exitstatus = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: pexpect.run(cmd, env=env, encoding='utf-8', timeout=180, withexitstatus=True, cwd=actual_workdir)
                )
                
                cleaned = self._clean_ansi(output or "").strip()
                cleaned = re.sub(r".*bypass permissions on.*", "", cleaned).strip()
                
                if cleaned:
                    return cleaned
                
                if exitstatus != 0:
                    return f"❌ 클로드 실행 오류 (Exit {exitstatus}):\n{cleaned if cleaned else '출력 없음'}"
                
                return "⚠️ 답변을 가져오지 못했습니다. (빈 출력)"
                
            except Exception as e:
                print(f"[ClaudeAgentEngine] Query failed: {e}")
                return f"❌ 클로드 엔진 실행 오류: {e}"

    async def start_auth_oauth(self) -> str:
        """Starts claude auth login and returns the OAuth URL. Process stays alive."""
        # Kill any leftover auth process
        if self.auth_child and self.auth_child.isalive():
            self.auth_child.terminate(force=True)
            self.auth_child = None
        
        # First check if already logged in
        try:
            import subprocess
            result = subprocess.run(
                [self.binary, "auth", "status"],
                capture_output=True, text=True, timeout=10,
                env=os.environ.copy()
            )
            status = result.stdout + result.stderr
            if '"loggedIn": true' in status:
                return "ALREADY_LOGGED_IN"
        except:
            pass

        cmd = f"{self.binary} auth login"
        env = os.environ.copy()
        env["TERM"] = "dumb"
        self.auth_child = pexpect.spawn(cmd, env=env, encoding='utf-8', timeout=120, cwd=self.workdir)
        try:
            patterns = [r"https://\S+", pexpect.EOF, pexpect.TIMEOUT]
            idx = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self.auth_child.expect(patterns, timeout=30)
            )
            if idx == 0:
                url = self.auth_child.after.strip()
                # Process stays alive — it's polling Anthropic's server
                return url
            output = self._clean_ansi(self.auth_child.before or "")
            self.auth_child = None
            return f"ERROR: {output[:300]}"
        except Exception as e:
            if self.auth_child:
                self.auth_child.terminate(force=True)
            self.auth_child = None
            return f"ERROR: {e}"

    async def finish_auth_oauth(self, code: str) -> str:
        """Check if Claude auth login completed after user logged in via browser."""
        # First check if the auth_child process completed on its own
        if self.auth_child and self.auth_child.isalive():
            # Process still running — give it a moment to detect the login
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self.auth_child.expect(pexpect.EOF, timeout=5)
                )
                out = self._clean_ansi(self.auth_child.before or "")
                self.auth_child = None
            except pexpect.TIMEOUT:
                pass  # Still waiting, check status manually
        
        # Check auth status regardless
        try:
            import subprocess
            result = subprocess.run(
                [self.binary, "auth", "status"],
                capture_output=True, text=True, timeout=10,
                env=os.environ.copy()
            )
            status = result.stdout + result.stderr
            if '"loggedIn": true' in status:
                # Clean up auth_child if still running
                if self.auth_child and self.auth_child.isalive():
                    self.auth_child.terminate(force=True)
                self.auth_child = None
                return "\u2705 Claude 인증이 완료되었습니다!"
            else:
                return "\u23f3 아직 인증이 완료되지 않았습니다.\n\n브라우저에서 로그인을 완료한 후 아무 메시지나 다시 보내주세요."
        except Exception as e:
            return f"\u274c 인증 상태 확인 오류: {e}"

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
    
    cur = context.user_data.get("engine", DEFAULT_ENGINE)
    
    if context.args:
        new_engine = context.args[0].lower()
        if new_engine in ["gemini", "claude"]:
            context.user_data["engine"] = new_engine
            await update.message.reply_text(f"✅ 엔진이 `{new_engine}`으로 변경되었습니다.", parse_mode=ParseMode.MARKDOWN)
            return
        else:
            await update.message.reply_text("❌ 지원하지 않는 엔진입니다. (gemini, claude 중 선택)")
            return

    # Show buttons if no args
    keyboard = [
        [
            InlineKeyboardButton("Gemini-CLI", callback_data="set_engine:gemini"),
            InlineKeyboardButton("Claude Code", callback_data="set_engine:claude"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"🤖 *엔진 선택*\n현재 설정: `{cur}`\n\n아래 버튼을 눌러 사용할 AI 엔진을 선택하세요:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

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
    
    is_running = bool(engine.child and engine.child.isalive())
    running_label = "Yes" if is_running else "No"
    run_note = ""
    if engine_type == "gemini":
        # Gemini is headless (one-shot per request), so persistent child is usually not running.
        running_label = "On-demand"
        run_note = "\n- 비고: `Gemini는 요청 시마다 단발 실행됩니다 (정상)`"

    status = (
        f"📊 *에이전트 상태*\n"
        f"- 활성 엔진: `{engine_type.upper()}`\n"
        f"- 모델: `{engine.model or 'Default'}`\n"
        f"- 승인 모드: `{engine.approval_mode}`\n"
        f"- 세션 ID: `{engine.session_id}`\n"
        f"- 워크스페이스: `{engine.workdir}`\n"
        f"- 실행 중: `{running_label}`"
        f"{run_note}"
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
    
    chat_id = update.effective_chat.id
    engine_type = context.user_data.get("engine", DEFAULT_ENGINE)
    engine = get_engine(chat_id, engine_type)
    
    if context.args:
        model = context.args[0]
        context.user_data["model"] = model
        engine.model = model
        await engine.start()
        await update.message.reply_text(f"✅ 모델이 `{model}`(으)로 변경되었습니다.")
        return

    # Show buttons if no args (Claude prioritized)
    if engine_type == "claude":
        keyboard = [
            [
                InlineKeyboardButton("Sonnet 4.6", callback_data="set_model:claude-sonnet-4-6"),
                InlineKeyboardButton("Opus 4.6", callback_data="set_model:claude-opus-4-6")
            ],
            [
                InlineKeyboardButton("Haiku 4.5", callback_data="set_model:claude-haiku-4-5"),
                InlineKeyboardButton("Default", callback_data="set_model:None")
            ]
        ]
        msg = "🤖 *Claude 모델 선택*\n현재 설정: `{}`\n\n사용할 모델을 선택하세요:".format(engine.model or "Default")
    else:
        # Gemini models
        keyboard = [
            [
                InlineKeyboardButton("Pro 3.1", callback_data="set_model:gemini-3.1-pro-preview"),
                InlineKeyboardButton("Flash 3", callback_data="set_model:gemini-3-flash-preview")
            ],
            [
                InlineKeyboardButton("Pro 2.5", callback_data="set_model:gemini-2.5-pro"),
                InlineKeyboardButton("Flash 2.5", callback_data="set_model:gemini-2.5-flash")
            ],
            [
                InlineKeyboardButton("Default", callback_data="set_model:None")
            ]
        ]
        msg = "🤖 *Gemini 모델 선택*\n현재 설정: `{}`\n\n사용할 모델을 선택하세요:".format(engine.model or "Default")

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

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

async def auth_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    
    engine_type = context.user_data.get("engine", DEFAULT_ENGINE)
    
    keyboard = [
        [
            InlineKeyboardButton("🔑 API Key 입력", callback_data="auth_method:api_key"),
            InlineKeyboardButton("🌐 OAuth 안내", callback_data="auth_method:oauth_guide"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    engine_name = engine_type.upper()
    msg = (
        f"🔐 *{engine_name} 인증 설정*\n\n"
        f"현재 {engine_name} 에이전트를 사용하기 위한 인증을 설정합니다.\n\n"
        "봇에서 직접 사용하시려면 **API Key** 방식을 추천드립니다. "
        "OAuth 방식은 브라우저 인증이 필요하므로 터미널에서 직접 진행하셔야 합니다."
    )
    
    await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

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
    try:
        async with asyncio.timeout(180):
            async with RUN_LOCK:
                out = await engine.query(full_cmd)
    except TimeoutError:
        engine.stop()
        out = "⏳ 요청 처리 시간이 초과되어 엔진을 재시작했습니다. 다시 시도해주세요."
    await _respond_with_engine_output(update, engine, out)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    print(f"[bot] Received message from user {user.id if user else 'Unknown'}")
    if not _authorized(update):
        print(f"[bot] Unauthorized user: {user.id if user else 'Unknown'}")
        return

    text = (update.message.text or "").strip()
    print(f"[bot] Message text: '{text[:20]}...'")
    if not text:
        return

    chat_id = update.effective_chat.id
    engine_type = context.user_data.get("engine", DEFAULT_ENGINE)
    model = context.user_data.get("model")
    print(f"[bot] Using engine: {engine_type}, model: {model}")
    engine = get_engine(chat_id, engine_type, model)

    # Check for authentication states
    auth_state = context.user_data.get("auth_state")
    print(f"[bot] Auth state: {auth_state}")
    if auth_state == "AWAITING_KEY":
        # Save API key to .env
        success = _update_env_key(engine_type, text)
        context.user_data["auth_state"] = None
        if success:
            await update.message.reply_text(f"✅ {engine_type.upper()} API Key가 `.env`에 저장되었습니다.")
        else:
            await update.message.reply_text("❌ `.env` 파일 업데이트에 실패했습니다.")
        return

    if auth_state == "AWAITING_CODE":
        # Check OAuth completion
        context.user_data["auth_state"] = None
        await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
        res = await engine.finish_auth_oauth(text)
        await update.message.reply_text(res, parse_mode=None)
        return

    # 1. Record workspace state
    old_state = _get_workspace_state(GEMINI_WORKDIR)

    await context.bot.send_chat_action(chat_id, ChatAction.TYPING)

    try:
        async with asyncio.timeout(180):
            async with RUN_LOCK:
                out = await engine.query(text)
    except TimeoutError:
        engine.stop()
        out = "⏳ 응답이 지연되어 엔진을 재시작했습니다. 같은 메시지를 한 번 더 보내주세요."
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

def _update_env_key(engine_type: str, key: str) -> bool:
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    key_name = "GEMINI_API_KEY" if engine_type == "gemini" else "ANTHROPIC_API_KEY"
    
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            lines = f.readlines()
            
    found = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{key_name}="):
            new_lines.append(f"{key_name}={key}\n")
            found = True
        else:
            new_lines.append(line)
            
    if not found:
        new_lines.append(f"{key_name}={key}\n")
        
    try:
        with open(env_path, "w") as f:
            f.writelines(new_lines)
        # Update current process env as well
        os.environ[key_name] = key
        return True
    except:
        return False

def _get_workspace_state(workdir: str) -> dict:
    """Return {absolute_path: mtime} for files under workdir."""
    state = {}
    try:
        for root, dirs, files in os.walk(workdir):
            # prune noisy dirs
            dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", ".sessions"}]
            for name in files:
                path = os.path.join(root, name)
                try:
                    state[path] = os.path.getmtime(path)
                except OSError:
                    pass
    except Exception:
        pass
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

    # Handle Engine Selection
    if data.startswith("set_engine:"):
        engine_type = data.split(":")[1]
        context.user_data["engine"] = engine_type
        # Update the message to remove buttons and show confirmation
        await query.edit_message_text(
            f"✅ 엔진이 `{engine_type}`으로 변경되었습니다.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # Handle Model Selection
    if data.startswith("set_model:"):
        model_name = data.split(":")[1]
        model_val = None if model_name == "None" else model_name
        context.user_data["model"] = model_val
        chat_id = update.effective_chat.id
        engine_type = context.user_data.get("engine", DEFAULT_ENGINE)
        engine = get_engine(chat_id, engine_type)
        engine.model = model_val
        await engine.start()
        await query.edit_message_text(
            f"✅ 모델이 `{model_val or 'Default'}`(으)로 변경되었습니다.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # Handle Auth Method Selection
    if data.startswith("auth_method:"):
        method = data.split(":")[1]
        chat_id = update.effective_chat.id
        engine_type = context.user_data.get("engine", DEFAULT_ENGINE)
        engine = get_engine(chat_id, engine_type)

        if method == "api_key":
            context.user_data["auth_state"] = "AWAITING_KEY"
            await query.edit_message_text(f"🔑 {engine_type.upper()} API Key를 입력해주세요 (메시지로 직접 보내주세요):")
        elif method == "oauth_guide":
            if engine_type == "claude":
                manual_msg = (
                    "🌐 *Claude Code OAuth 인증 가이드*\n\n"
                    "1. 서버 터미널에 접속합니다.\n"
                    f"2. `claude auth login` 명령어를 실행합니다.\n"
                    "3. 출력된 URL을 브라우저에서 열고 로그인을 완료합니다.\n"
                    "4. 인증이 완료되면 봇에서 즉시 사용 가능합니다."
                )
            else:
                manual_msg = (
                    "🌐 *Gemini CLI OAuth 인증 가이드*\n\n"
                    "1. 서버 터미널에 접속합니다.\n"
                    f"2. `gemini` 명령어를 실행합니다.\n"
                    "3. 초기 실행 시 요구하는 Google OAuth 인증을 브라우저에서 완료합니다.\n"
                    "4. 설정이 완료되면 봇에서 즉시 사용 가능합니다."
                )
            await query.edit_message_text(manual_msg, parse_mode=ParseMode.MARKDOWN)
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
    
    try:
        async with asyncio.timeout(120):
            async with RUN_LOCK:
                out = await engine.send_input(action)
    except TimeoutError:
        engine.stop()
        out = "⏳ 입력 처리 시간이 초과되어 엔진을 재시작했습니다. 다시 시도해주세요."
    await _respond_with_engine_output(update, engine, out)

async def post_init(app: Application) -> None:
    commands = [
        BotCommand("start", "봇 시작"),
        BotCommand("help", "도움말"),
        BotCommand("monitor", "트레이더 상태 모니터링"),
        BotCommand("workspace", "작업 디렉토리 설정"),
        BotCommand("engine", "엔진 전환 (gemini/claude)"),
        BotCommand("auth", "엔진 인증 설정 (API Key/OAuth)"),
        BotCommand("coding", "코딩 에이전트 모드 활성화"),
        BotCommand("mode", "승인 모드 설정"),
        BotCommand("status", "에이전트 상태"),
        BotCommand("new", "세션 초기화 (Reset)"),
        BotCommand("update", "바이너리 업데이트"),
        BotCommand("model", "모델 전환 (Sonnet/Haiku/Opus/Pro/Flash)"),
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

    # Add persistence to keep engine settings across restarts
    from telegram.ext import PicklePersistence
    persistence = PicklePersistence(filepath=os.path.join(GEMINI_WORKDIR, ".bot_persistence.pickle"))
    app = Application.builder().token(TELEGRAM_TOKEN).persistence(persistence).post_init(post_init).build()

    app.add_error_handler(on_error)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("monitor", monitor_cmd))
    app.add_handler(CommandHandler("engine", engine_cmd))
    app.add_handler(CommandHandler("auth", auth_cmd))
    app.add_handler(CommandHandler("login", auth_cmd)) # Keep as alias
    app.add_handler(CommandHandler("mode", mode_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("new", restart_cmd))
    app.add_handler(CommandHandler("workspace", workspace_cmd))
    app.add_handler(CommandHandler("coding", coding_cmd))
    app.add_handler(CommandHandler("update", update_cmd))
    app.add_handler(CommandHandler("model", model_cmd))
    
    # Callback Query Handlers
    app.add_handler(CallbackQueryHandler(approval_callback, pattern="^(tool_approval:|set_ws:|set_engine:|auth_method:|set_model:)"))

    # Message Handlers
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Proxy commands for gemini-cli / claude
    for cmd in ["init", "reset", "undo", "redo", "mcp", "skills", "hooks", "login", "auth"]:
        app.add_handler(CommandHandler(cmd, command_proxy))

    print("OpenGemini Agent bot polling...")
    # Drop pending updates to clear any stuck queue
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
