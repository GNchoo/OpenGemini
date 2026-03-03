# OpenGemini

[English](README_EN.md) | [한국어](README_KR.md)

OpenGemini는 Gemini CLI와 SuperGemini를 텔레그램 봇으로 연동하여 텔레그램 상에서 끊김 없는 원격 대화형 코딩, 모델 관리, 고급 MCP(Model Context Protocol) 기술들을 곧바로 사용할 수 있게 해주는 프로젝트입니다.

## 주요 기능
- **대화형 코딩**: `pexpect`를 통해 로컬 `gemini` CLI 파이프라인과 연결하여 장시간 지속되는 원격 프롬프팅이 가능합니다.
- **다중 모델 스위칭**: 대화 중간에 프로세스 중단 없이 `/model [모델명]` 명령어로 작동 중인 AI 모델을 즉각적으로 변경할 수 있습니다.
- **안정적인 시스템 서비스화**: 백그라운드 데몬(`systemd`)으로 구동되어 24시간 내내 안정적인 동작을 보장합니다.
- **자동 업데이트**: `/update` 명령어 한 번으로 시스템 내부의 Gemini CLI 패키지를 최신 버전으로 업데이트하고 봇을 자동 재시작합니다.
- **MCP 통합 연동**: SuperGemini 설정과 Github MCP Server 등 고급 플러그인 연동을 완벽히 지원하여 터미널과 동일한 기술 수준을 모바일 환경에서도 누릴 수 있게 합니다.

## 요구 사항
- Python 3.10 이상
- npm을 통해 설치된 `gemini` CLI (`npm install -g gemini` 명령어 사용)
- Telegram 봇 토큰 (BotFather를 통해 발급)

## 설치 방법
1. 저장소 클론:
   ```bash
   git clone https://github.com/GNchoo/OpenGemini.git
   cd OpenGemini
   ```
2. 가상 환경 생성 및 활성화:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
3. 의존성 패키지 설치:
   ```bash
   pip install -r requirements.txt
   ```

## 환경 설정 구성하기
발급받은 텔레그램 봇 토큰과 자신의 텔레그램 User ID(유저 아이디)를 `bot.py` 스크립트 상단에 작성하여 타인의 접속을 제한합니다:
```python
BOT_TOKEN = '여러분의_봇_토큰'
ALLOWED_USER_ID = 여러분의_텔레그램_유저_아이디
```
봇을 처음 시작하기 전에 터미널에서 `gemini auth`를 실행하여 Gemini CLI 계정 연동을 먼저 완료해 주어야 합니다.

## 백그라운드 데몬으로 실행하기 (시스템 서비스화)
서버를 종료해도 봇이 꺼지지 않고 백그라운드에서 상시 작동되도록 systemd를 설정합니다.
1. `~/.config/systemd/user/tg-gemini.service` 파일을 만들고 아래 코드를 입력합니다 (본인 서버의 로컬 경로에 맞춰 수정 요망):
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
2. 시스템 서비스 데몬을 활성화하고 봇을 시작합니다:
```bash
systemctl --user daemon-reload
systemctl --user enable tg-gemini.service
systemctl --user start tg-gemini.service
```

## 사용 가능한 명령어
- `/start` - Gemini CLI와 백그라운드 파이프라인 연결을 시작합니다.
- `/model [모델명]` - 현재 대화를 이어갈 활성 LLM 모델을 변경합니다.
- `/update` - 전역 환경의 `gemini` npm 패키지를 최신 버전 상태로 끌어올린 후 연결을 재시작합니다.
- `/restart` - 기존 백그라운드 프로세스를 Kill 하고 완전히 새로운 터미널 인스턴스를 하나 띄워서 초기화해 줍니다.
- `/help` - 사용할 수 있는 도움말과 명령어 목록들을 보여줍니다.
