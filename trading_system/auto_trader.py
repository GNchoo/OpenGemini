#!/usr/bin/env python3
"""
트레이더 마크 📊 - 자동 주문 실행 시스템
WebSocket 실시간 수신 → AI 합의 → 자동 주문
"""

import os
import json
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional
import math
import subprocess

from upbit_live_client import UpbitLiveClient
from ai_signal_engine  import AISignalEngine
from volatility_monitor import (
    VolatilityCalculator, EmergencyStopManager, THRESHOLDS
)
from websocket_client import get_client, TickerData
from exchange_maintenance import check_upbit_status, is_maintenance_time

try:
    from telegram_notifier import send_alert as telegram_send_alert
    TELEGRAM_AVAILABLE = True
except Exception:
    TELEGRAM_AVAILABLE = False


# ─────────────────────────────────────────────────────────────
# 리스크 설정
# ─────────────────────────────────────────────────────────────
RISK_CONFIG = {
    "AGGRESSIVE":    {"position_pct": 0.010, "stop_loss": 0.020, "take_profit": 0.030},
    "MODERATE":      {"position_pct": 0.005, "stop_loss": 0.015, "take_profit": 0.025},
    "CONSERVATIVE":  {"position_pct": 0.002, "stop_loss": 0.010, "take_profit": 0.020},
    "EMERGENCY_STOP":{"position_pct": 0.000, "stop_loss": 0.000, "take_profit": 0.000},
}

MIN_ORDER_KRW = 5_000          # 업비트 최소 주문금액
MIN_ORDER_BUFFER_KRW = 700      # 매수 최소주문 버퍼 (수수료/슬리피지 여유)
MIN_SAFE_ORDER_KRW = MIN_ORDER_KRW + MIN_ORDER_BUFFER_KRW
MIN_SELL_ORDER_KRW = MIN_ORDER_KRW  # 매도는 거래소 최소만 적용(소액계좌 대응)
FEE_RATE = 0.0005               # 업비트 0.05%
ROUND_TRIP_FEE = FEE_RATE * 2   # 왕복 수수료 0.10%
MAX_DAILY_LOSS_PCT = 0.05       # 일일 최대 손실 5%
PROFILE_FILE = Path(__file__).parent / 'trading_profile.json'
LIVE_TRADE_LOG_FILE = Path(__file__).parent / 'live_trade_log.json'
WS_HEALTH_FILE = Path(__file__).parent / 'ws_health.json'
AI_STATUS_FILE = Path(__file__).parent / 'ai_status_live.json'
BASELINE_FILE = Path(__file__).parent / 'live_baseline.json'
TRADE_LOG_MAX_ITEMS = 5000  # 거래 로그 보존 개수(기존 500 → 손절/익절 이력 보존 강화)
PROFILE_CONFIG = {
    'SAFE': {'risk_scale': 0.6, 'min_conf': 0.72, 'scalp_take_profit': None, 'max_order_ratio': 0.60, 'ai_sell_min_hold_sec': 1200, 'min_net_profit_krw': 200, 'auto_stoploss_time_sec': 7200, 'auto_stoploss_threshold_pct': -0.02, 'signal_interval_sec': 5, 'same_signal_cooldown_sec': 20},
    'BALANCED': {'risk_scale': 1.0, 'min_conf': 0.65, 'scalp_take_profit': None, 'max_order_ratio': 0.60, 'ai_sell_min_hold_sec': 900, 'min_net_profit_krw': 150, 'auto_stoploss_time_sec': 7200, 'auto_stoploss_threshold_pct': -0.02, 'signal_interval_sec': 5, 'same_signal_cooldown_sec': 20},
    'AGGRESSIVE': {'risk_scale': 1.4, 'min_conf': 0.60, 'scalp_take_profit': None, 'max_order_ratio': 0.60, 'ai_sell_min_hold_sec': 600, 'min_net_profit_krw': 100, 'auto_stoploss_time_sec': 7200, 'auto_stoploss_threshold_pct': -0.02, 'signal_interval_sec': 5, 'same_signal_cooldown_sec': 20},
    # Freqtrade 스캘핑 전략 참고: 빠른 익절, 적절한 보유시간
    'SCALP': {
        'risk_scale': 1.0,
        'min_conf': 0.65,  # 65% (과도한 필터링 방지)
        'scalp_take_profit': 0.0050,  # 0.5% (수수료 제외 0.4% 순이익)
        'scalp_trail_arm': 0.0030,  # 0.3%
        'scalp_trail_gap': 0.0020,  # 0.2%
        'scalp_time_exit_min': 15,  # 15분 (Freqtrade 평균)
        'max_order_ratio': 0.60,
        'ai_sell_min_hold_sec': 180,  # 3분 (과도한 회전 방지)
        'min_net_profit_krw': 50,
        'auto_stoploss_time_sec': 3600,  # 1시간 경과 + -1.5% 이하면 손절
        'auto_stoploss_threshold_pct': -0.015,
        'scalp_break_even_exit_sec': 1800,   # 30분 경과 후 본전 이하면 정리
        'scalp_break_even_buffer_pct': -0.0015,  # -0.15% 이하이면 정리
        'scalp_hard_max_hold_sec': 5400,     # 90분 강제 리스크 정리
        'scalp_hard_max_loss_pct': -0.006,   # -0.6% 이상 손실이면 강제 청산
        'signal_interval_sec': 3,
        'same_signal_cooldown_sec': 15,
    },
    # Jesse/Freqtrade 참고: 리스크/리워드 2:1, 적절한 보유시간
    'ALL_IN': {
        'risk_scale': 1.0,
        'min_conf': 0.75,  # 75% (경계 신호 진입 축소)
        'buy_confirmations': 3,  # 동일 방향 BUY 신호 3회 연속 확인 후 진입
        'scalp_take_profit': None,
        'max_order_ratio': 0.98,
        'max_symbol_cap_ratio': 1/3,
        'ai_sell_min_hold_sec': 600,  # 10분 (수수료 회수 + 추세 확인)
        'min_net_profit_krw': 100,  # 100원 (수수료의 12배, 안전 마진)
        'risk_reward_ratio': 2.0,  # 손실 1 : 수익 2 (Jesse 권장)
        'auto_stoploss_time_sec': 7200,  # 2시간 (기회비용 고려)
        'auto_stoploss_threshold_pct': -0.02,  # -2% (손실 허용 범위)
        'signal_interval_sec': 5,
        'same_signal_cooldown_sec': 20,
    },
}


class Position:
    """보유 포지션"""

    def __init__(self, symbol: str, entry_price: float,
                 volume: float, strategy: str):
        self.symbol      = symbol
        self.entry_price = entry_price
        self.volume      = volume
        self.strategy    = strategy
        self.opened_at   = datetime.now()
        self.order_uuid  = None
        self.high_watermark = entry_price

        cfg = RISK_CONFIG.get(strategy, RISK_CONFIG["MODERATE"])
        self.stop_loss   = entry_price * (1 - cfg["stop_loss"])
        self.take_profit = entry_price * (1 + cfg["take_profit"])

    def pnl(self, current_price: float) -> float:
        return (current_price - self.entry_price) / self.entry_price

    def should_close(self, current_price: float) -> Optional[str]:
        """청산 여부 판단"""
        if current_price <= self.stop_loss:
            return "STOP_LOSS"
        if current_price >= self.take_profit:
            return "TAKE_PROFIT"
        return None

    def __repr__(self):
        return (f"Position({self.symbol} "
                f"entry={self.entry_price:,.0f} "
                f"vol={self.volume:.6f} "
                f"SL={self.stop_loss:,.0f} "
                f"TP={self.take_profit:,.0f})")


