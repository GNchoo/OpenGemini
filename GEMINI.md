# GEMINI.md - 통합 AI 에이전트 작업 컨텍스트

이 파일은 이 시스템(OpenGemini, CoinTrader, StockTrader) 환경에서 Gemini CLI가 효과적으로 작업을 수행하기 위한 핵심 지침서입니다.

## 🌟 시스템 개요 (System Overview)
이 환경은 AI 에이전트(OpenGemini)가 주식 및 코인 자동 매매 시스템을 관리하고, 사용자에게 텔레그램 인터페이스를 제공하며, 다양한 개발 작업을 수행하는 통합 자동화 플랫폼입니다.

---

## 📁 주요 프로젝트 및 경로 (Key Projects & Paths)

### 1. OpenGemini (에이전트 플랫폼)
- **경로**: `/home/fallman/tools/OpenGemini`
- **역할**: Telegram Bot을 통해 AI 에이전트(Gemini, Claude) 인터페이스 제공.
- **핵심 파일**: `bot.py` (메인 엔진), `workspace/` (파일 작업 공간).
- **특징**: 워크스페이스 내 파일 생성 시 텔레그램으로 자동 업로드됨.

### 2. CoinTrader (코인 자동 매매)
- **경로**: `/home/fallman/projects/CoinTrader`
- **역할**: Upbit API 기반 24시간 코인 자동 매매 시스템.
- **기술 스택**: Python, WebSocket, AI 신호 합의 알고리즘.
- **핵심 파일**: `auto_trader.py` (엔진), `ai_signal_engine.py` (AI 신호), `dash.py` (대시보드).
- **운영**: `trader-autotrader.service` (systemd)로 관리됨.

### 3. StockTrader (주식 자동 매매)
- **경로**: `/home/fallman/projects/StockTrader`
- **역할**: 한국투자증권(KIS) API 기반 주식 자동 매매 시스템.
- **기술 스택**: Python, KIS API, SQLite, 기술적 분석 지표.
- **핵심 파일**: `app/main.py` (엔진), `app/execution/kis_broker.py` (브로커 연동).
- **운영**: 한국 시장 시간(09:00~15:30)에 맞춰 작동.

---

## ⚙️ 에이전트 운영 가이드라인 (Operational Guidelines)

### 1. 작업 범위 및 권한
- 에이전트는 `/home/fallman/tools/` 및 `/home/fallman/projects/` 하위의 모든 프로젝트에 대해 읽기/쓰기 및 실행 권한을 가집니다.
- **주의**: 주식/코인 매매 로직 수정 시에는 반드시 백업(`*.bak`)을 생성하고 테스트를 선행해야 합니다.

### 2. 워크스페이스 활용
- 사용자에게 결과물(HTML 게임, 리포트 등)을 전달할 때는 반드시 `/home/fallman/tools/OpenGemini/workspace/` 경로에 저장하여 자동 업로드 기능을 활용합니다.

### 3. 트레이딩 시스템 대응
- **Coin bot** 질문 시: `/home/fallman/projects/CoinTrader` 내부를 분석합니다.
- **Stock bot** 질문 시: `/home/fallman/projects/StockTrader` 내부를 분석합니다.
- 각 프로젝트의 `requirements.txt` 및 가상환경(`venv`, `trader_env`) 위치를 확인하여 명령어를 실행합니다.

### 4. 보안 및 안전 (Security & Safety)
- `.env` 파일에 포함된 API Key (Upbit, KIS, Telegram) 및 개인 식별 정보를 절대 외부로 노출하거나 로그에 남기지 않습니다.
- 실제 주문 로직(`live` 모드) 수정 시에는 `paper` 모드(모의 투자) 테스트를 거쳐야 합니다.

---

## 🛠 주요 명령어 및 도구 (Tools & Commands)
- **Python**: 가상환경 활성화 후 실행 (`source [venv]/bin/activate`)
- **Systemd**: 서비스 상태 확인 (`systemctl --user status [service]`)
- **Git**: 각 프로젝트 폴더에서 독립적으로 관리.

## 🧪 테스트 및 검증
- 신규 기능 추가 시 각 프로젝트의 `tests/` 디렉토리에 있는 테스트 코드를 실행하여 회귀 테스트를 수행합니다.

---
**최종 갱신**: 2026-03-04 (통합 프로젝트 컨텍스트 반영)
