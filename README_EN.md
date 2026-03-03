# OpenGemini

[English](README_EN.md) | [한국어](README_KR.md)
# OpenGemini

OpenGemini is a Telegram bot integration for the Gemini CLI and SuperGemini, allowing seamless remote conversational coding, model management, and advanced MCP (Model Context Protocol) capabilities directly from Telegram.

## Features
- **Conversational Coding**: Connects to the local `gemini` CLI via `pexpect` for long-running remote prompting.
- **Model Switching**: `/model [model_name]` to switch between different AI models on the fly without interrupting the process.
- **System Service**: Runs as a background daemon (`systemd`) for stable 24/7 continuous operation.
- **Auto-Update**: `/update` command to update the underlying Gemini CLI and automatically restart the bot.
- **MCP Integration**: Fully supports SuperGemini configurations and MCP servers such as the GitHub MCP Server.

## Prerequisites
- Python 3.10+
- `gemini` CLI installed via npm (`npm install -g gemini`)
- Telegram Bot Token

## Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/GNchoo/OpenGemini.git
   cd OpenGemini
   ```
2. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration
Edit the `bot.py` script and update it with your Telegram Bot Token and your User ID (to restrict access):
```python
BOT_TOKEN = 'YOUR_BOT_TOKEN'
ALLOWED_USER_ID = YOUR_TELEGRAM_USER_ID
```
Ensure you have authenticated to your Gemini CLI by running `gemini auth` in the terminal first before starting the bot.

## Running as a Service
For continuous operation, set up the systemd service.
1. Create `~/.config/systemd/user/tg-gemini.service` with the following configuration (adjusting the paths):
```ini
[Unit]
Description=Telegram Gemini Agent Bot
After=network.target

[Service]
Type=simple
ExecStart=~/tools/tg_gemini/venv/bin/python3 -u ~/tools/tg_gemini/bot.py
WorkingDirectory=~/tools/tg_gemini
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```
2. Enable and start the service:
```bash
systemctl --user daemon-reload
systemctl --user enable tg-gemini.service
systemctl --user start tg-gemini.service
```

## Commands
- `/start` - Start interacting with the Gemini CLI.
- `/model [name]` - Switch the active LLM.
- `/update` - Update the global `gemini` npm package and restart the connection.
- `/restart` - Kill the existing background process and spawn a fresh instance.
- `/help` - Show the help menu.
