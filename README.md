# OpenGemini Agent Platform

Telegram에서 Gemini CLI / Claude Code를 붙여서 사용하는 개인용 에이전트 봇입니다.

---

## 기능 요약

- `/engine`으로 Gemini ↔ Claude 전환
- `/workspace`로 작업 경로 전환
- `/mode`로 승인 모드 변경(default/plan/yolo)
- 대화형 코딩 지원(`/coding`)
- 채팅별 세션 유지

---

## 1) 새 Ubuntu 서버에 처음 설치하기

### 요구사항

- Ubuntu 22.04+ (권장)
- Python 3.10+
- Node.js 20+
- Telegram Bot Token
- 본인 Telegram User ID (숫자)

### 1-1. 시스템 패키지

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
```

### 1-2. 저장소 클론

```bash
git clone https://github.com/GNchoo/OpenGemini.git
cd OpenGemini
```

### 1-3. Python 의존성 설치 (venv 권장)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

### 1-4. CLI 설치

```bash
# Node.js가 없다면 먼저 설치 (nvm 또는 apt 이용)
# 예시: nvm 사용 시
# curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
# source ~/.nvm/nvm.sh
# nvm install 22

npm install -g @google/gemini-cli
# claude-code를 사용한다면 별도 설치 필요
```

설치 경로 확인:

```bash
which gemini
which claude   # claude-code 설치 시
```

### 1-5. 환경변수 설정

```bash
cp .env.template .env
nano .env
```

필수 항목:

```env
TELEGRAM_TOKEN=...
ALLOWED_USER_ID=123456789
GEMINI_BIN=/실제/gemini/바이너리/경로
CLAUDE_BIN=/실제/claude/바이너리/경로
GEMINI_WORKDIR=/home/<user>/OpenGemini/workspace
DEFAULT_ENGINE=gemini
```

> 참고: 코드 기준 모델 변수는 `GEMINI_MODEL`을 읽습니다. (`GEMINI_MODEL_DEFAULT`가 아니라 `GEMINI_MODEL` 사용 권장)

### 1-6. 실행

```bash
source .venv/bin/activate
python bot.py
```

정상 실행 시, Telegram에서 `/start`로 확인하세요.

---

## 2) 운영 권장 (tmux 또는 systemd)

### tmux로 백그라운드 실행

```bash
tmux new -s opengemini
source .venv/bin/activate
python bot.py
# Ctrl+b, d 로 분리
```

### systemd (user) 예시

`~/.config/systemd/user/opengemini.service`

```ini
[Unit]
Description=OpenGemini Telegram Bot
After=network.target

[Service]
WorkingDirectory=/home/<user>/OpenGemini
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/<user>/OpenGemini/.venv/bin/python /home/<user>/OpenGemini/bot.py
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
```

적용:

```bash
systemctl --user daemon-reload
systemctl --user enable --now opengemini
systemctl --user status opengemini
```

---

## 3) 자주 쓰는 봇 명령어

- `/start` : 시작 안내
- `/help` : 명령어 도움말
- `/engine [gemini|claude]` : 엔진 전환
- `/model [name]` : 모델 전환
- `/mode [default|plan|yolo]` : 승인 모드
- `/workspace [path]` : 작업 폴더 변경
- `/status` : 현재 엔진/세션 상태
- `/new` : 세션 초기화
- `/coding` : 코딩 에이전트 모드

---

## 4) 보안 체크리스트 (중요)

- `.env`는 **절대 커밋 금지**
- Git remote URL에 PAT(토큰) 직접 넣지 않기
- 토큰이 채팅/로그에 노출되면 즉시 revoke 후 재발급
- `ALLOWED_USER_ID`를 본인 ID로 고정
- 필요하면 `GEMINI_SANDBOX=true`로 실행

간단 점검:

```bash
git status
git remote -v
```

---

## 5) 트러블슈팅

### 봇이 응답하지 않을 때

1. `TELEGRAM_TOKEN`, `ALLOWED_USER_ID` 확인
2. `GEMINI_BIN` 경로 실제 존재 여부 확인
3. 동일 봇 중복 실행 여부 확인 (`.bot.lock`)

### Gemini/Claude 실행 오류

- `which gemini`, `which claude`로 바이너리 확인
- 해당 경로를 `.env`의 `GEMINI_BIN`, `CLAUDE_BIN`에 정확히 반영
- 필요시 CLI 로그인/인증 재진행

---

## 라이선스

내부/개인 운영 목적 기준으로 사용 중. 필요 시 별도 라이선스 정책 추가하세요.
