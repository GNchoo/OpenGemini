# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OpenGemini is a Telegram bot that serves as an AI agent orchestrator, integrating `gemini-cli` and `claude-code` CLI tools through a `pexpect`-based headless execution layer. Users interact via Telegram; the bot forwards messages to the selected AI engine, captures output, and auto-uploads any new/modified workspace files.

## Running the Bot

```bash
# Direct execution
python bot.py

# Using startup script (handles pkill cleanup + nohup)
./start_bot.sh

# Via systemd
systemctl --user start tg-gemini.service
```

## Setup

```bash
pip install python-telegram-bot pexpect python-dotenv
npm install -g @google/gemini-cli
cp .env.template .env  # then fill in credentials
```

## Key `.env` Variables

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_TOKEN` | — | Bot token from @BotFather |
| `ALLOWED_USER_ID` | — | Single authorized user's numeric Telegram ID |
| `GEMINI_BIN` | `/usr/local/share/npm-global/bin/gemini` | Path to gemini-cli binary |
| `CLAUDE_BIN` | `/home/fallman/.npm-global/bin/claude` | Path to claude-code binary |
| `DEFAULT_ENGINE` | `gemini` | `gemini` or `claude` |
| `GEMINI_WORKDIR` | `./workspace` | Working directory for file operations |
| `GEMINI_APPROVAL_MODE` | `yolo` | `default`, `plan`, or `yolo` |
| `GEMINI_SANDBOX` | `true` | Enable Gemini CLI sandbox mode |
| `GEMINI_MODEL` | `gemini-2.5-pro` | Default Gemini model |

## Architecture

All logic lives in `bot.py`. The class hierarchy:

- **`BaseAgentEngine`** — Abstract base. Handles ANSI/noise cleanup, session ID generation (UUID5 hash of `chat_id`), and async locking.
- **`GeminiAgentEngine`** — Runs `gemini -p <prompt>` with `--resume latest` for session persistence. Parses JSON output from gemini-cli, with fallback to plain text.
- **`ClaudeAgentEngine`** — Runs `claude -p <prompt> --session-id <id>` with `--dangerously-skip-permissions`. Handles OAuth login flow via a background `pexpect` child.

Engine instances are stored in a global dict: `ENGINES: dict[(chat_id, engine_type), BaseAgentEngine]`.

**Message flow:** Telegram message → auth check → route to active engine → pexpect subprocess → clean output → chunk to 3500 chars → send to Telegram → detect workspace file changes → auto-upload new/modified files.

## Workspace & File Tracking

- `GEMINI_WORKDIR` (default: `./workspace`) is the root for all file operations.
- The bot snapshots file mtimes before each query and uploads any new/modified files afterward.
- Output files intended for the user should be saved to `workspace/` to trigger auto-upload.
- Session state: `workspace/.sessions/`, Lock file: `workspace/.bot.lock`, Persistence: `workspace/.bot_persistence.pickle`.

## Testing

```bash
python test_gemini.py   # Tests pexpect interaction with gemini-cli
python test_parse.py    # Tests JSON parsing of noisy CLI output
```

No formal test framework is configured.

## Integrated Projects

This bot manages two external trading systems (see `GEMINI.md` for details):
- **CoinTrader** — `/home/fallman/projects/CoinTrader`, managed by `trader-autotrader.service`
- **StockTrader** — `/home/fallman/projects/StockTrader`, Korean market hours (09:00–15:30 KST)

When modifying trading logic, always create a `.bak` backup and test in paper/mock mode before live execution.