class AutoTrader:
    """
    자동 트레이딩 시스템
    WebSocket → 변동성 → AI → 주문
    """

    def __init__(self, symbols: list = None, paper_mode: bool = True, ws_simulate: Optional[bool] = None):
        """
        paper_mode=True  : 모의 거래 (실제 주문 X, 로그만)
        paper_mode=False : 실제 주문 (소액 테스트 권장)
        """
        self.symbols    = symbols or ["KRW-BTC", "KRW-ETH"]
        self.paper_mode = paper_mode

        # 서브 모듈
        self.upbit     = UpbitLiveClient(account=os.getenv("TRADING_ACCOUNT", "B"))
        self.ai        = AISignalEngine()
        self.vol_calc  = VolatilityCalculator()
        self.emergency = EmergencyStopManager()
        if ws_simulate is None:
            ws_simulate = paper_mode
        self.ws        = get_client(self.symbols, simulate=ws_simulate)
        
        # 가격 업데이트 모니터링
        self.last_price_update = {sym: time.time() for sym in self.symbols}
        self.last_ws_tick_at = 0.0
        self.last_rest_fallback_at = 0.0
        self.rest_fallback_count = 0
        self.rest_fallback_events: list[float] = []
        self.health_last_write = 0.0
        self.ai_status_last_write = 0.0
        self.last_decisions: dict[str, dict] = {}
        self.order_block_until: dict[str, float] = {}

        # 상태
        self.running          = False
        self.current_strategy = "MODERATE"
        self.positions:  dict[str, Position] = {}
        self.daily_pnl   = 0.0
        self.daily_trades = 0
        self._lock       = threading.Lock()

        # 성과 기록
        self.trade_log: list[dict] = []
        self.signal_log: list[dict] = []
        self.consecutive_losses = 0
        self.consecutive_wins = 0
        self.slippage_records: list[dict] = []
        self.pending_orders: dict[str, dict] = {}  # uuid -> {symbol, type, price, volume, timestamp}
        self.last_sell_price: dict[str, float] = {}  # 심볼별 마지막 매도가 (재진입 방지)
        self.last_sell_time: dict[str, float] = {}  # 심볼별 마지막 매도 시각
        self.last_signal_eval_at: dict[str, float] = {}
        self.last_signal_key_at: dict[str, float] = {}
        self.buy_signal_streak: dict[str, int] = {}
        self._load_live_trade_log()

        self.profile_name = 'BALANCED'
        self.profile = PROFILE_CONFIG['BALANCED']
        self.last_profile_check = 0.0
        self.last_autotune_check = 0.0
        self.load_profile(force=True)

        mode_str = "📝 모의거래 (Paper)" if paper_mode else "💰 실제거래 (Live)"
        print("=" * 70)
        print(f"트레이더 마크 📊 - 자동 트레이딩 시스템 [{mode_str}]")
        print("=" * 70)
        print(f"심볼: {', '.join(self.symbols)}")
        print(f"모드: {mode_str}")
        print(f"리스크: {RISK_CONFIG}")
        print()

    def get_current_price(self, symbol: str, fallback_price: float = None) -> float:
        """
        현재가 조회 (WebSocket → REST API fallback)
        
        Args:
            symbol: 심볼 (e.g., KRW-BTC)
            fallback_price: 최후 fallback 가격 (진입가 등)
        
        Returns:
            현재가 (float)
        """
        # 1차: WebSocket에서 가져오기
        ws_price = self.ws.get_price(symbol)
        if ws_price and ws_price > 0:
            self.last_price_update[symbol] = time.time()
            return ws_price
        
        # 2차: REST API fallback
        try:
            tickers = self.upbit.get_ticker([symbol])
            if tickers and len(tickers) > 0:
                rest_price = float(tickers[0].get('trade_price', 0))
                if rest_price > 0:
                    now_ts = time.time()
                    print(f"  ⚠️ WebSocket 시세 없음 → REST API 사용: {symbol} {rest_price:,.0f}원")
                    self.last_price_update[symbol] = now_ts
                    self.last_rest_fallback_at = now_ts
                    self.rest_fallback_count += 1
                    self.rest_fallback_events.append(now_ts)
                    # 최근 5분 이벤트만 유지
                    cutoff = now_ts - 300
                    self.rest_fallback_events = [x for x in self.rest_fallback_events if x >= cutoff]
                    return rest_price
        except Exception as e:
            print(f"  ❌ REST API 조회 실패: {symbol} - {e}")
        
        # 3차: fallback_price 사용 (경고)
        if fallback_price and fallback_price > 0:
            elapsed = time.time() - self.last_price_update.get(symbol, 0)
            print(f"  🚨 시세 조회 실패! fallback 사용: {symbol} {fallback_price:,.0f}원 (마지막 업데이트: {elapsed:.0f}초 전)")
            return fallback_price
        
        raise ValueError(f"현재가 조회 실패: {symbol}")

    def write_health_snapshot(self, force: bool = False):
        """헬스 상태를 파일로 기록 (헬스체크 스크립트에서 사용)."""
        now_ts = time.time()
        if not force and (now_ts - self.health_last_write) < 2.0:
            return
        self.health_last_write = now_ts

        # 최근 60초 REST fallback 횟수
        cutoff_60 = now_ts - 60
        recent_fallback_1m = sum(1 for t in self.rest_fallback_events if t >= cutoff_60)

        payload = {
            "ts": now_ts,
            "ws_connected": bool(getattr(self.ws, "connected", False)),
            "last_ws_tick_at": self.last_ws_tick_at,
            "last_rest_fallback_at": self.last_rest_fallback_at,
            "rest_fallback_count_total": self.rest_fallback_count,
            "rest_fallback_count_1m": recent_fallback_1m,
            "positions": list(self.positions.keys()),
            "current_strategy": self.current_strategy,
            "profile": self.profile_name,
        }
        try:
            WS_HEALTH_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def write_ai_status_snapshot(self, force: bool = False):
        """대시보드에서 바로 읽는 AI 상태 스냅샷 기록."""
        now_ts = time.time()
        if not force and (now_ts - self.ai_status_last_write) < 0.5:
            return
        self.ai_status_last_write = now_ts

        payload = {
            "ts": now_ts,
            "profile": self.profile_name,
            "current_strategy": self.current_strategy,
            "symbols": self.last_decisions,
        }
        try:
            AI_STATUS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def load_profile(self, force: bool = False):
        now = time.time()
        if not force and now - self.last_profile_check < 5:
            return
        self.last_profile_check = now
        try:
            if PROFILE_FILE.exists():
                raw = json.loads(PROFILE_FILE.read_text(encoding='utf-8'))
                name = str(raw.get('profile', 'BALANCED')).upper()
                if name not in PROFILE_CONFIG:
                    return

                base = dict(PROFILE_CONFIG[name])
                overrides = (raw.get('overrides') or {}).get(name, {})
                for k, v in overrides.items():
                    if k in base and isinstance(v, (int, float)):
                        base[k] = v

                changed_name = (name != self.profile_name)
                changed_profile = (base != self.profile)
                self.profile_name = name
                self.profile = base

                if changed_name or changed_profile:
                    scalp_txt = f", scalp_tp {self.profile['scalp_take_profit']*100:.2f}%" if self.profile.get('scalp_take_profit') else ""
                    mr = float(self.profile.get('max_order_ratio', 0.60))
                    self._log(f"🎛️ 투자방식 적용: {name} (risk x{self.profile['risk_scale']}, conf {self.profile['min_conf']:.2f}, max_order {mr*100:.0f}%{scalp_txt})")
        except Exception:
            pass

    # ── 계좌 확인 ───────────────────────────────────────────
    def check_account(self) -> dict:
        """계좌 상태 확인"""
        try:
            portfolio = self.upbit.get_portfolio()
            krw = portfolio.get("KRW", {}).get("balance", 0)
            total = sum(v.get("value_krw", 0) for v in portfolio.values())

            print(f"💰 계좌 상태:")
            print(f"   KRW 잔고: {krw:,.0f}원")
            print(f"   총 평가: {total:,.0f}원")

            for currency, data in portfolio.items():
                if currency != "KRW":
                    pnl = data.get("profit_pct", 0)
                    icon = "🟢" if pnl >= 0 else "🔴"
                    print(f"   {icon} {currency}: {data['balance']:.6f} "
                          f"({data.get('value_krw',0):,.0f}원, {pnl:+.2%})")

            return portfolio

        except Exception as e:
            print(f"   ⚠️ 계좌 조회 실패: {e}")
            print(f"   (잔고 없음 또는 네트워크 오류)")
            return {"KRW": {"balance": 0, "value_krw": 0}}

    def _load_initial_capital(self) -> float:
        try:
            if BASELINE_FILE.exists():
                raw = json.loads(BASELINE_FILE.read_text(encoding='utf-8'))
                return float(raw.get('initial_capital', 0) or 0)
        except Exception:
            pass
        return 0.0

    def _get_account_summary(self) -> tuple[float, float, float]:
        """(총자산, 기준자산, 수익률) 반환"""
        total = 0.0
        baseline = self._load_initial_capital()
        try:
            pf = self.upbit.get_portfolio()
            total = float(sum((v.get('value_krw', 0) or 0) for v in pf.values()) or 0)
        except Exception:
            total = 0.0
        rate = ((total - baseline) / baseline) if baseline > 0 else 0.0
        return total, baseline, rate

    def _get_position_strategy(self) -> str:
        """
        Position 생성 시 사용할 전략 결정
        프로필 우선, 동적 전략은 참고용
        """
        # ALL_IN/SCALP은 고정 MODERATE 전략 (Position 손익절 미사용)
        if self.profile_name in ('ALL_IN', 'SCALP'):
            return 'MODERATE'
        
        # 일반 프로필은 현재 변동성 기반 전략 사용
        return self.current_strategy
    
    def sync_existing_positions(self):
        """계좌에 이미 있는 포지션을 내부 상태에 복원 (재시작 후 관리/청산 가능)."""
        try:
            pf = self.upbit.get_portfolio()
            for symbol in self.symbols:
                coin = symbol.split('-')[1]
                asset = pf.get(coin)
                if not asset:
                    continue
                vol = float(asset.get('balance', 0) or 0)
                avg = float(asset.get('avg_price', 0) or 0)
                value_krw = float(asset.get('value_krw', 0) or (vol * avg))
                if vol <= 0 or avg <= 0:
                    continue
                # 거래소 최소주문 미만의 먼지 잔고는 포지션으로 간주하지 않음
                if value_krw < MIN_ORDER_KRW:
                    continue
                if symbol in self.positions:
                    continue
                
                # Profile 기반으로 Position 생성 (동적 전략 아님)
                pos = Position(symbol, avg, vol, self._get_position_strategy())
                
                # 실제 매수 시간 복구 (로컬 거래 로그 우선, 그 다음 업비트 API)
                opened_at_found = False
                
                # 1차: 로컬 거래 로그에서 찾기
                try:
                    if LIVE_TRADE_LOG_FILE.exists():
                        trade_log = json.loads(LIVE_TRADE_LOG_FILE.read_text(encoding='utf-8'))
                        if isinstance(trade_log, list):
                            # 최근 거래부터 역순 탐색
                            for trade in reversed(trade_log):
                                if trade.get('symbol') == symbol and trade.get('side') == 'BUY':
                                    trade_date = trade.get('date', '')
                                    if trade_date:
                                        dt = datetime.fromisoformat(trade_date.replace('Z', '+00:00'))
                                        pos.opened_at = dt
                                        hold_time = (datetime.now(dt.tzinfo) - dt).total_seconds()
                                        self._log(f"🔁 기존 포지션 복원: {symbol} {vol:.8f} @ {avg:,.0f} (보유: {hold_time/60:.0f}분)")
                                        opened_at_found = True
                                        break
                except Exception as e:
                    self._log(f"⚠️ {symbol} 로컬 로그 조회 실패: {e}")
                
                # 2차: 업비트 API에서 찾기
                if not opened_at_found:
                    try:
                        orders = self.upbit.get_orders(state='done', market=symbol)
                        for order in orders[:200]:  # 최근 200개 주문 확인
                            if order.get('side') == 'bid':  # 매수
                                created_at = order.get('created_at', '')
                                if created_at:
                                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                                    pos.opened_at = dt
                                    hold_time = (datetime.now(dt.tzinfo) - dt).total_seconds()
                                    self._log(f"🔁 기존 포지션 복원: {symbol} {vol:.8f} @ {avg:,.0f} (보유: {hold_time/60:.0f}분)")
                                    opened_at_found = True
                                    break
                    except Exception as e:
                        self._log(f"⚠️ {symbol} API 매수시간 조회 실패: {e}")
                
                # 3차: 찾지 못한 경우 현재 시간 사용 (경고)
                if not opened_at_found:
                    self._log(f"🔁 기존 포지션 복원: {symbol} {vol:.8f} @ {avg:,.0f} (⚠️ 매수시간 미확인 - 즉시 매도 가능)")
                
                self.positions[symbol] = pos
        except Exception as e:
            self._log(f"⚠️ 기존 포지션 복원 실패: {e}")

    def is_price_fresh(self, symbol: str, max_age_sec: float = 15.0) -> tuple[bool, float]:
        """주문 직전 가격 freshness 체크."""
        last = float(self.last_price_update.get(symbol, 0) or 0)
        if last <= 0:
            return (False, 999999.0)
        age = time.time() - last
        return (age <= max_age_sec, age)

    # ── 주문 실행 ───────────────────────────────────────────
    def execute_buy(self, symbol: str, price: float) -> bool:
        """매수 실행"""
        with self._lock:
            # 거래소 점검시간 체크
            if not self.paper_mode:
                maintenance, reason = is_maintenance_time()
                if maintenance:
                    self._log(f"⏸️ 점검시간 - 매수 보류: {reason}")
                    return False
            
            # 일일 손실 한도 체크
            if self.daily_pnl < -MAX_DAILY_LOSS_PCT:
                msg = f"일일 손실 한도 도달\nPnL: {self.daily_pnl:+.2%} (한도: -{MAX_DAILY_LOSS_PCT:.2%})\n매수 중단됨"
                self._log(f"🚫 {msg}")
                self._send_alert(msg, priority="critical")
                return False

            if symbol in self.positions:
                return False  # 이미 포지션 있음
            
            # 매도 후 재진입 방지 (3분 쿨다운 + 가격 검증)
            if symbol in self.last_sell_time:
                time_since_sell = time.time() - self.last_sell_time[symbol]
                last_sell = self.last_sell_price.get(symbol, 0)
                
                # 3분 미만이면 차단
                if time_since_sell < 180:  # 3분
                    self._log(f"⏳ BUY 차단 {symbol}: 매도 후 {time_since_sell:.0f}초 경과 (3분 쿨다운)")
                    return False
                
                # 3분 이상이어도, 매도가보다 2% 이상 낮을 때만 재진입 허용
                if last_sell > 0 and price >= last_sell * 0.98:  # 2% 이상 하락 필요
                    discount = (last_sell - price) / last_sell
                    self._log(f"⏳ BUY 차단 {symbol}: 매도가 대비 {discount:+.2%} (2% 이상 하락 필요)")
                    return False

            now_ts = time.time()
            block_until = float(self.order_block_until.get(symbol, 0) or 0)
            if now_ts < block_until:
                wait = block_until - now_ts
                self._log(f"⏳ BUY 쿨다운 {symbol}: {wait:.1f}s 남음")
                return False

            fresh, age = self.is_price_fresh(symbol, max_age_sec=15.0)
            if not fresh:
                self._log(f"🛑 BUY 차단 {symbol}: 시세 stale ({age:.1f}s > 15s)")
                return False

            cfg = RISK_CONFIG.get(self.current_strategy, RISK_CONFIG["MODERATE"])

            try:
                portfolio = self.upbit.get_portfolio()
                krw_balance = float(portfolio.get("KRW", {}).get("balance", 0) or 0)
                total_eval = float(sum(v.get("value_krw", 0) for v in portfolio.values()) or krw_balance)
            except Exception:
                krw_balance = 0
                total_eval = 0

            order_krw = max(krw_balance * cfg["position_pct"] * self.profile["risk_scale"], 0)

            # 프로필별 최대 주문 비율 제한
            max_ratio = float(self.profile.get('max_order_ratio', 0.60))
            max_order = krw_balance * max_ratio

            if self.profile_name == 'ALL_IN' and not self.paper_mode:
                # ALL_IN은 신호 시 가용 KRW 대부분을 사용하되,
                # 코인별 최대 투자금은 총자본의 1/3로 제한
                symbol_cap_ratio = float(self.profile.get('max_symbol_cap_ratio', 1/3))
                symbol_cap_krw = total_eval * symbol_cap_ratio if total_eval > 0 else max_order
                order_krw = min(max_order, symbol_cap_krw)
            else:
                # 일반 프로필은 최소주문 + 버퍼를 강제
                if not self.paper_mode:
                    order_krw = max(order_krw, MIN_SAFE_ORDER_KRW)
                order_krw = min(order_krw, max_order)

            # 연속 손실 시 포지션 축소
            if self.consecutive_losses >= 3:
                reduction = 0.5  # 50% 축소
                original_order = order_krw
                order_krw = order_krw * reduction
                self._log(f"📉 연속 {self.consecutive_losses}패 - 포지션 축소 {original_order:,.0f} → {order_krw:,.0f}원")
            elif self.consecutive_wins >= 2:
                # 연속 2승 시 원복 (이미 정상 크기이므로 추가 작업 불필요)
                pass

            if order_krw < MIN_SAFE_ORDER_KRW:
                self._log(
                    f"⚠️ {symbol} 매수 불가: 주문금액 {order_krw:,.0f}원 < 안전최소 {MIN_SAFE_ORDER_KRW:,}원"
                )
                return False

            volume = order_krw / price

            if self.paper_mode:
                # 모의거래: 기록만
                pos = Position(symbol, price, volume, self._get_position_strategy())
                self.positions[symbol] = pos
                self._log(f"📝 [모의] BUY {symbol} {volume:.6f}개 @ {price:,.0f}원 "
                          f"(총 {order_krw:,.0f}원) SL={pos.stop_loss:,.0f} TP={pos.take_profit:,.0f}")
                self._record_trade("BUY", symbol, price, volume, order_krw, "paper")
                return True
            else:
                # 실제 주문 직전 KRW 잔고 재검증 (슬리피지 방지)
                try:
                    pf_recheck = self.upbit.get_portfolio()
                    krw_avail = float(pf_recheck.get("KRW", {}).get("balance", 0) or 0)
                    # 슬리피지 완충: 가용 잔고의 95%만 사용
                    safe_krw = krw_avail * 0.95
                    final_order_krw = min(order_krw, safe_krw)
                except Exception:
                    final_order_krw = order_krw

                if final_order_krw < MIN_SAFE_ORDER_KRW:
                    self._log(
                        f"⚠️ BUY 스킵 {symbol}: 재검증 후 가용금액 {final_order_krw:,.0f}원 < 최소 {MIN_SAFE_ORDER_KRW:,}원"
                    )
                    return False

                final_volume = final_order_krw / price

                # 실제 주문
                try:
                    result = self.upbit.place_buy_order(
                        market=symbol, price=final_order_krw, order_type="price"
                    )
                    pos = Position(symbol, price, final_volume, self._get_position_strategy())
                    pos.order_uuid = result.get("uuid")
                    self.positions[symbol] = pos
                    
                    # 슬리피지 추적 (주문 후 실제 체결가 조회)
                    try:
                        time.sleep(0.5)  # 체결 대기
                        filled_order = self.upbit.get_order(pos.order_uuid)
                        executed_price = float(filled_order.get('avg_price', price) or price)
                        slippage_pct = (executed_price - price) / price if price > 0 else 0
                        self.slippage_records.append({
                            'timestamp': time.time(),
                            'symbol': symbol,
                            'type': 'BUY',
                            'expected': price,
                            'executed': executed_price,
                            'slippage_pct': slippage_pct
                        })
                        if abs(slippage_pct) > 0.005:  # 0.5% 이상 차이
                            self._log(f"⚠️ 슬리피지 발생: {slippage_pct:+.2%} (예상 {price:,.0f} → 체결 {executed_price:,.0f})")
                    except Exception:
                        pass
                    
                    # 미체결 추적에 추가
                    if pos.order_uuid:
                        self.pending_orders[pos.order_uuid] = {
                            'symbol': symbol,
                            'type': 'BUY',
                            'price': final_order_krw,
                            'volume': final_volume,
                            'timestamp': time.time()
                        }
                    
                    self._log(f"✅ [실거래] BUY {symbol} 주문 완료 uuid={pos.order_uuid}")
                    self._record_trade("BUY", symbol, price, final_volume, final_order_krw, "live")

                    total_asset, baseline, total_rate = self._get_account_summary()
                    buy_msg = (
                        f"🟢 *매수 체결*\n"
                        f"종목: `{symbol}`\n"
                        f"체결가: `{price:,.0f}원`\n"
                        f"수량: `{final_volume:.8f}`\n"
                        f"매수금액: `{final_order_krw:,.0f}원`\n\n"
                        f"💼 *계좌 현황*\n"
                        f"총 자산: `{total_asset:,.0f}원`\n"
                        f"기준 자산: `{baseline:,.0f}원`\n"
                        f"누적 수익률: `{total_rate:+.2%}`"
                    )
                    self._send_alert(buy_msg, priority="normal")

                    self.daily_trades += 1
                    return True
                except Exception as e:
                    emsg = str(e)
                    # API 에러 폭주 방지 백오프
                    if '429' in emsg:
                        self.order_block_until[symbol] = time.time() + 30
                    elif '400' in emsg:
                        self.order_block_until[symbol] = time.time() + 10
                    else:
                        self.order_block_until[symbol] = time.time() + 5
                    self._log(f"❌ BUY 실패 {symbol}: {e} (백오프 적용)")
                    return False

    def execute_sell(self, symbol: str, price: float, reason: str = "") -> bool:
        """매도 실행 (실제 주문)"""
        with self._lock:
            now_ts = time.time()
            block_until = float(self.order_block_until.get(symbol, 0) or 0)
            if now_ts < block_until:
                wait = block_until - now_ts
                self._log(f"⏳ SELL 쿨다운 {symbol}: {wait:.1f}s 남음")
                return False

            fresh, age = self.is_price_fresh(symbol, max_age_sec=15.0)
            if not fresh:
                self._log(f"🛑 SELL 차단 {symbol}: 시세 stale ({age:.1f}s > 15s)")
                return False

            # 통합 매도 조건 체크
            should_sell, final_reason = self.should_sell(symbol, price, reason)
            
            if not should_sell:
                self._log(f"⏸️ 매도 보류 {symbol}: {final_reason}")
                return False
            
            if symbol not in self.positions:
                return False
            
            pos   = self.positions[symbol]
            pnl   = pos.pnl(price)
            value = pos.volume * price
            
            self.daily_pnl += pnl

            if self.paper_mode:
                self._log(f"📝 [모의] SELL {symbol} {pos.volume:.6f}개 @ {price:,.0f}원 "
                          f"PnL {pnl:+.2%} ({reason})")
                self._record_trade("SELL", symbol, price, pos.volume, value, "paper", pnl, reason)
                del self.positions[symbol]
                return True
            else:
                # 매도 직전 실보유수량 재조회(400 Bad Request 방지)
                try:
                    pf = self.upbit.get_portfolio()
                    coin = symbol.split('-')[1]
                    avail = float((pf.get(coin) or {}).get('balance', 0) or 0)
                    sell_volume = min(float(pos.volume), avail)
                except Exception:
                    sell_volume = float(pos.volume)

                if sell_volume <= 0:
                    self._log(f"⚠️ SELL 스킵 {symbol}: 실보유수량 0")
                    return False

                # 매도 가능금액 체크: 거래소 최소주문(5,000원) 기준
                est_gross = sell_volume * price
                est_net = est_gross * (1 - FEE_RATE)
                value = est_gross
                if est_gross < MIN_SELL_ORDER_KRW or est_net < MIN_ORDER_KRW:
                    self._log(
                        f"⚠️ SELL 스킵 {symbol}: 예상체결 {est_gross:,.0f}원(순 {est_net:,.0f}원) "
                        f"< 최소주문 {MIN_SELL_ORDER_KRW:,}원"
                    )
                    return False

                try:
                    result = self.upbit.place_sell_order(
                        market=symbol, volume=sell_volume, order_type="market"
                    )
                    
                    # 연속 손익 추적
                    if pnl > 0:
                        self.consecutive_wins += 1
                        self.consecutive_losses = 0
                    else:
                        self.consecutive_losses += 1
                        self.consecutive_wins = 0
                    
                    buy_cost = pos.entry_price * sell_volume
                    total_fee = (buy_cost + value) * FEE_RATE
                    realized_krw = value - buy_cost - total_fee

                    self._log(f"✅ [실거래] SELL {symbol} 완료 PnL {pnl:+.2%} ({final_reason})")
                    self._record_trade("SELL", symbol, price, sell_volume, value, "live", pnl, final_reason)

                    total_asset, baseline, total_rate = self._get_account_summary()
                    sell_msg = (
                        f"🔵 *매도 체결*\n"
                        f"종목: `{symbol}`\n"
                        f"체결가: `{price:,.0f}원`\n"
                        f"수량: `{sell_volume:.8f}`\n"
                        f"실현손익: `{realized_krw:+,.0f}원`\n"
                        f"거래수익률: `{pnl:+.2%}`\n"
                        f"사유: `{final_reason or 'N/A'}`\n\n"
                        f"💼 *계좌 현황*\n"
                        f"총 자산: `{total_asset:,.0f}원`\n"
                        f"기준 자산: `{baseline:,.0f}원`\n"
                        f"누적 수익률: `{total_rate:+.2%}`"
                    )
                    priority = "warning" if (realized_krw < 0 or self.consecutive_losses >= 3) else "normal"
                    self._send_alert(sell_msg, priority=priority)
                    
                    # 매도가/시각 기록 (재진입 방지용)
                    self.last_sell_price[symbol] = price
                    self.last_sell_time[symbol] = time.time()
                    
                    # pending에서 제거 (BUY 주문 UUID)
                    if symbol in self.positions and self.positions[symbol].order_uuid:
                        self.pending_orders.pop(self.positions[symbol].order_uuid, None)
                    
                    del self.positions[symbol]
                    self.daily_trades += 1
                    return True
                except Exception as e:
                    emsg = str(e)
                    # API 에러 폭주 방지 백오프
                    if '429' in emsg:
                        self.order_block_until[symbol] = time.time() + 30
                    elif '400' in emsg:
                        self.order_block_until[symbol] = time.time() + 10
                    else:
                        self.order_block_until[symbol] = time.time() + 5
                    self._log(f"❌ SELL 실패 {symbol}: {e} (백오프 적용)")
                    return False

    def _load_live_trade_log(self):
        if self.paper_mode:
            return
        try:
            if LIVE_TRADE_LOG_FILE.exists():
                raw = json.loads(LIVE_TRADE_LOG_FILE.read_text(encoding='utf-8'))
                if isinstance(raw, list):
                    self.trade_log = raw[-TRADE_LOG_MAX_ITEMS:]
        except Exception:
            pass

    def _persist_live_trade_log(self):
        if self.paper_mode:
            return
        try:
            LIVE_TRADE_LOG_FILE.write_text(
                json.dumps(self.trade_log[-TRADE_LOG_MAX_ITEMS:], ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
        except Exception as e:
            self._log(f"⚠️ 거래로그 저장 실패: {e}")

    def _record_trade(self, side, symbol, price, volume, value, mode, pnl=0, reason=""):
        est_fee = (value or 0) * FEE_RATE if mode == 'live' else 0
        rec = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "date": datetime.now().isoformat(),
            "side": side,
            "symbol": symbol,
            "price": price,
            "volume": volume,
            "value": value,
            "mode": mode,
            "pnl": pnl,
            "profit": (pnl * value) if side == 'SELL' else 0,
            "total_fee": est_fee,
            "reason": reason,
        }
        self.trade_log.append(rec)
        self._persist_live_trade_log()

    def autotune_scalp_params(self):
        """최근 SCALP 실거래 성과로 익절/트레일 파라미터를 소폭 자동 튜닝."""
        now = time.time()
        if now - self.last_autotune_check < 300:  # 5분마다
            return
        self.last_autotune_check = now

        if self.profile_name != 'SCALP':
            return
        if self.paper_mode:
            return

        try:
            if not PROFILE_FILE.exists():
                return
            raw = json.loads(PROFILE_FILE.read_text(encoding='utf-8'))
            if raw.get('autotune', True) is False:
                return

            recent = []
            for t in self.trade_log[-120:]:
                if t.get('side') != 'SELL':
                    continue
                if not str(t.get('reason', '')).startswith('SCALP'):
                    continue
                try:
                    recent.append(float(t.get('pnl', 0)))
                except Exception:
                    continue
            if len(recent) < 6:
                return

            win_rate = sum(1 for p in recent if p > 0) / len(recent)
            avg_pnl = sum(recent) / len(recent)

            ov = dict((raw.get('overrides') or {}).get('SCALP', {}))
            tp = float(ov.get('scalp_take_profit', self.profile.get('scalp_take_profit', 0.0030)))
            gap = float(ov.get('scalp_trail_gap', self.profile.get('scalp_trail_gap', 0.0015)))
            tmin = int(ov.get('scalp_time_exit_min', self.profile.get('scalp_time_exit_min', 40)))

            changed = False
            if win_rate >= 0.65 and avg_pnl >= 0.0020:
                tp = min(0.0050, tp + 0.0001)
                gap = min(0.0022, gap + 0.00005)
                changed = True
            elif win_rate < 0.45 or avg_pnl < 0:
                tp = max(0.0022, tp - 0.0001)
                gap = max(0.0010, gap - 0.00005)
                tmin = max(20, tmin - 5)
                changed = True

            if changed:
                raw.setdefault('overrides', {})['SCALP'] = {
                    'scalp_take_profit': round(tp, 6),
                    'scalp_trail_gap': round(gap, 6),
                    'scalp_time_exit_min': int(tmin),
                }
                raw['updated_at'] = time.time()
                PROFILE_FILE.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding='utf-8')
                self.load_profile(force=True)
                self._log(f"🧠 SCALP 자동튜닝 반영 (win {win_rate:.0%}, avg {avg_pnl:+.3%})")
        except Exception as e:
            self._log(f"⚠️ SCALP 자동튜닝 오류: {e}")

    # ── 포지션 감시 ─────────────────────────────────────────
    def monitor_positions(self, current_prices: dict):
        """손절/익절 감시 - 프로필별 동작"""
        # ALL_IN/SCALP: Position 기반 손익절 사용 안 함
        if self.profile_name in ('ALL_IN', 'SCALP'):
            return
        
        # 일반 프로필: Position 기반 손익절 감시
        for symbol, pos in list(self.positions.items()):
            price  = self.get_current_price(symbol, pos.entry_price)
            reason = pos.should_close(price)
            if reason:
                self.execute_sell(symbol, price, reason)

    def _calc_volume_trend(self, ticker) -> float:
        """WebSocket ticker의 24시간 거래량과 변화율로 거래량 추세 추정.

        Returns:
            -1.0 ~ +1.0 범위의 거래량 추세 값
            양수 = 거래량 증가 추세, 음수 = 거래량 감소 추세
        """
        try:
            change_rate = getattr(ticker, 'change_rate', 0.0) or 0.0
            # 가격 상승 + 양봉 → 거래량 추세 양수 추정
            # 가격 하락 + 음봉 → 거래량 추세 음수 추정
            # 횡보 → 0에 가깝게
            vol_trend = change_rate * 3.0  # 스케일링
            return max(min(vol_trend, 1.0), -1.0)
        except Exception:
            return 0.0

    def _sma(self, arr, n):
        return sum(arr[-n:]) / n if len(arr) >= n else None

    def _rsi(self, arr, period: int = 14):
        if len(arr) < period + 1:
            return None
        gains = 0.0
        losses = 0.0
        for i in range(-period, 0):
            d = arr[i] - arr[i - 1]
            if d > 0:
                gains += d
            else:
                losses -= d
        if losses == 0:
            return 100.0
        rs = (gains / period) / (losses / period)
        return 100 - (100 / (1 + rs))

    def scalp_entry_ok(self, prices, vol, change_rate):
        """Freqtrade류 스캘핑 원칙(짧은 추세 + 과열회피 + 저변동성)을 단순화 적용."""
        ma5 = self._sma(prices, 5)
        ma20 = self._sma(prices, 20)
        if ma5 is None or ma20 is None:
            return False
        rsi = self._rsi(prices, 14)
        if rsi is None:
            return False
        # 1) 단기 상승 추세
        trend_ok = ma5 > ma20
        # 2) 과열 매수 금지
        rsi_ok = 48 <= rsi <= 72
        # 3) 급등 캔들 추격 금지
        spike_ok = abs(change_rate or 0) < 0.006
        # 4) 변동성 과대 구간 회피 (초단타 슬리피지 방지)
        vol_ok = (vol or 0) < 0.03
        return trend_ok and rsi_ok and spike_ok and vol_ok

    def expected_net_profit_krw(self, pos: Position, price: float) -> float:
        """수수료 포함 기대 순이익 (원화)"""
        gross_buy = pos.entry_price * pos.volume
        gross_sell = price * pos.volume
        total_fee = (gross_buy + gross_sell) * FEE_RATE
        return (gross_sell - gross_buy) - total_fee

    def should_sell(self, symbol: str, price: float, reason: str = "") -> tuple[bool, str]:
        """
        통합 매도 결정 함수
        
        Returns:
            (should_sell: bool, final_reason: str)
        """
        if symbol not in self.positions:
            return (False, "NO_POSITION")
        
        pos = self.positions[symbol]
        
        # 1. 비상 상황은 무조건 매도
        if reason == "EMERGENCY":
            return (True, reason)
        
        # 2. 프로필별 매도 로직
        if self.profile_name == 'ALL_IN':
            return self._should_sell_all_in(pos, price, reason)
        elif self.profile_name == 'SCALP':
            return self._should_sell_scalp(pos, price, reason)
        else:
            return self._should_sell_normal(pos, price, reason)
    
    def _should_sell_all_in(self, pos: Position, price: float, reason: str) -> tuple[bool, str]:
        """ALL_IN 프로필 매도 조건"""
        hold_sec = (datetime.now() - pos.opened_at).total_seconds()
        pnl = pos.pnl(price)

        # 시간 기반 자동 손절 (우선순위 최상위)
        auto_stop_time = float(self.profile.get('auto_stoploss_time_sec', 7200))
        auto_stop_threshold = float(self.profile.get('auto_stoploss_threshold_pct', -0.02))
        if hold_sec >= auto_stop_time and pnl <= auto_stop_threshold:
            exp_net = self.expected_net_profit_krw(pos, price)
            return (True, f"AUTO_TIME_STOPLOSS({int(hold_sec/60)}분보유,{pnl*100:.2f}%,{exp_net:.0f}원)")

        # 최소 보유시간 체크
        min_hold = int(self.profile.get('ai_sell_min_hold_sec', 300))
        if hold_sec < min_hold:
            return (False, f"MIN_HOLD({int(hold_sec)}s < {min_hold}s)")

        # 최소 수익률 조건 (기본 0.25%)
        min_profit_pct = float(self.profile.get('all_in_min_profit_pct', 0.0025))
        if pnl < min_profit_pct:
            return (False, f"MIN_PROFIT_PCT({pnl*100:.2f}% < {min_profit_pct*100:.2f}%)")

        # 수수료 포함 순이익 체크
        exp_net = self.expected_net_profit_krw(pos, price)
        min_net = float(self.profile.get('min_net_profit_krw', 30) or 0)
        if exp_net < min_net:
            return (False, f"MIN_NET_PROFIT({exp_net:.1f}원 < {min_net:.1f}원)")

        # 최소 수익률/순이익 충족 후에도 SELL 신호까지 홀드
        if reason != "AI_SIGNAL":
            return (False, f"WAIT_SELL_SIGNAL({reason})")

        return (True, f"ALL_IN_PROFIT({exp_net:.1f}원)")
    
    def _should_sell_scalp(self, pos: Position, price: float, reason: str) -> tuple[bool, str]:
        """SCALP 프로필 매도 조건"""
        pnl = pos.pnl(price)
        hold_sec = (datetime.now() - pos.opened_at).total_seconds()

        # 1) 시간 기반 자동 손절 (기존)
        auto_stop_time = float(self.profile.get('auto_stoploss_time_sec', 3600))
        auto_stop_threshold = float(self.profile.get('auto_stoploss_threshold_pct', -0.015))
        if hold_sec >= auto_stop_time and pnl <= auto_stop_threshold:
            exp_net = self.expected_net_profit_krw(pos, price)
            return (True, f"AUTO_TIME_STOPLOSS({int(hold_sec/60)}분보유,{pnl*100:.2f}%,{exp_net:.0f}원)")

        # 2) 장기 보유 방지: 30분 이상 보유했는데 본전권 미회복이면 정리
        be_exit_sec = int(self.profile.get('scalp_break_even_exit_sec', 1800))
        be_buffer = float(self.profile.get('scalp_break_even_buffer_pct', -0.0015))
        if hold_sec >= be_exit_sec and pnl <= be_buffer:
            exp_net = self.expected_net_profit_krw(pos, price)
            return (True, f"SCALP_TIMEOUT_EXIT({int(hold_sec/60)}분,{pnl*100:.2f}%,{exp_net:.0f}원)")

        # 3) 하드 리스크 컷: 너무 오래 + 손실 확대 시 강제 청산
        hard_max_hold = int(self.profile.get('scalp_hard_max_hold_sec', 5400))
        hard_max_loss = float(self.profile.get('scalp_hard_max_loss_pct', -0.006))
        if hold_sec >= hard_max_hold and pnl <= hard_max_loss:
            exp_net = self.expected_net_profit_krw(pos, price)
            return (True, f"SCALP_HARD_RISK_CUT({int(hold_sec/60)}분,{pnl*100:.2f}%,{exp_net:.0f}원)")

        # 4) SCALP 고유 로직: 익절/트레일/시간청산
        if reason.startswith("SCALP_"):
            # 수수료 제외 순이익 체크
            net_pnl_after_fee = pnl - ROUND_TRIP_FEE
            if net_pnl_after_fee <= 0:
                return (False, f"SCALP_NO_PROFIT({net_pnl_after_fee*100:.2f}%)")
            return (True, reason)

        # 5) AI_SIGNAL 매도
        if reason == "AI_SIGNAL":
            min_hold = int(self.profile.get('ai_sell_min_hold_sec', 30))
            if hold_sec < min_hold:
                return (False, f"SCALP_MIN_HOLD({int(hold_sec)}s)")

            net_pnl_after_fee = pnl - ROUND_TRIP_FEE
            if net_pnl_after_fee <= 0:
                return (False, f"SCALP_FEE_LOSS({net_pnl_after_fee*100:.2f}%)")

            return (True, "SCALP_AI_SIGNAL")

        # Position 기반 손익절은 SCALP에서 사용 안 함
        return (False, "SCALP_NO_CONDITION")
    
    def _should_sell_normal(self, pos: Position, price: float, reason: str) -> tuple[bool, str]:
        """일반 프로필 (SAFE/BALANCED/AGGRESSIVE) 매도 조건"""
        hold_sec = (datetime.now() - pos.opened_at).total_seconds()
        pnl = pos.pnl(price)
        
        # 시간 기반 자동 손절 (우선순위 최상위)
        auto_stop_time = float(self.profile.get('auto_stoploss_time_sec', 7200))
        auto_stop_threshold = float(self.profile.get('auto_stoploss_threshold_pct', -0.02))
        if hold_sec >= auto_stop_time and pnl <= auto_stop_threshold:
            exp_net = self.expected_net_profit_krw(pos, price)
            return (True, f"AUTO_TIME_STOPLOSS({int(hold_sec/60)}분보유,{pnl*100:.2f}%,{exp_net:.0f}원)")
        
        # Position 기반 손익절
        if reason in ("STOP_LOSS", "TAKE_PROFIT"):
            return (True, reason)
        
        # AI_SIGNAL 매도
        if reason == "AI_SIGNAL":
            min_hold = int(self.profile.get('ai_sell_min_hold_sec', 900))
            if hold_sec < min_hold:
                return (False, f"MIN_HOLD({int(hold_sec)}s < {min_hold}s)")
            
            # 최소 순이익 체크 (베스트 프랙티스 적용)
            min_net = float(self.profile.get('min_net_profit_krw', 0) or 0)
            if min_net > 0:
                exp_net = self.expected_net_profit_krw(pos, price)
                if exp_net < min_net:
                    return (False, f"MIN_NET_PROFIT({exp_net:.1f}원 < {min_net:.1f}원)")
            
            return (True, reason)
        
        return (False, "NO_CONDITION")

    def scalp_manage_position(self, symbol, price):
        pos = self.positions.get(symbol)
        if not pos:
            return
        pnl = pos.pnl(price)
        pos.high_watermark = max(pos.high_watermark, price)

        # (A) 수수료를 제하고도 이익일 때만 익절
        tp = self.profile.get('scalp_take_profit')
        net_pnl_after_fee = pnl - ROUND_TRIP_FEE
        if tp is not None and pnl >= tp and net_pnl_after_fee > 0:
            self.execute_sell(symbol, price, f"SCALP_TAKE_{tp*100:.2f}%_NET{net_pnl_after_fee*100:.2f}%")
            return

        trail_arm = float(self.profile.get('scalp_trail_arm', 0.0020))
        trail_gap = float(self.profile.get('scalp_trail_gap', 0.0015))
        time_exit_min = int(self.profile.get('scalp_time_exit_min', 40))

        # (B) 트레일링 보호: trail_arm 도달 후 고점 대비 trail_gap 이탈 시 청산
        if pnl >= trail_arm:
            trail_stop = pos.high_watermark * (1 - trail_gap)
            if price <= trail_stop:
                self.execute_sell(symbol, price, "SCALP_TRAIL")
                return

        # (C) 시간 청산: 일정 시간 경과 + 소폭 이익이면 자금 회전
        hold_min = (datetime.now() - pos.opened_at).total_seconds() / 60
        if hold_min >= time_exit_min and pnl > 0.001:
            self.execute_sell(symbol, price, "SCALP_TIME_EXIT")

    # ── WebSocket 핸들러 ────────────────────────────────────
    def _on_ticker(self, ticker: TickerData):
        symbol = ticker.symbol
        price  = ticker.price
        self.last_ws_tick_at = time.time()
        self.last_price_update[symbol] = self.last_ws_tick_at
        self.write_health_snapshot()

        # 투자방식 파일 반영 (대시보드 버튼 연동)
        self.load_profile()
        self.autotune_scalp_params()

        # 가격 히스토리 업데이트
        prices = self.ws.get_price_history(symbol, 50)
        if len(prices) < 20:
            return

        # 변동성 계산 + 전략 결정
        vol      = self.vol_calc.update(symbol, prices)
        strategy = self.vol_calc.suggest_strategy(vol)

        if strategy != self.current_strategy:
            self._log(f"🔄 전략 전환: {self.current_strategy} → {strategy} "
                      f"(변동성 {vol:.2%})")
            self.current_strategy = strategy

        # 긴급 정지
        emergency = self.emergency.check(
            self.vol_calc.cache,
            abs(min(self.daily_pnl, 0)),
            max(0, -ticker.change_rate),
        )
        if emergency:
            self._log(f"🚨 긴급 정지: {self.emergency.reason}")
            for sym in list(self.positions.keys()):
                self.execute_sell(sym, self.get_current_price(sym, price), "EMERGENCY")
            return

        # 포지션 감시 (손절/익절)
        self.monitor_positions({symbol: price})

        # SCALP 모드: 검증된 초단타 관리(빠른 익절+트레일+시간청산)
        if self.profile_name == 'SCALP' and symbol in self.positions:
            self.scalp_manage_position(symbol, price)

        # AI 신호 (시간 기반 샘플링 + 동일 신호 쿨다운)
        now_ts = time.time()
        signal_interval = float(self.profile.get('signal_interval_sec', 5) or 5)
        same_signal_cooldown = float(self.profile.get('same_signal_cooldown_sec', 20) or 20)

        last_eval = self.last_signal_eval_at.get(symbol, 0.0)
        if now_ts - last_eval < signal_interval:
            return
        self.last_signal_eval_at[symbol] = now_ts

        decision = self.ai.decide(symbol, prices, vol,
                                  volume_trend=self._calc_volume_trend(ticker),
                                  strategy=strategy)

        min_conf = self.profile["min_conf"]
        required_confirms = int(self.profile.get('buy_confirmations', 1) or 1)
        pos = self.positions.get(symbol)
        streak_if_buy = self.buy_signal_streak.get(symbol, 0) + 1 if (
            decision.get("signal") == "BUY" and pos is None and decision.get("confidence", 0) >= min_conf
        ) else 0

        # 대시보드용: 트레이더가 실제로 본 최신 의사결정(지연/불일치 제거)
        self.last_decisions[symbol] = {
            "symbol": symbol,
            "signal": decision.get("signal", "HOLD"),
            "confidence": float(decision.get("confidence", 0) or 0),
            "votes": decision.get("votes", {}),
            "agents": decision.get("agents", []),
            "strategy": strategy,
            "profile": self.profile_name,
            "min_conf": float(min_conf),
            "required_confirms": required_confirms,
            "buy_streak": streak_if_buy,
            "updated_at": now_ts,
        }
        self.write_ai_status_snapshot()

        # 동일 심볼/신호/신뢰도(반올림)가 짧은 시간 내 반복되면 스킵
        signal_key = f"{symbol}:{decision['signal']}:{round(decision['confidence'], 2)}"
        last_same = self.last_signal_key_at.get(signal_key, 0.0)
        if now_ts - last_same < same_signal_cooldown:
            return
        self.last_signal_key_at[signal_key] = now_ts

        self.signal_log.append(decision)

        # 신뢰도 높은 신호만 출력
        if decision["confidence"] >= min_conf:
            print(self.ai.format_decision(decision))

        # 거래 실행
        # 먼지 잔고(최소주문 미만)는 보유 포지션에서 제외해 신규 매수를 막지 않게 처리
        pos = self.positions.get(symbol)
        if pos and (pos.volume * price) < MIN_ORDER_KRW:
            self._log(f"🧹 먼지 포지션 제외 {symbol}: {(pos.volume * price):,.2f}원")
            self.positions.pop(symbol, None)
            pos = None

        required_confirms = int(self.profile.get('buy_confirmations', 1) or 1)
        if decision["signal"] == "BUY" and pos is None and decision["confidence"] >= min_conf:
            # 프로필별 연속 확인 진입(노이즈 완화)
            streak = self.buy_signal_streak.get(symbol, 0) + 1
            self.buy_signal_streak[symbol] = streak
            if streak < required_confirms:
                self._log(f"⏳ BUY 확인 대기 {symbol}: {streak}/{required_confirms}")
                return

            if self.profile_name == 'SCALP' and not self.scalp_entry_ok(prices, vol, ticker.change_rate):
                return

            if self.execute_buy(symbol, price):
                self.buy_signal_streak[symbol] = 0
        elif decision["signal"] == "SELL" and pos is not None and decision["confidence"] >= min_conf:
            # 매도 조건은 should_sell()에서 통합 처리
            self.buy_signal_streak[symbol] = 0
            self.execute_sell(symbol, price, "AI_SIGNAL")
        else:
            # BUY 연속 확인 리셋: 신호 약화/다른 신호/이미 보유 시
            self.buy_signal_streak[symbol] = 0

    # ── 로그 ────────────────────────────────────────────────
    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  [{ts}] {msg}")

    def _systemd_notify(self, msg: str):
        """systemd-notify 호출 (실패해도 무시)."""
        try:
            subprocess.run(["systemd-notify", msg], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def _send_alert(self, message: str, priority: str = "normal"):
        """Telegram 알림 전송 (중요 이벤트만)."""
        if self.paper_mode:
            return  # 모의거래에서는 알림 안 보냄
        
        if not TELEGRAM_AVAILABLE:
            return  # Telegram 모듈 없으면 스킵
        
        try:
            # Telegram으로 실제 전송
            ok = telegram_send_alert(message, priority)
            if not ok:
                self._log("⚠️ Telegram 알림 전송 실패 (토큰/chat_id 설정 확인)")
        except Exception as e:
            self._log(f"⚠️ Telegram 알림 예외: {e}")  # 알림 실패해도 거래는 계속

    def _check_pending_orders(self):
        """미체결 주문 체크 및 자동 취소 (3분 이상 미체결)."""
        if self.paper_mode:
            return
        
        now = time.time()
        to_cancel = []
        
        for uuid, order_info in list(self.pending_orders.items()):
            age = now - order_info['timestamp']
            if age > 180:  # 3분
                to_cancel.append((uuid, order_info))
        
        for uuid, order_info in to_cancel:
            try:
                # 주문 상태 확인
                order = self.upbit.get_order(uuid)
                state = order.get('state', '')
                
                if state in ['wait', 'watch']:  # 미체결
                    self.upbit.cancel_order(uuid)
                    self._log(f"⏰ 미체결 주문 자동 취소: {order_info['symbol']} {order_info['type']} (3분 경과)")
                    self._send_alert(f"미체결 주문 취소\n{order_info['symbol']} {order_info['type']}", priority="warning")
                
                # pending에서 제거
                del self.pending_orders[uuid]
            except Exception as e:
                self._log(f"⚠️ 미체결 주문 체크 실패: {e}")

    # ── 상태 출력 ───────────────────────────────────────────
    def print_status(self, elapsed: float):
        print(f"\n{'─'*70}")
        print(f"  🤖 AutoTrader [{datetime.now().strftime('%H:%M:%S')}] "
              f"경과 {elapsed:.0f}초 | 전략: {self.current_strategy}")
        print(f"{'─'*70}")
        print(f"  일일 PnL: {self.daily_pnl:+.2%} | 거래: {self.daily_trades}회 "
              f"| 신호: {len(self.signal_log)}개")

        if self.positions:
            print(f"  보유 포지션:")
            for sym, pos in self.positions.items():
                price = self.get_current_price(sym, pos.entry_price)
                pnl   = pos.pnl(price)
                icon  = "🟢" if pnl >= 0 else "🔴"
                print(f"    {icon} {sym}: {pnl:+.2%} | "
                      f"진입 {pos.entry_price:,.0f} → 현재 {price:,.0f}")
        else:
            print(f"  보유 포지션: 없음")

        if self.trade_log:
            print(f"  최근 거래:")
            for t in self.trade_log[-3:]:
                pnl_str = f" PnL {t['pnl']:+.2%}" if t["side"] == "SELL" else ""
                print(f"    [{t['time']}] {t['side']} {t['symbol']} "
                      f"@ {t['price']:,.0f}원{pnl_str} ({t['mode']})")

    # ── 최종 리포트 ─────────────────────────────────────────
    def print_final_report(self, duration: float):
        buys  = [t for t in self.trade_log if t["side"] == "BUY"]
        sells = [t for t in self.trade_log if t["side"] == "SELL"]
        pnls  = [t["pnl"] for t in sells]

        print(f"\n{'='*70}")
        print(f"  트레이더 마크 📊 - AutoTrader 최종 리포트")
        print(f"{'='*70}")
        print(f"  모드       : {'모의거래' if self.paper_mode else '실거래'}")
        print(f"  실행 시간  : {duration:.0f}초")
        print(f"  총 매수    : {len(buys)}회")
        print(f"  총 매도    : {len(sells)}회")
        print(f"  총 신호    : {len(self.signal_log)}개")
        print(f"  일일 PnL   : {self.daily_pnl:+.2%}")

        if pnls:
            wins    = [p for p in pnls if p > 0]
            losses  = [p for p in pnls if p <= 0]
            win_rate = len(wins) / len(pnls)
            avg_pnl  = sum(pnls) / len(pnls)
            print(f"\n  거래 성과:")
            print(f"    승률     : {win_rate:.0%} ({len(wins)}승 {len(losses)}패)")
            print(f"    평균 PnL : {avg_pnl:+.3%}")
            print(f"    최대 이익: {max(pnls):+.3%}")
            print(f"    최대 손실: {min(pnls):+.3%}")

        print(f"\n  🚀 다음 단계:")
        print(f"    simulate=False 설정 시 실제 업비트 주문 실행")
        print(f"    3월 16일 소액(100,000원)으로 실전 테스트 권장")
        print(f"{'='*70}")

    # ── 메인 실행 ───────────────────────────────────────────
    def start(self, duration: int = 60):
        # 계좌 확인
        print("📋 계좌 상태 확인 중...")
        self.check_account()
        self.sync_existing_positions()
        print()

        # WebSocket 연결
        self.ws.on_ticker = self._on_ticker
        try:
            self.ws.connect(tick_interval=0.5)
        except TypeError:
            # 실제 UpbitWebSocketClient는 tick_interval 인자를 받지 않음
            self.ws.connect()
        self.running = True
        self.write_health_snapshot(force=True)
        self._systemd_notify("READY=1")
        last_watchdog_ping = time.time()

        if duration <= 0:
            print(f"🚀 AutoTrader 시작 (무기한 실행)\n")
        else:
            print(f"🚀 AutoTrader 시작 ({duration}초)\n")

        start_wall = time.time()
        last_report = -1

        try:
            last_pending_check = 0.0
            while True:
                elapsed = time.time() - start_wall
                if duration > 0 and elapsed >= duration:
                    break
                slot    = int(elapsed) // 20
                if slot > last_report:
                    last_report = slot
                    self.print_status(elapsed)

                # 미체결 주문 체크 (20초마다)
                if time.time() - last_pending_check >= 20:
                    self._check_pending_orders()
                    last_pending_check = time.time()

                if time.time() - last_watchdog_ping >= 10:
                    self._systemd_notify("WATCHDOG=1")
                    last_watchdog_ping = time.time()

                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n  ⏹️  사용자 중단")

        self.ws.disconnect()
        self.running = False
        self.write_health_snapshot(force=True)
        self.print_final_report(time.time() - start_wall)


# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mode = os.getenv("PAPER_MODE", "true").lower() in ("1", "true", "yes", "on")
    duration = int(os.getenv("RUN_SECONDS", "60"))
    ws_sim = os.getenv("WS_SIMULATE")
    ws_simulate = None if ws_sim is None else ws_sim.lower() in ("1", "true", "yes", "on")

    trader = AutoTrader(
        symbols=["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-ADA", "KRW-DOGE", "KRW-DOT", "KRW-LINK", "KRW-POL", "KRW-AVAX"],
        paper_mode=mode,
        ws_simulate=ws_simulate,
    )
    trader.start(duration=duration)
