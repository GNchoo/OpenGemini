# StockTrader - 순수 주식 트레이딩 시스템

## 📈 시스템 개요

**순수 주식 전용 트레이딩 시스템**입니다. 코인 트레이더 코드와 완전히 분리되었습니다.

## 🎯 특징

- **한국투자증권(KIS) 전용** (주식만 거래)
- **장시간 자동 트레이딩** (09:00-15:30)
- **기술적 분석 기반 의사결정**
- **실시간 시세 데이터**
- **종목 매핑 및 감성 분석**

## 🏗️ 아키텍처

### 주요 모듈
- `app/main.py` - 메인 트레이딩 엔진
- `app/execution/kis_broker.py` - KIS API 브로커
- `app/signal/decision.py` - 신호 의사결정
- `app/risk/engine.py` - 리스크 관리 엔진
- `app/nlp/ticker_mapper.py` - 종목 매핑

### 지원 기능
- **실시간 주문/체결**
- **포트폴리오 관리**
- **리스크 노출 제어**
- **자동 청산 트리거**
- **성과 보고**

## 🚀 시작하기

### 1. 환경 설정
```bash
# 가상환경 생성
python3 -m venv stock_env
source stock_env/bin/activate
pip install -r requirements.txt
```

### 2. KIS API 설정
`.env` 파일 생성:
```env
# KIS API 키
KIS_APP_KEY=your_app_key
KIS_APP_SECRET=your_app_secret
KIS_CANO=your_cano
KIS_ACNT_PRDT_CD=your_acnt_prdt_cd

# 트레이딩 설정
INITIAL_CAPITAL=10000000
RISK_PER_TRADE=0.02
STOP_LOSS_PERCENT=0.05
TAKE_PROFIT_PERCENT=0.10
```

### 3. 실행
```bash
# 테스트 모드 (종이 거래)
python app/main.py --mode=paper

# 실전 모드 (실제 거래)
python app/main.py --mode=live
```

## 📊 트레이딩 전략

### 기본 전략
1. **기술적 지표 분석** (RSI, MACD, 이동평균)
2. **시장 상황 적응**
3. **리스크 기반 포지션 사이징**

### 프로파일 시스템
- **CONSERVATIVE**: 보수적 (장기 투자)
- **BALANCED**: 균형적 (스윙 트레이딩) 
- **AGGRESSIVE**: 공격적 (단기 매매)

## 🔧 모니터링

### 건강 상태 체크
```bash
./scripts/healthcheck.sh
```

### 일일 리포트
```bash
./scripts/daily_report.sh
```

## 📈 성과 추적

### 데이터베이스
- SQLite 기반 거래 기록
- 포트폴리오 추적
- 성과 메트릭 계산

### 리포트
- 일일/주간/월간 리포트
- 위험 노출 분석
- 수익률 비교

## ⚠️ 주의사항

### 코인 시스템과의 분리
- 이 시스템은 **코인 트레이더와 완전히 분리됨**
- 별도 저장소: https://github.com/GNchoo/CoinTrader
- 별도 실행 환경, 별도 설정 파일

### 시장 시간
- **거래 시간**: 09:00 ~ 15:30
- **점심 시간**: 11:30 ~ 12:30 (거래 중지)
- 주말/공휴일 거래 없음

### API 제한
- KIS API 호출 제한 준수
- 실시간 시세 구독 관리
- 오류 처리 및 재시도

### 리스크 관리
- 일일 손실 한도
- 종목별 노출 제한
- 시장 변동성 대응

## 🔄 개발 가이드

### 테스트 실행
```bash
# 단위 테스트
python -m pytest tests/

# 통합 테스트
python -m pytest tests/test_main_flow.py
```

### 코드 구조
```
app/
├── execution/     # 주문 실행 모듈
├── signal/        # 신호 생성 모듈
├── risk/          # 리스크 관리 모듈
├── ingestion/     # 데이터 수집
├── scheduler/     # 스케줄링
└── storage/       # 데이터 저장
```

## 📞 문제 해결

### 일반적인 문제
1. **API 연결 실패**: API 키 확인, 네트워크 확인
2. **주문 실패**: 시장 시간 확인, 잔고 확인
3. **데이터 동기화 실패**: DB 연결 확인

### 로그 확인
```bash
# 에러 로그 확인
tail -f logs/error.log

# 트레이딩 로그 확인
tail -f logs/trading.log
```

## 🔗 관련 프로젝트

- **CoinTrader**: 코인 전용 트레이딩 시스템
- **공통 라이브러리**: 향후 추출 예정

---
**버전**: 1.0 (순수 주식 전용)  
**최근 업데이트**: 2026-03-03  
**상태**: 개발/테스트 중