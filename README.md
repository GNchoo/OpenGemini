# OpenGemini 에이전트 플랫폼 (OpenGemini Agent Platform)

[English](README_EN.md) | [한국어](README.md)

OpenGemini는 Google의 Gemini CLI와 Anthropic의 Claude Code를 텔레그램 봇으로 연동하여, 모바일에서도 강력한 AI 엔지니어링 도구를 사용할 수 있게 해주는 개인용 에이전트 플랫폼입니다.

---

## 🌟 주요 기능

- **듀얼 엔진 지원**: `/engine` 명령어로 Gemini와 Claude 사이를 즉시 전환할 수 있습니다.
- **최신 2026년형 모델**: 
    - **Claude**: Sonnet 4.6, Opus 4.6, Haiku 4.5 지원
    - **Gemini**: Pro 3.1 Preview, Flash 3 Preview, Flash 2.0 지원
- **버튼 기반 UI**: `/model` 명령어를 통해 최신 모델들을 버튼 하나로 간편하게 선택할 수 있습니다.
- **세션 지속성 (Continuity)**: 클로드의 `--resume` 플래그를 완벽히 지원하여, 대화 맥락이 끊기지 않고 유지됩니다.
- **승인 모드 통합**: `/mode yolo`를 통해 터미널 접속 없이도 모든 권한(Bash, Edit, Read)을 자동으로 승인하도록 설정할 수 있습니다.
- **워크스페이스 관리**: `/workspace` 명령어로 작업 경로를 자유롭게 변경하고 관리할 수 있습니다.
- **안정적인 운영**: 싱글톤 락(Singleton Lock) 및 24시간 백그라운드 구동 스크립트(`start_bot.sh`)를 제공합니다.

---

## 💻 윈도우(Windows) 사용자를 위한 안내 (WSL2)

이 프로젝트는 리눅스 및 유닉스 계열 기능을 사용하므로, 윈도우 환경에서는 **WSL2 (Windows Subsystem for Linux)**를 통한 설치가 필수적입니다.

### 1단계: WSL2 설치 및 리눅스 배포판 설정
1. **PowerShell**을 관리자 권한으로 실행하고 다음 명령어를 입력합니다:
   ```powershell
   wsl --install
   ```
2. 설치 완료 후 컴퓨터를 재부팅합니다.
3. 재부팅 후 자동으로 실행되는 Ubuntu 터미널에서 사용자 이름과 비밀번호를 설정합니다.

### 2단계: 리눅스 환경 개발 도구 설치
Ubuntu 터미널(WSL)에서 아래 명령어를 순서대로 실행합니다:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git python3 python3-venv python3-pip
```

### 3단계: 이후 과정
위 설정이 완료되었다면 아래의 **[Ubuntu 서버 기준 시작하기]** 가이드를 그대로 따라서 설치를 진행하시면 됩니다.

---

## 🚀 Ubuntu 서버 기준 시작하기

- Ubuntu 22.04 이상 (권장)
- Python 3.10 이상
- Node.js 20 이상
- Telegram Bot Token ([BotFather](https://t.me/botfather)를 통해 발급)
- 본인의 텔레그램 User ID

### 2. 설치 및 설정

```bash
# 1. 저장소 클론
git clone https://github.com/GNchoo/OpenGemini.git
cd OpenGemini

# 2. 가상 환경 설정 및 의존성 설치
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. CLI 도구 설치 (필요시)
npm install -g @google/gemini-cli
# claude-code 설치 (별도 가이드 참고)
```

### 3. 환경 변수 설정 (`.env`)

`.env.template` 파일을 복사하여 `.env` 파일을 생성하고 본인의 정보를 입력합니다.

```env
TELEGRAM_TOKEN=여러분의_토큰
ALLOWED_USER_ID=여러분의_ID
GEMINI_BIN=/usr/local/bin/gemini         # which gemini로 확인
CLAUDE_BIN=/home/user/.npm-global/bin/claude  # which claude로 확인
GEMINI_WORKDIR=/home/user/OpenGemini/workspace
DEFAULT_ENGINE=gemini
```

---

## 🛠 실행 및 운영

### 봇 시작하기
```bash
bash start_bot.sh
```

### 백그라운드 상시 가동 (systemd 예시)
`~/.config/systemd/user/opengemini.service` 파일을 생성하여 등록하면 서버 재부팅 후에도 자동으로 실행됩니다.

---

## 🤖 봇 명령어 가이드

- `/start` : 봇 시작 및 인사
- `/status` : 현재 엔진, 모델, 세션 정보 확인
- `/engine` : Gemini ↔ Claude 엔진 전환 (버튼형)
- `/model` : 최신 모델 선택 (버튼형)
- `/mode [yolo|plan|default]` : 승인 모드 변경 (YOLO 권장)
- `/workspace [path]` : 현재 작업 디렉토리 변경
- `/new` : 대화 세션 초기화 (새 대화 시작)
- `/coding` : 코딩 전용 모드 활성화

---

## 🔒 보안 및 주의사항

- **.env 파일 금지**: API 키와 개인 정보가 포함된 `.env` 파일은 절대 Git에 커밋하지 마세요.
- **사용자 제한**: `ALLOWED_USER_ID`를 설정하여 본인만 봇을 사용할 수 있도록 관리하세요.
- **로그 정기 삭제**: 작업 로그가 쌓일 수 있으므로 필요 시 정리해 주세요.

---

## 라이선스
본 프로젝트는 개인 및 내부 개발 공용 목적으로 설계되었습니다. 상세 라이선스 정책은 추후 업데이트 예정입니다.
