#!/usr/bin/env python3
"""트레이더 마크 📊 - 대시보드 서버"""
import json, os, socket, time, sys, subprocess
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

PORT = 8080
BASE = Path(__file__).parent
LIVE_TRADE_LOG_FILE = BASE / 'live_trade_log.json'
LIVE_SYNC_STATE_FILE = BASE / '.live_sync_state.json'
WS_HEALTH_FILE = BASE / 'ws_health.json'
AI_STATUS_FILE = BASE / 'ai_status_live.json'
HC_STATE_FILE = BASE / '.healthcheck_state'
TRADE_LOG_MAX_ITEMS = 5000      # 대시보드 거래내역 보존 개수
MIN_POSITION_VALUE_KRW = 5000   # 잔여 찌꺼기(먼지) 포지션은 표시 제외

# Upbit API 클라이언트 추가
sys.path.insert(0, str(Path(__file__).parent))
try:
    from upbit_live_client import UpbitLiveClient
    # 대시보드는 실투자 기본 계정(B) 기준으로 조회
    upbit = UpbitLiveClient(account=os.getenv('TRADING_ACCOUNT', 'B'))
    UPBIT_AVAILABLE = True
except Exception as e:
    print(f"⚠️ Upbit 클라이언트 로드 실패: {e}")
    upbit = None
    UPBIT_AVAILABLE = False

HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>트레이더 마크 📊</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; font-family:'Segoe UI',sans-serif; }
body { background:#0f172a; color:#e2e8f0; min-height:100vh; padding:20px; }
h1 { text-align:center; font-size:2rem; color:#60a5fa; padding:20px 0; }
.subtitle { text-align:center; color:#94a3b8; margin-bottom:12px; font-size:0.9rem; }
.health-row { display:flex; justify-content:center; margin-bottom:10px; }
.health-badge { display:inline-flex; align-items:center; gap:6px; border:1px solid #334155; border-radius:999px; padding:6px 10px; font-size:0.8rem; color:#cbd5e1; background:#0f172a; cursor:pointer; }
.health-dot { width:8px; height:8px; border-radius:50%; background:#64748b; }
.health-badge.ok .health-dot { background:#22c55e; }
.health-badge.warn .health-dot { background:#f59e0b; }
.health-badge.bad .health-dot { background:#ef4444; }
.health-detail { text-align:center; color:#94a3b8; font-size:0.78rem; margin:4px 0 10px; display:none; }
.health-detail.show { display:block; }
.health-alert { display:none; margin:0 auto 12px; max-width:980px; border:1px solid #7f1d1d; background:#3f1111; color:#fecaca; border-radius:10px; padding:8px 12px; font-size:0.82rem; }
.health-alert.show { display:block; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:16px; margin-bottom:30px; }
.card { background:#1e293b; border-radius:12px; padding:20px; border:1px solid #334155; }
.card .label { color:#94a3b8; font-size:0.85rem; margin-bottom:8px; }
.card .val { font-size:1.8rem; font-weight:700; }
.card .sub { font-size:0.85rem; margin-top:4px; }
.pos { color:#4ade80; }
.neg { color:#f87171; }
.table-wrap { background:#1e293b; border-radius:12px; padding:20px; border:1px solid #334155; overflow-x:auto; }
.table-wrap h2 { color:#60a5fa; margin-bottom:16px; font-size:1.1rem; }
table { width:100%; border-collapse:collapse; }
th { text-align:left; padding:10px 12px; background:#0f172a; color:#94a3b8; font-size:0.85rem; }
td { padding:10px 12px; border-bottom:1px solid #334155; font-size:0.9rem; }
tr:hover td { background:rgba(96,165,250,0.05); }
.badge { display:inline-block; padding:3px 10px; border-radius:20px; font-size:0.8rem; font-weight:600; white-space:nowrap; word-break:keep-all; }
.badge.buy { background:rgba(74,222,128,0.15); color:#4ade80; }
.badge.sell { background:rgba(248,113,113,0.15); color:#f87171; }
.pnl-cell { white-space:nowrap; word-break:keep-all; }
.footer { text-align:center; margin-top:24px; color:#475569; font-size:0.85rem; }
.footer span { color:#60a5fa; font-weight:600; }
.btn { background:#3b82f6; color:#fff; border:none; padding:8px 16px; border-radius:8px; cursor:pointer; font-size:0.9rem; }
.btn:hover { background:#2563eb; }
#status { text-align:center; padding:6px; font-size:0.8rem; }
.profile-switch { display:flex; gap:8px; align-items:center; justify-content:center; margin:8px 0 14px; flex-wrap:wrap; }
.profile-label { color:#94a3b8; font-size:0.85rem; }
.pgroup { display:flex; align-items:center; gap:4px; }
.pbtn { border:1px solid #334155; background:#1e293b; color:#cbd5e1; padding:6px 10px; border-radius:8px; cursor:pointer; font-weight:600; }
.pbtn.active { background:#16a34a; color:#fff; border-color:#16a34a; }
.tip-wrap { position:relative; display:inline-flex; align-items:center; }
.tip-icon { width:18px; height:18px; border-radius:50%; border:1px solid #475569; color:#cbd5e1; background:#0f172a; font-size:12px; line-height:16px; text-align:center; cursor:pointer; padding:0; }
.tip-bubble { display:none; position:absolute; top:24px; right:0; min-width:220px; max-width:260px; background:#111827; color:#e5e7eb; border:1px solid #334155; border-radius:8px; padding:8px 10px; font-size:12px; line-height:1.4; z-index:50; box-shadow:0 8px 20px rgba(0,0,0,.35); white-space:pre-line; }
.tip-wrap:hover .tip-bubble, .tip-wrap:focus-within .tip-bubble { display:block; }
.tabs { display:flex; gap:8px; margin-bottom:14px; }
.tab-btn { flex:1; border:1px solid #334155; background:#1e293b; color:#cbd5e1; padding:10px 12px; border-radius:10px; cursor:pointer; font-weight:600; }
.tab-btn.active { background:#1d4ed8; color:#fff; border-color:#1d4ed8; }
.tab-panel { display:none; }
.tab-panel.active { display:block; }
.ab-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; margin-bottom:16px; }
.ab-card { background:#1e293b; border:1px solid #334155; border-radius:12px; padding:14px; }
.ab-card h3 { font-size:0.95rem; color:#93c5fd; margin-bottom:8px; }
.ab-card .big { font-size:1.35rem; font-weight:700; }
.chart-container { background:#1e293b; border-radius:12px; padding:20px; border:1px solid #334155; margin-bottom:30px; }
.chart-container h2 { color:#60a5fa; margin-bottom:16px; font-size:1.1rem; }
.chart-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:20px; }
.chart-box { height:200px; position:relative; }
.chart-line { position:absolute; left:0; right:0; top:0; bottom:0; }
.chart-label { position:absolute; bottom:-25px; left:0; right:0; text-align:center; font-size:0.85rem; color:#94a3b8; }
.chart-entry { position:absolute; width:4px; background:#4ade80; top:0; bottom:0; }
.chart-entry-label { position:absolute; top:-25px; left:50%; transform:translateX(-50%); background:#4ade80; color:#fff; padding:2px 8px; border-radius:4px; font-size:0.8rem; white-space:nowrap; }
.chart-sl { position:absolute; width:4px; background:#60a5fa; top:0; bottom:0; }
.chart-sl-label { position:absolute; bottom:-25px; left:50%; transform:translateX(-50%); background:#60a5fa; color:#fff; padding:2px 8px; border-radius:4px; font-size:0.8rem; white-space:nowrap; }
.chart-tp { position:absolute; width:4px; background:#f87171; top:0; bottom:0; }
.chart-tp-label { position:absolute; bottom:-25px; left:50%; transform:translateX(-50%); background:#f87171; color:#fff; padding:2px 8px; border-radius:4px; font-size:0.8rem; white-space:nowrap; }
.price-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; margin-bottom:20px; }
.price-card { background:#1e293b; border-radius:8px; padding:15px; border:1px solid #334155; }
.price-card h3 { font-size:0.9rem; color:#94a3b8; margin-bottom:8px; }
.price-card .price { font-size:1.5rem; font-weight:700; margin-bottom:4px; }
.price-card .change { font-size:0.85rem; }
.mobile-chart-container { display:none; background:#1e293b; border-radius:12px; padding:16px; border:1px solid #334155; margin-bottom:20px; }
.mobile-chart-container h2 { color:#60a5fa; margin-bottom:12px; font-size:1rem; }
.mpos-card { background:#0f172a; border:1px solid #334155; border-radius:10px; padding:12px; margin-bottom:10px; }
.mpos-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; font-size:0.95rem; }
.mpos-pnl { font-weight:700; }
.mbar-track { position:relative; height:28px; border-radius:8px; background:#1e293b; border:1px solid #334155; margin:8px 0; }
.m-marker { position:absolute; top:0; bottom:0; width:3px; }
.m-marker.entry { background:#4ade80; }
.m-marker.current { background:#fbbf24; }
.m-marker.sl { background:#60a5fa; }
.m-marker.tp { background:#f87171; }
.mlegend { display:grid; grid-template-columns:1fr 1fr; gap:4px 8px; font-size:0.78rem; color:#cbd5e1; }
.mlegend b { color:#e2e8f0; }

@media (max-width: 768px) {
  body { padding:10px; }
  h1 { font-size:1.4rem; padding:10px 0; }
  .subtitle { font-size:0.82rem; margin-bottom:14px; }
  .price-grid, .grid, .chart-grid, .ab-grid { grid-template-columns:1fr; gap:10px; margin-bottom:14px; }
  .price-card, .card, .table-wrap, .ab-card { padding:12px; }
  .tab-btn { font-size:0.85rem; padding:9px 8px; }
  .card .label { font-size:0.9rem; }
  .card .val { font-size:1.7rem; }
  .card .sub { font-size:0.9rem; }
  .price-card .price { font-size:1.9rem; }
  .table-wrap h2 { font-size:0.95rem; }
  th, td { padding:8px 6px; font-size:0.78rem; }
  th:nth-child(5), td:nth-child(5), th:nth-child(6), td:nth-child(6), th:nth-child(8), td:nth-child(8) { display:none; }
  .badge { font-size:0.76rem; padding:3px 8px; }
  .pnl-cell { min-width:72px; }
  .btn { padding:5px 10px; font-size:0.75rem; }
  .chart-container { display:none; }
  .mobile-chart-container { display:block; }
  .footer { font-size:0.74rem; line-height:1.45; }
}
</style>

<!-- AI 봇 상태 패널 스타일 -->
<style>
.ai-panel { background:#1e293b; border:1px solid #334155; border-radius:12px; padding:16px 20px; margin:0 auto 16px; max-width:980px; }
.ai-panel h2 { font-size:1.05rem; color:#60a5fa; margin-bottom:12px; display:flex; align-items:center; gap:8px; }
.ai-panel h2 .toggle-btn { cursor:pointer; font-size:0.8rem; color:#94a3b8; background:#0f172a; border:1px solid #334155; border-radius:6px; padding:2px 10px; margin-left:auto; }
.agent-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(170px,1fr)); gap:10px; margin-bottom:14px; }
.agent-card { background:#0f172a; border:1px solid #334155; border-radius:10px; padding:12px; text-align:center; }
.agent-card .aname { font-size:0.78rem; color:#94a3b8; margin-bottom:4px; }
.agent-card .asignal { font-size:1.1rem; font-weight:700; }
.agent-card .asignal.buy { color:#22c55e; }
.agent-card .asignal.sell { color:#ef4444; }
.agent-card .asignal.hold { color:#f59e0b; }
.agent-card .aweight { font-size:0.72rem; color:#64748b; margin-top:2px; }
.agent-card .ascore { font-size:0.75rem; color:#cbd5e1; }
.final-signal { display:flex; align-items:center; gap:14px; padding:10px 14px; background:#0f172a; border-radius:10px; border:1px solid #334155; margin-bottom:14px; flex-wrap:wrap; }
.final-signal .fs-sym { font-weight:700; color:#e2e8f0; min-width:90px; }
.final-signal .fs-signal { font-size:1.1rem; font-weight:700; padding:2px 12px; border-radius:6px; }
.final-signal .fs-signal.buy { background:#052e16; color:#22c55e; }
.final-signal .fs-signal.sell { background:#450a0a; color:#ef4444; }
.final-signal .fs-signal.hold { background:#422006; color:#f59e0b; }
.final-signal .fs-conf { color:#94a3b8; font-size:0.85rem; }
.final-signal .fs-votes { color:#64748b; font-size:0.78rem; }
.profile-detail { display:grid; grid-template-columns:repeat(auto-fit, minmax(200px,1fr)); gap:10px; margin-top:12px; }
.pd-item { background:#0f172a; border:1px solid #334155; border-radius:8px; padding:10px 14px; }
.pd-item .pd-label { font-size:0.75rem; color:#64748b; margin-bottom:3px; }
.pd-item .pd-val { font-size:0.95rem; color:#e2e8f0; font-weight:600; }
.pd-item .pd-val.warn { color:#f59e0b; }
.pd-item .pd-val.ok { color:#22c55e; }
.pd-item .pd-val.danger { color:#ef4444; }
.conf-bar { height:6px; background:#334155; border-radius:3px; margin-top:5px; overflow:hidden; }
.conf-fill { height:100%; border-radius:3px; transition:width 0.3s; }
.conf-fill.high { background:#22c55e; }
.conf-fill.mid { background:#f59e0b; }
.conf-fill.low { background:#ef4444; }
</style>
</head>
<body>
<h1>트레이더 마크 📊</h1>
<div class="subtitle">실시간 실투자 대시보드 &nbsp;|&nbsp; <span id="ts">로딩 중...</span></div>
<div class="health-row">
  <div id="healthBadge" class="health-badge" onclick="toggleHealthDetail()" title="클릭해서 상세 보기">
    <span class="health-dot"></span>
    <span id="healthText">WS 상태 확인 중...</span>
  </div>
</div>
<div id="healthDetail" class="health-detail"></div>
<div id="healthAlert" class="health-alert"></div>
<div id="status"></div>

<div class="profile-switch">
  <span class="profile-label">투자방식:</span>

  <div class="pgroup">
    <button class="pbtn" id="pSAFE" onclick="setProfile('SAFE')">SAFE</button>
    <span class="tip-wrap">
      <button class="tip-icon" aria-label="SAFE 설명">i</button>
      <span class="tip-bubble">SAFE: 보수적 운용
- 예상 리스크: 낮음
- 거래 빈도: 낮음
- 진입 신뢰도 기준: 높음</span>
    </span>
  </div>

  <div class="pgroup">
    <button class="pbtn" id="pBALANCED" onclick="setProfile('BALANCED')">BALANCED</button>
    <span class="tip-wrap">
      <button class="tip-icon" aria-label="BALANCED 설명">i</button>
      <span class="tip-bubble">BALANCED: 균형 운용
- 예상 리스크: 중간
- 거래 빈도: 중간
- 기본 추천 모드</span>
    </span>
  </div>

  <div class="pgroup">
    <button class="pbtn" id="pAGGRESSIVE" onclick="setProfile('AGGRESSIVE')">AGGRESSIVE</button>
    <span class="tip-wrap">
      <button class="tip-icon" aria-label="AGGRESSIVE 설명">i</button>
      <span class="tip-bubble">AGGRESSIVE: 공격 운용
- 예상 리스크: 높음
- 거래 빈도: 높음
- 진입 신뢰도 기준: 완화</span>
    </span>
  </div>

  <div class="pgroup">
    <button class="pbtn" id="pSCALP" onclick="setProfile('SCALP')">SCALP</button>
    <span class="tip-wrap">
      <button class="tip-icon" aria-label="SCALP 설명">i</button>
      <span class="tip-bubble">SCALP: 검증형 초단타 모드
- 예상 리스크: 중간
- 거래 빈도: 중간~높음
- 진입: 단기추세(MA5>MA20) + RSI 과열회피 + 급등추격 금지
- 청산: +0.30% 익절 / 트레일링 / 시간청산
- 원칙: 왕복 수수료(0.10%) 제하고도 순이익일 때만 익절
- 자동튜닝: 최근 SCALP 성과로 TP/트레일/시간값 미세조정</span>
    </span>
  </div>

  <div class="pgroup">
    <button class="pbtn" id="pALL_IN" onclick="setProfile('ALL_IN')">ALL_IN</button>
    <span class="tip-wrap">
      <button class="tip-icon" aria-label="ALL_IN 설명">i</button>
      <span class="tip-bubble">ALL_IN: 총 자금 가용 모드
- 예상 리스크: 매우 높음
- 거래 빈도: 신호 의존
- 신호 발생 시 KRW 잔고의 최대 98%까지 진입
- 단, 코인당 최대 투자금은 총자본의 1/3로 제한</span>
    </span>
  </div>

  <span class="profile-label" id="profileNow">현재: -</span>
</div>

<div style="display:flex;gap:8px;align-items:center;justify-content:center;margin:0 0 14px;flex-wrap:wrap;">
  <label for="allInMinNet" class="profile-label">ALL_IN 최소 순이익(원):</label>
  <input id="allInMinNet" type="number" min="0" step="1" value="30" style="width:110px;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:8px;padding:6px 8px;" disabled>
  <button class="btn" id="saveAllInMinNet" onclick="saveAllInMinNet()" disabled>적용</button>
</div>

<!-- AI 봇 상태 패널 -->
<div class="ai-panel" id="aiPanel">
  <h2>🤖 AI 봇 상태 <button class="toggle-btn" onclick="toggleAiPanel()">접기/펼치기</button></h2>
  <div id="aiPanelBody">
    <div id="aiSignals">로딩 중...</div>
    <div id="aiAgents"></div>
    <h2 style="margin-top:14px;">⚙️ 현재 프로필 설정</h2>
    <div class="profile-detail" id="profileDetail"></div>
  </div>
</div>

<div class="tabs">
  <button class="tab-btn active" id="tabBtnA" onclick="switchTab('a')">💰 실투자 대시보드</button>
</div>

<div id="panelA" class="tab-panel active">
<!-- 3개 코인 현재가 -->
<div class="price-grid" id="priceGrid"></div>

<!-- KPI 카드 -->
<div class="grid">
  <div class="card">
    <div class="label">💰 현재 자본</div>
    <div class="val" id="capital">-</div>
    <div class="sub" id="capitalSub">-</div>
  </div>
  <div class="card">
    <div class="label">📈 누적 수익률</div>
    <div class="val" id="ret">-</div>
    <div class="sub" id="retSub">-</div>
  </div>
  <div class="card">
    <div class="label">📊 총 거래 횟수</div>
    <div class="val" id="trades">-</div>
    <div class="sub">오늘: <span id="todayT">-</span>회</div>
  </div>
  <div class="card">
    <div class="label">🎯 승률</div>
    <div class="val" id="wr">-</div>
    <div class="sub">수익 거래: <span id="wins">-</span>회</div>
  </div>
  <div class="card">
    <div class="label">💸 총 수수료</div>
    <div class="val" id="fee">-</div>
    <div class="sub">거래당 평균: <span id="avgFee">-</span>원</div>
  </div>
</div>

<!-- 차트: 매수 지점 표시 -->
<div class="chart-container">
  <h2>📊 포지션 차트 (진입가 vs 현재가)</h2>
  <div class="chart-grid" id="chartGrid"></div>
</div>

<!-- 모바일용 포지션 그래프 -->
<div class="mobile-chart-container">
  <h2>📱 모바일 포지션 그래프</h2>
  <div id="mobilePosList"></div>
</div>

<!-- 거래 내역 -->
<div class="table-wrap">
  <h2>📋 최근 거래 내역 (최근 20건)
    <button class="btn" onclick="load()" style="float:right;font-size:0.8rem;padding:6px 14px;">새로고침</button>
  </h2>
  <table>
    <thead>
      <tr><th>일시</th><th>종목</th><th>매매</th><th>가격</th><th>수량</th><th>금액(원)</th><th>손익</th><th>사유</th></tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
</div>
</div>

<div id="panelB" class="tab-panel">
  <div class="price-grid" id="bPriceGrid"></div>

  <div class="grid">
    <div class="card">
      <div class="label">💰 B 현재 자본</div>
      <div class="val" id="bCapital">-</div>
      <div class="sub" id="bCapitalSub">-</div>
    </div>
    <div class="card">
      <div class="label">📈 B 누적 수익률</div>
      <div class="val" id="bRet">-</div>
      <div class="sub" id="bRetSub">-</div>
    </div>
    <div class="card">
      <div class="label">📊 B 총 거래</div>
      <div class="val" id="bTrades">-</div>
      <div class="sub">청산: <span id="bSells">-</span>회</div>
    </div>
    <div class="card">
      <div class="label">🎯 B 승률</div>
      <div class="val" id="bWr">-</div>
      <div class="sub">오픈 포지션: <span id="bOpen">-</span>개</div>
    </div>
  </div>

  <div class="table-wrap">
    <h2>📋 B 최근 거래 내역 (최근 20건)</h2>
    <table>
      <thead>
        <tr><th>시간</th><th>종목</th><th>매매</th><th>가격</th><th>손익</th><th>사유</th></tr>
      </thead>
      <tbody id="bTbody"></tbody>
    </table>
  </div>
</div>

<div id="panelAB" class="tab-panel">
  <div class="ab-grid">
    <div class="ab-card">
      <h3>A 전략 (검증형)</h3>
      <div class="big" id="aCap">-</div>
      <div id="aMeta" class="sub">-</div>
    </div>
    <div class="ab-card">
      <h3>B 전략 (다수결 실험형)</h3>
      <div class="big" id="bCap">-</div>
      <div id="bMeta" class="sub">-</div>
    </div>
    <div class="ab-card">
      <h3>수익률 비교</h3>
      <div class="big" id="abRet">-</div>
      <div id="abDiff" class="sub">-</div>
    </div>
  </div>

  <div class="table-wrap">
    <h2>📌 A/B 비교 요약</h2>
    <table>
      <thead>
        <tr><th>항목</th><th>A(검증형)</th><th>B(실험형)</th></tr>
      </thead>
      <tbody id="abTbody"></tbody>
    </table>
  </div>
</div>

<div class="footer">
  자동 새로고침: <span>10초</span> | 로컬: <span>localhost:8080</span> | 네트워크: <span id="neturl">-</span>
</div>

<script>
let timer = null;
let healthDetailOpen = false;

function toggleHealthDetail() {
  healthDetailOpen = !healthDetailOpen;
  const el = document.getElementById('healthDetail');
  if (el) el.classList.toggle('show', healthDetailOpen);
}

async function loadProfile() {
  try {
    const r = await fetch('/api/profile?t=' + Date.now());
    if (!r.ok) return;
    const d = await r.json();
    const p = (d.profile || 'BALANCED').toUpperCase();
    ['SAFE','BALANCED','AGGRESSIVE','SCALP','ALL_IN'].forEach(x => {
      const el = document.getElementById('p'+x);
      if (el) el.classList.toggle('active', x === p);
    });
    const now = document.getElementById('profileNow');
    if (now) now.textContent = '현재: ' + p;

    const isAllIn = p === 'ALL_IN';
    const input = document.getElementById('allInMinNet');
    const btn = document.getElementById('saveAllInMinNet');
    if (input) {
      input.disabled = !isAllIn;
      input.value = Math.round(Number(d.all_in_min_net_profit_krw ?? 30));
    }
    if (btn) btn.disabled = !isAllIn;
  } catch(e) {}
}

async function setProfile(profile) {
  try {
    const r = await fetch('/api/profile', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({profile})
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'profile update failed');
    await loadProfile();
  } catch(e) {
    document.getElementById('status').textContent = '⚠️ 투자방식 전환 실패: ' + e.message;
  }
}

async function saveAllInMinNet() {
  try {
    const v = Math.max(0, parseInt(document.getElementById('allInMinNet').value || '0', 10));
    const r = await fetch('/api/profile', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({all_in_min_net_profit_krw: v})
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'save failed');
    document.getElementById('status').textContent = `✅ ALL_IN 최소 순이익 ${v}원 적용`;
    await loadProfile();
  } catch(e) {
    document.getElementById('status').textContent = '⚠️ ALL_IN 필터 저장 실패: ' + e.message;
  }
}

function switchTab(tab) {
  const isA = tab === 'a';
  document.getElementById('panelA').classList.toggle('active', isA);
  document.getElementById('tabBtnA').classList.toggle('active', isA);
}

async function loadHealthz() {
  try {
    const r = await fetch('/api/healthz?t=' + Date.now());
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    const badge = document.getElementById('healthBadge');
    const text = document.getElementById('healthText');
    const detail = document.getElementById('healthDetail');
    const alert = document.getElementById('healthAlert');
    if (!badge || !text || !detail || !alert) return;

    const tickAge = d?.ws?.tick_age_sec;
    const fb = d?.ws?.fallback_1m;
    const svc = d?.service?.trader_autotrader;
    const st = d?.status || 'degraded';
    const connected = d?.ws?.connected;
    const reasons = Array.isArray(d?.reasons) ? d.reasons : [];
    const lastRestartTs = d?.service?.last_restart_ts;
    const lastRestartReason = d?.service?.last_restart_reason;

    let restartTxt = '';
    if (typeof lastRestartTs === 'number' && lastRestartTs > 0) {
      const secAgo = Math.max(0, Math.floor(Date.now()/1000 - lastRestartTs));
      restartTxt = ` · 복구 ${secAgo}s 전${lastRestartReason ? ` (${lastRestartReason})` : ''}`;
    }

    badge.classList.remove('ok', 'warn', 'bad');
    const bad = (svc !== 'active') || (typeof tickAge === 'number' && tickAge > 30);
    const warn = (!bad) && ((typeof fb === 'number' && fb >= 3) || st !== 'ok');

    if (bad) {
      badge.classList.add('bad');
      text.textContent = `🔴 WS 위험 · tick ${tickAge?.toFixed?.(1) ?? '-'}s · fb ${fb ?? '-'} · svc ${svc}${restartTxt}`;
      alert.classList.add('show');
      alert.textContent = `⚠️ 실시간 시세/연결 이상 감지: ${reasons.join(', ') || '상세 원인 확인 필요'}`;
    } else if (warn) {
      badge.classList.add('warn');
      text.textContent = `🟠 WS 주의 · tick ${tickAge?.toFixed?.(1) ?? '-'}s · fb ${fb ?? '-'} · svc ${svc}${restartTxt}`;
      alert.classList.remove('show');
      alert.textContent = '';
    } else {
      badge.classList.add('ok');
      text.textContent = `🟢 WS 정상 · tick ${tickAge?.toFixed?.(1) ?? '-'}s · fb ${fb ?? '-'} · svc ${svc}${restartTxt}`;
      alert.classList.remove('show');
      alert.textContent = '';
    }

    detail.textContent = `연결:${connected} · tick_age:${tickAge?.toFixed?.(2) ?? '-'}s · fallback_1m:${fb ?? '-'} · service:${svc} · status:${st}${reasons.length ? ` · reasons:${reasons.join('|')}` : ''}`;
    detail.classList.toggle('show', healthDetailOpen);

  } catch (e) {
    const badge = document.getElementById('healthBadge');
    const text = document.getElementById('healthText');
    const alert = document.getElementById('healthAlert');
    if (badge && text) {
      badge.classList.remove('ok', 'warn');
      badge.classList.add('bad');
      text.textContent = 'WS 상태 조회 실패';
    }
    if (alert) {
      alert.classList.add('show');
      alert.textContent = '⚠️ healthz 조회 실패 - 대시보드 상태 확인 필요';
    }
  }
}

async function load() {
  try {
    const r = await fetch('/api/portfolio?t=' + Date.now());
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    render(d);
    loadProfile();
    loadHealthz();
    loadAiStatus();
    document.getElementById('status').textContent = '';
  } catch(e) {
    document.getElementById('status').textContent = '⚠️ 데이터 로드 오류: ' + e.message;
    console.error(e);
  }
}

function fmt(n) { return (n||0).toLocaleString('ko-KR'); }

function render(d) {
  const capital = d.capital || 0;
  const init = d.initial_capital || capital || 1;
  const ret = ((capital - init) / init * 100).toFixed(2);
  const tl = d.trade_log || [];
  const today = new Date().toISOString().slice(0,10);
  const todayT = tl.filter(t => t.date && t.date.startsWith(today)).length;
  const wins = tl.filter(t => (t.profit||0) > 0).length;
  const wr = tl.length ? (wins/tl.length*100).toFixed(1) : '0.0';
  let fee = 0;
  tl.forEach(t => { fee += t.total_fee || (t.buy_fee||0) + (t.sell_fee||0); });

  // KPI
  document.getElementById('capital').textContent = fmt(capital) + '원';
  document.getElementById('capitalSub').innerHTML = `초기 대비 <span class="${ret>=0?'pos':'neg'}">${ret>=0?'+':''}${ret}%</span>`;
  document.getElementById('ret').textContent = ret + '%';
  document.getElementById('ret').className = 'val ' + (ret>=0?'pos':'neg');
  document.getElementById('retSub').textContent = ret>=0?'📈 상승 중':'📉 하락 중';
  document.getElementById('trades').textContent = tl.length + '회';
  document.getElementById('todayT').textContent = todayT;
  document.getElementById('wr').textContent = wr + '%';
  document.getElementById('wins').textContent = wins;
  document.getElementById('fee').textContent = Math.round(fee).toLocaleString('ko-KR') + '원';
  document.getElementById('avgFee').textContent = tl.length ? Math.round(fee/tl.length) : 0;

  // 타임스탬프
  if (d.last_updated) {
    const dt = new Date(d.last_updated);
    const diff = Math.floor((Date.now() - dt) / 1000);
    const txt = diff < 60 ? diff+'초 전' : Math.floor(diff/60)+'분 전';
    document.getElementById('ts').textContent = '업데이트: ' + txt;
  }

  // 현재가 카드
  renderPriceCards(d);

  // 차트
  renderCharts(d);
  renderMobilePositions(d);

  // 실투자 단일 탭

  // 테이블
  // 표는 봇 체결 중심으로 정리 (동기화 중복 행 숨김)
  const visible = tl.filter(t => (t.reason || '') !== 'UPBIT_SYNC');
  const recent = (visible.length ? visible : tl).slice(-20).reverse();
  let html = '';
  recent.forEach(t => {
    const dt = new Date(t.date||Date.now());
    const datePart = [dt.getFullYear(), String(dt.getMonth()+1).padStart(2,'0'), String(dt.getDate()).padStart(2,'0')].join('-');
    const timePart = [dt.getHours(),dt.getMinutes(),dt.getSeconds()]
      .map(x=>String(x).padStart(2,'0')).join(':');
    const dateTime = `${datePart} ${timePart}`;
    const profit = t.profit||0;
    const cls = profit>=0?'pos':'neg';
    const ptxt = (profit>=0?'+':'')+profit.toFixed(1);
    const side = t.side==='BUY'?'buy':'sell';
    const sideLabel = t.side==='BUY'?'🟢 매수':'🔴 매도';
    const amount = (t.value || ((t.price||0) * (t.volume||0)) || 0);
    html += `<tr>
      <td>${dateTime}</td>
      <td><b>${t.symbol||''}</b></td>
      <td><span class="badge ${side}">${sideLabel}</span></td>
      <td>${fmt(t.price)}원</td>
      <td>${(t.volume||0).toFixed(4)}</td>
      <td>${fmt(Math.round(amount))}</td>
      <td class="${cls} pnl-cell">${ptxt}원</td>
      <td>${t.reason||'AI'}</td>
    </tr>`;
  });
  document.getElementById('tbody').innerHTML = html || '<tr><td colspan="8" style="text-align:center;padding:30px;color:#94a3b8;">거래 내역 없음</td></tr>';
}

function renderPriceCards(d) {
  const symbols = ['KRW-BTC', 'KRW-ETH', 'KRW-XRP', 'KRW-SOL', 'KRW-ADA', 'KRW-DOGE', 'KRW-DOT', 'KRW-LINK', 'KRW-POL', 'KRW-AVAX'];
  let html = '';
  
  symbols.forEach(sym => {
    const pos = d.positions?.[sym];
    const entry = pos?.entry || 0;
    const vol = pos?.volume || 0;
    const invested = entry && vol ? entry * vol : 0;
    const current = d.current_prices?.[sym] || 0;
    const change = entry ? ((current - entry) / entry * 100).toFixed(2) : 0;
    const changeClass = change >= 0 ? 'pos' : 'neg';
    const changeSign = change >= 0 ? '+' : '';
    
    html += `
    <div class="price-card">
      <h3>${sym}</h3>
      <div class="price">${fmt(current)}원</div>
      <div class="change ${changeClass}">
        ${entry ? `진입가: ${fmt(entry)}원` : '포지션 없음'}
        ${entry ? `<br>투자금: ${fmt(Math.round(invested))}원` : ''}
        ${entry ? `<br>${changeSign}${change}%` : ''}
      </div>
    </div>`;
  });
  
  document.getElementById('priceGrid').innerHTML = html;
}

function renderCharts(d) {
  const positions = d.positions || {};
  const currentPrices = d.current_prices || {};
  let html = '';
  
  Object.entries(positions).forEach(([symbol, pos]) => {
    const entry = pos.entry || 0;
    const sl = pos.sl || 0;
    const tp = pos.tp || 0;
    const current = currentPrices[symbol] || entry;
    
    // 가격 범위 계산
    const minPrice = Math.min(entry, sl, tp, current) * 0.995;
    const maxPrice = Math.max(entry, sl, tp, current) * 1.005;
    const range = maxPrice - minPrice;
    
    // 상대적 위치 계산 (0~100%)
    const entryPercent = ((entry - minPrice) / range) * 100;
    const slPercent = ((sl - minPrice) / range) * 100;
    const tpPercent = ((tp - minPrice) / range) * 100;
    const currentPercent = ((current - minPrice) / range) * 100;
    
    html += `
    <div class="chart-box">
      <div class="chart-line" style="background:linear-gradient(to top, #334155 1px, transparent 1px); background-size:100% 20px;"></div>
      
      <!-- 현재가 라인 -->
      <div class="chart-entry" style="left:${currentPercent}%; background:#fbbf24;"></div>
      <div class="chart-entry-label" style="left:${currentPercent}%; background:#fbbf24;">
        현재가<br>${fmt(current)}원
      </div>
      
      <!-- 진입가 라인 -->
      <div class="chart-entry" style="left:${entryPercent}%;"></div>
      <div class="chart-entry-label" style="left:${entryPercent}%;">
        진입가<br>${fmt(entry)}원
      </div>
      
      <!-- 손절가 라인 (파란색) -->
      <div class="chart-sl" style="left:${slPercent}%;"></div>
      <div class="chart-sl-label" style="left:${slPercent}%;">
        손절<br>${fmt(sl)}원
      </div>
      
      <!-- 익절가 라인 (빨간색) -->
      <div class="chart-tp" style="left:${tpPercent}%;"></div>
      <div class="chart-tp-label" style="left:${tpPercent}%;">
        익절<br>${fmt(tp)}원
      </div>
      
      <div class="chart-label">${symbol}</div>
    </div>`;
  });
  
  // 포지션 없는 코인들
  const allSymbols = ['KRW-BTC', 'KRW-ETH', 'KRW-XRP', 'KRW-SOL', 'KRW-ADA', 'KRW-DOGE', 'KRW-DOT', 'KRW-LINK', 'KRW-POL', 'KRW-AVAX'];
  allSymbols.forEach(sym => {
    if (!positions[sym]) {
      const current = currentPrices[sym] || 0;
      if (current > 0) {
        html += `
        <div class="chart-box">
          <div class="chart-line" style="background:linear-gradient(to top, #334155 1px, transparent 1px); background-size:100% 20px;"></div>
          <div class="chart-entry" style="left:50%; background:#94a3b8;"></div>
          <div class="chart-entry-label" style="left:50%; background:#94a3b8;">
            현재가<br>${fmt(current)}원
          </div>
          <div class="chart-label">${sym} (포지션 없음)</div>
        </div>`;
      }
    }
  });
  
  document.getElementById('chartGrid').innerHTML = html || '<div style="text-align:center;padding:40px;color:#94a3b8;">포지션 없음</div>';
}

function renderMobilePositions(d) {
  const positions = d.positions || {};
  const currentPrices = d.current_prices || {};
  const symbols = ['KRW-BTC', 'KRW-ETH', 'KRW-XRP', 'KRW-SOL', 'KRW-ADA', 'KRW-DOGE', 'KRW-DOT', 'KRW-LINK', 'KRW-POL', 'KRW-AVAX'];
  let html = '';

  const toPct = (val, min, max) => {
    if (max - min <= 0) return 50;
    return Math.max(0, Math.min(100, ((val - min) / (max - min)) * 100));
  };

  symbols.forEach(symbol => {
    const pos = positions[symbol];
    const current = currentPrices[symbol] || 0;

    if (!pos) {
      html += `
      <div class="mpos-card">
        <div class="mpos-head"><b>${symbol}</b><span style="color:#94a3b8;">포지션 없음</span></div>
        <div style="font-size:0.9rem;color:#cbd5e1;">현재가: <b>${fmt(current)}원</b></div>
      </div>`;
      return;
    }

    const entry = pos.entry || 0;
    const sl = pos.sl || entry;
    const tp = pos.tp || entry;
    const pnl = entry ? ((current - entry) / entry * 100) : 0;
    const invested = (entry && (pos.volume||0)) ? entry * pos.volume : 0;

    const min = Math.min(sl, entry, tp, current) * 0.995;
    const max = Math.max(sl, entry, tp, current) * 1.005;

    const slPct = toPct(sl, min, max);
    const enPct = toPct(entry, min, max);
    const cuPct = toPct(current, min, max);
    const tpPct = toPct(tp, min, max);

    html += `
    <div class="mpos-card">
      <div class="mpos-head">
        <b>${symbol}</b>
        <span class="mpos-pnl ${pnl >= 0 ? 'pos' : 'neg'}">${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}%</span>
      </div>
      <div class="mbar-track">
        <div class="m-marker sl" style="left:${slPct}%"></div>
        <div class="m-marker entry" style="left:${enPct}%"></div>
        <div class="m-marker current" style="left:${cuPct}%"></div>
        <div class="m-marker tp" style="left:${tpPct}%"></div>
      </div>
      <div class="mlegend">
        <div>🟡 현재가 <b>${fmt(current)}원</b></div>
        <div>🟢 진입가 <b>${fmt(entry)}원</b></div>
        <div>💵 투자금 <b>${fmt(Math.round(invested))}원</b></div>
        <div>🔵 손절 <b>${fmt(sl)}원</b></div>
        <div>🔴 익절 <b>${fmt(tp)}원</b></div>
      </div>
    </div>`;
  });

  document.getElementById('mobilePosList').innerHTML = html;
}

function renderB(d) {
  const b = d.ab_test || {};
  const currentPrices = d.current_prices || {};
  const symbols = ['KRW-BTC', 'KRW-ETH', 'KRW-XRP', 'KRW-SOL', 'KRW-ADA', 'KRW-DOGE', 'KRW-DOT', 'KRW-LINK', 'KRW-POL', 'KRW-AVAX'];
  const init = b.initial_capital || 1000000;
  const bCapital = b.capital || init;
  const bRet = ((bCapital / init - 1) * 100);
  const bTrades = b.trades || 0;
  const bSells = b.sell_trades || 0;
  const bWr = b.win_rate || 0;
  const bPositions = b.positions || {};
  const bTradeLog = b.trade_log || [];

  document.getElementById('bCapital').textContent = fmt(bCapital) + '원';
  document.getElementById('bCapitalSub').innerHTML = `초기 대비 <span class="${bRet>=0?'pos':'neg'}">${bRet>=0?'+':''}${bRet.toFixed(2)}%</span>`;
  document.getElementById('bRet').textContent = `${bRet.toFixed(2)}%`;
  document.getElementById('bRet').className = 'val ' + (bRet>=0?'pos':'neg');
  document.getElementById('bRetSub').textContent = bRet>=0?'📈 상승 중':'📉 하락 중';
  document.getElementById('bTrades').textContent = `${bTrades}회`;
  document.getElementById('bSells').textContent = `${bSells}`;
  document.getElementById('bWr').textContent = `${bWr.toFixed(1)}%`;
  document.getElementById('bOpen').textContent = Object.keys(bPositions).length;

  // B 현재가 카드
  let phtml = '';
  symbols.forEach(sym => {
    const pos = bPositions[sym];
    const entry = pos?.entry || 0;
    const cur = currentPrices[sym] || 0;
    const chg = entry ? ((cur - entry) / entry * 100) : 0;
    phtml += `
    <div class="price-card">
      <h3>${sym}</h3>
      <div class="price">${fmt(cur)}원</div>
      <div class="change ${chg>=0?'pos':'neg'}">${entry ? `진입가: ${fmt(entry)}원<br>${chg>=0?'+':''}${chg.toFixed(2)}%` : '포지션 없음'}</div>
    </div>`;
  });
  document.getElementById('bPriceGrid').innerHTML = phtml;

  // B 거래 테이블
  const recent = bTradeLog.slice(-20).reverse();
  let html = '';
  recent.forEach(t => {
    const dt = new Date(t.date || Date.now());
    const time = [dt.getHours(),dt.getMinutes(),dt.getSeconds()].map(x=>String(x).padStart(2,'0')).join(':');
    const side = t.side === 'BUY' ? 'buy' : 'sell';
    const sideLabel = t.side === 'BUY' ? '🟢 매수' : '🔴 매도';
    const profit = Number(t.profit || 0);
    html += `<tr>
      <td>${time}</td>
      <td><b>${t.symbol||''}</b></td>
      <td><span class="badge ${side}">${sideLabel}</span></td>
      <td>${fmt(t.price)}원</td>
      <td class="${profit>=0?'pos':'neg'} pnl-cell">${profit?((profit>=0?'+':'')+profit.toFixed(1)+'원'):'-'}</td>
      <td>${t.reason||''}</td>
    </tr>`;
  });
  document.getElementById('bTbody').innerHTML = html || '<tr><td colspan="6" style="text-align:center;padding:30px;color:#94a3b8;">B 거래 내역 없음</td></tr>';
}

function renderAB(d) {
  const aCapital = d.capital || 0;
  const aInit = 1000000;
  const aTrades = (d.trade_log || []).length;
  const aSells = (d.trade_log || []).filter(t => t.side === 'SELL');
  const aWins = aSells.filter(t => (t.profit || 0) > 0).length;
  const aWinRate = aSells.length ? (aWins / aSells.length * 100) : 0;
  const aRet = (aCapital / aInit - 1) * 100;

  const b = d.ab_test || {};
  const bCapital = b.capital || aInit;
  const bTrades = b.trades || 0;
  const bSells = b.sell_trades || 0;
  const bWinRate = b.win_rate || 0;
  const bRet = b.return_pct || 0;

  document.getElementById('aCap').textContent = fmt(aCapital) + '원';
  document.getElementById('aMeta').innerHTML = `수익률 <span class="${aRet>=0?'pos':'neg'}">${aRet>=0?'+':''}${aRet.toFixed(2)}%</span> · 거래 ${aTrades}회`;

  document.getElementById('bCap').textContent = fmt(bCapital) + '원';
  document.getElementById('bMeta').innerHTML = `수익률 <span class="${bRet>=0?'pos':'neg'}">${bRet>=0?'+':''}${bRet.toFixed(2)}%</span> · 거래 ${bTrades}회`;

  const diff = (aRet - bRet);
  document.getElementById('abRet').innerHTML = `<span class="${diff>=0?'pos':'neg'}">A ${diff>=0?'+':''}${diff.toFixed(2)}%p</span>`;
  document.getElementById('abDiff').textContent = diff >= 0 ? 'A 전략 우세' : 'B 전략 우세';

  const rows = [
    ['현재 자본', fmt(aCapital)+'원', fmt(bCapital)+'원'],
    ['누적 수익률', `${aRet>=0?'+':''}${aRet.toFixed(2)}%`, `${bRet>=0?'+':''}${bRet.toFixed(2)}%`],
    ['총 거래', `${aTrades}회`, `${bTrades}회`],
    ['청산 거래', `${aSells.length}회`, `${bSells}회`],
    ['승률', `${aWinRate.toFixed(1)}%`, `${bWinRate.toFixed(1)}%`],
    ['오픈 포지션', `${Object.keys(d.positions||{}).length}개`, `${Object.keys((b.positions)||{}).length}개`],
  ];

  document.getElementById('abTbody').innerHTML = rows.map(r =>
    `<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td></tr>`
  ).join('');
}

// 네트워크 IP 표시
fetch('/api/info').then(r=>r.json()).then(d=>{
  document.getElementById('neturl').textContent = d.network_url || '?';
}).catch(()=>{});

// AI 봇 상태
let aiPanelOpen = true;
function toggleAiPanel() {
  aiPanelOpen = !aiPanelOpen;
  const body = document.getElementById('aiPanelBody');
  if (body) body.style.display = aiPanelOpen ? 'block' : 'none';
}

async function loadAiStatus() {
  try {
    const r = await fetch('/api/ai_status?t=' + Date.now());
    if (!r.ok) return;
    const d = await r.json();
    renderAiSignals(d);
    renderProfileDetail(d.profile_config);
  } catch(e) { console.error('AI status load error:', e); }
}

function renderAiSignals(d) {
  const symbols = d.symbols || [];
  let sigHtml = '';
  let agentHtml = '';

  symbols.forEach(s => {
    const sig = s.signal || 'HOLD';
    const cls = sig.toLowerCase();
    const conf = ((s.confidence || 0) * 100).toFixed(1);
    const confCls = conf >= 70 ? 'high' : conf >= 55 ? 'mid' : 'low';
    const votes = s.votes || {};
    sigHtml += `<div class="final-signal">
      <span class="fs-sym">${s.symbol}</span>
      <span class="fs-signal ${cls}">${sig}</span>
      <span class="fs-conf">신뢰도 ${conf}%</span>
      <div class="conf-bar" style="width:120px;"><div class="conf-fill ${confCls}" style="width:${conf}%;"></div></div>
      <span class="fs-votes">BUY ${((votes.BUY||0)*100).toFixed(0)}% · SELL ${((votes.SELL||0)*100).toFixed(0)}% · HOLD ${((votes.HOLD||0)*100).toFixed(0)}%</span>
    </div>`;

    if (s.agents && s.agents.length) {
      agentHtml += `<div style="margin:8px 0 4px;color:#94a3b8;font-size:0.8rem;">📊 ${s.symbol} 에이전트</div><div class="agent-grid">`;
      s.agents.forEach(a => {
        const aCls = (a.signal||'HOLD').toLowerCase();
        agentHtml += `<div class="agent-card">
          <div class="aname">${a.agent}</div>
          <div class="asignal ${aCls}">${a.signal}</div>
          <div class="ascore">점수 ${(a.score||0).toFixed(3)} · 신뢰도 ${((a.confidence||0)*100).toFixed(0)}%</div>
          <div class="aweight">가중치 ${a.weight||0}</div>
        </div>`;
      });
      agentHtml += '</div>';
    }
  });

  const noData = '<div style="color:#94a3b8;text-align:center;padding:14px;">시세 데이터 수집 중... (트레이더 실행 후 표시됩니다)</div>';
  document.getElementById('aiSignals').innerHTML = sigHtml || noData;
  document.getElementById('aiAgents').innerHTML = agentHtml;
}

function renderProfileDetail(cfg) {
  if (!cfg) return;
  const el = document.getElementById('profileDetail');
  if (!el) return;

  const items = [
    {label:'프로필', val: cfg.name || '-', cls:'ok'},
    {label:'최소 신뢰도', val: ((cfg.min_conf||0)*100).toFixed(0) + '%', cls: cfg.min_conf >= 0.70 ? 'warn' : 'ok'},
    {label:'리스크 스케일', val: (cfg.risk_scale||1).toFixed(1) + 'x', cls: cfg.risk_scale > 1.2 ? 'danger' : cfg.risk_scale < 0.8 ? 'ok' : ''},
    {label:'최대 주문 비율', val: ((cfg.max_order_ratio||0)*100).toFixed(0) + '%'},
    {label:'최소 순이익', val: fmt(cfg.min_net_profit_krw||0) + '원', cls: cfg.min_net_profit_krw > 100 ? 'warn' : 'ok'},
    {label:'AI 매도 최소 보유', val: Math.round((cfg.ai_sell_min_hold_sec||0)/60) + '분'},
    {label:'자동 손절 시간', val: Math.round((cfg.auto_stoploss_time_sec||0)/60) + '분'},
    {label:'자동 손절 임계', val: ((cfg.auto_stoploss_threshold_pct||0)*100).toFixed(1) + '%', cls:'danger'},
    {label:'손절가(SL)', val: ((cfg.stop_loss||0)*100).toFixed(1) + '%', cls:'danger'},
    {label:'익절가(TP)', val: ((cfg.take_profit||0)*100).toFixed(1) + '%', cls:'ok'},
    {label:'매수 확인 횟수', val: cfg.buy_confirmations || '-'},
    {label:'일일 손실 한도', val: cfg.daily_loss_limit || '5%'},
  ];

  if (cfg.scalp_take_profit) {
    items.push({label:'SCALP 익절', val: ((cfg.scalp_take_profit||0)*100).toFixed(2) + '%', cls:'ok'});
    items.push({label:'SCALP 트레일', val: ((cfg.scalp_trail_arm||0)*100).toFixed(2) + '% / ' + ((cfg.scalp_trail_gap||0)*100).toFixed(2) + '%'});
    items.push({label:'SCALP 시간청산', val: (cfg.scalp_time_exit_min||0) + '분'});
  }

  el.innerHTML = items.map(i =>
    `<div class="pd-item"><div class="pd-label">${i.label}</div><div class="pd-val ${i.cls||''}">${i.val}</div></div>`
  ).join('');
}

// 초기 로드 + 자동 새로고침
load();
loadAiStatus();
timer = setInterval(load, 10000);        // 포트폴리오/거래내역은 10초
aiTimer = setInterval(loadAiStatus, 2000); // AI 신호는 2초
</script>
</body>
</html>
"""

class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        path = self.path.split('?')[0]
        if path == '/api/profile':
            self.update_profile()
        else:
            self.respond(404, 'text/plain', b'Not Found')

    def do_GET(self):
        path = self.path.split('?')[0]  # 쿼리스트링 제거
        
        if path == '/':
            self.respond(200, 'text/html; charset=utf-8', HTML.encode())
        elif path == '/api/portfolio':
            self.serve_portfolio()
        elif path == '/api/health':
            self.send_json({'status': 'ok'})
        elif path == '/api/healthz':
            self.serve_healthz()
        elif path == '/api/info':
            self.send_json({'network_url': f'http://{get_ip()}:{PORT}'})
        elif path == '/api/ai_status':
            self.serve_ai_status()
        elif path == '/api/profile':
            self.serve_profile()
        else:
            self.respond(404, 'text/plain', b'Not Found')

    def respond(self, code, ctype, body):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(body)

    def serve_healthz(self):
        now_ts = time.time()
        out = {
            'status': 'ok',
            'now': now_ts,
            'ws': {
                'health_file_exists': WS_HEALTH_FILE.exists(),
                'connected': None,
                'tick_age_sec': None,
                'fallback_1m': None,
                'last_update_sec': None,
            },
            'service': {
                'trader_autotrader': 'unknown',
                'last_restart_ts': None,
                'last_restart_reason': None,
            }
        }

        # ws_health.json 기반 상태
        try:
            if WS_HEALTH_FILE.exists():
                raw = json.loads(WS_HEALTH_FILE.read_text(encoding='utf-8'))
                ts = float(raw.get('ts', 0) or 0)
                last_tick = float(raw.get('last_ws_tick_at', 0) or 0)
                out['ws']['connected'] = bool(raw.get('ws_connected'))
                out['ws']['fallback_1m'] = int(raw.get('rest_fallback_count_1m', 0) or 0)
                out['ws']['last_update_sec'] = (now_ts - ts) if ts > 0 else None
                out['ws']['tick_age_sec'] = (now_ts - last_tick) if last_tick > 0 else None
        except Exception as e:
            out['ws']['error'] = str(e)

        # systemd 서비스 상태
        try:
            res = subprocess.run(
                ['systemctl', '--user', 'is-active', 'trader-autotrader.service'],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            out['service']['trader_autotrader'] = (res.stdout or '').strip() or 'unknown'
        except Exception as e:
            out['service']['error'] = str(e)

        # 최근 자동복구 이력
        try:
            if HC_STATE_FILE.exists():
                txt = HC_STATE_FILE.read_text(encoding='utf-8')
                for line in txt.splitlines():
                    if line.startswith('last_restart_ts='):
                        out['service']['last_restart_ts'] = int(line.split('=', 1)[1].strip())
                    elif line.startswith('last_restart_reason='):
                        out['service']['last_restart_reason'] = line.split('=', 1)[1].strip().strip('"')
        except Exception:
            pass

        # 종합 상태
        tick_age = out['ws']['tick_age_sec']
        fallback_1m = out['ws']['fallback_1m']
        connected = out['ws']['connected']
        service_ok = out['service']['trader_autotrader'] == 'active'

        degraded = False
        reasons = []
        if not service_ok:
            degraded = True
            reasons.append('service_inactive')
        if connected is False:
            degraded = True
            reasons.append('ws_disconnected')
        if isinstance(tick_age, (int, float)) and tick_age > 30:
            degraded = True
            reasons.append('tick_stale')
        if isinstance(fallback_1m, int) and fallback_1m >= 6:
            degraded = True
            reasons.append('fallback_high')

        if degraded:
            out['status'] = 'degraded'
            out['reasons'] = reasons

        self.send_json(out)

    def serve_portfolio(self):
        try:
            if not UPBIT_AVAILABLE:
                self.send_json({'error': 'Upbit API 사용 불가'}, 500)
                return

            symbols = ['KRW-BTC', 'KRW-ETH', 'KRW-XRP', 'KRW-SOL', 'KRW-ADA', 'KRW-DOGE', 'KRW-DOT', 'KRW-LINK', 'KRW-POL', 'KRW-AVAX']
            current_prices = {s: 0 for s in symbols}

            # 현재가
            try:
                tickers = upbit.get_ticker(symbols)
                for ticker in tickers:
                    if isinstance(ticker, dict) and 'market' in ticker:
                        current_prices[ticker['market']] = float(ticker.get('trade_price', 0))
            except Exception as e:
                print(f"현재가 조회 오류: {e}")

            # 실계좌 자산
            portfolio = upbit.get_portfolio()
            krw_balance = float(portfolio.get('KRW', {}).get('balance', 0))
            positions = {}
            coin_value = 0.0

            for sym in symbols:
                coin = sym.split('-')[1]
                asset = portfolio.get(coin)
                if not asset:
                    continue
                cur = current_prices.get(sym, 0)
                bal = float(asset.get('balance', 0) or 0)
                avg = float(asset.get('avg_price', 0) or 0)
                val = bal * cur
                coin_value += val
                # 미세 잔고(먼지)로 인한 "투자금 1원" 표기 방지
                if bal > 0 and val >= MIN_POSITION_VALUE_KRW:
                    # 프로필별 실제 전략 파라미터로 SL/TP 계산
                    try:
                        from auto_trader import STRATEGY_PARAMS as _STRAT
                    except Exception:
                        try:
                            from auto_trader import RISK_CONFIG as _STRAT
                        except Exception:
                            _STRAT = {}
                    strat = _STRAT.get('MODERATE', {}) if isinstance(_STRAT, dict) else {}
                    sl_pct = strat.get('stop_loss', 0.015)
                    tp_pct = strat.get('take_profit', 0.025)
                    positions[sym] = {
                        'entry': avg,
                        'volume': bal,
                        'sl': avg * (1 - sl_pct) if avg else 0,
                        'tp': avg * (1 + tp_pct) if avg else 0,
                    }

            total_eval = krw_balance + coin_value

            # 기준 자본(최초 1회 저장)
            baseline_file = BASE / 'live_baseline.json'
            if baseline_file.exists():
                baseline = json.loads(baseline_file.read_text(encoding='utf-8'))
                initial_capital = float(baseline.get('initial_capital', total_eval or 1))
                # 잘못 저장된 baseline(예: 1원) 자동 복구
                if initial_capital < 1000 and total_eval > 1000:
                    initial_capital = total_eval
                    baseline_file.write_text(json.dumps({'initial_capital': initial_capital, 'created_at': time.time()}, ensure_ascii=False, indent=2), encoding='utf-8')
            else:
                initial_capital = total_eval or 1
                baseline_file.write_text(json.dumps({'initial_capital': initial_capital, 'created_at': time.time()}, ensure_ascii=False, indent=2), encoding='utf-8')

            # 로컬 실거래 로그 + 업비트 체결 동기화
            trade_log = self.load_live_trade_log()
            trade_log = self.sync_upbit_done_orders(trade_log)
            trade_log = self.ensure_position_entries(trade_log, positions)

            data = {
                'capital': total_eval,
                'initial_capital': initial_capital,
                'positions': positions,
                'trade_log': trade_log,
                'current_prices': current_prices,
                'last_updated': time.strftime('%Y-%m-%dT%H:%M:%S'),
                'mode': 'live',
                'account': os.getenv('TRADING_ACCOUNT', 'B'),
                'krw_balance': krw_balance,
                'coin_value': coin_value,
            }
            self.send_json(data)
        except Exception as e:
            self.send_json({'error': str(e)}, 500)

    def load_live_trade_log(self):
        if LIVE_TRADE_LOG_FILE.exists():
            try:
                raw = json.loads(LIVE_TRADE_LOG_FILE.read_text(encoding='utf-8'))
                if isinstance(raw, list):
                    from datetime import datetime, timezone, timedelta
                    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
                    filtered = []
                    for t in raw:
                        ds = t.get('date')
                        if not ds:
                            filtered.append(t)
                            continue
                        try:
                            dt = datetime.fromisoformat(str(ds).replace('Z', '+00:00'))
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            if dt >= cutoff:
                                filtered.append(t)
                        except Exception:
                            filtered.append(t)
                    if len(filtered) != len(raw):
                        self.save_live_trade_log(filtered)
                    return filtered[-TRADE_LOG_MAX_ITEMS:]
            except Exception:
                pass
        return []

    def save_live_trade_log(self, trade_log):
        try:
            LIVE_TRADE_LOG_FILE.write_text(
                json.dumps(trade_log[-TRADE_LOG_MAX_ITEMS:], ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
        except Exception as e:
            print(f"거래로그 저장 오류: {e}")

    def sync_upbit_done_orders(self, trade_log):
        if not UPBIT_AVAILABLE:
            return trade_log

        # 너무 잦은 동기화 방지(10초)
        now_ts = time.time()
        last_sync = 0
        if LIVE_SYNC_STATE_FILE.exists():
            try:
                last_sync = float(json.loads(LIVE_SYNC_STATE_FILE.read_text(encoding='utf-8')).get('last_sync', 0))
            except Exception:
                last_sync = 0
        if now_ts - last_sync < 10:
            return trade_log

        try:
            done = upbit.get_orders(state='done')
            if not isinstance(done, list):
                done = []
        except Exception as e:
            print(f"업비트 체결 조회 오류: {e}")
            return trade_log

        existing_keys = set()
        for t in trade_log:
            k = t.get('uuid') or f"{t.get('date','')}_{t.get('side','')}_{t.get('symbol','')}_{t.get('price','')}_{t.get('volume','')}"
            existing_keys.add(k)

        added = 0
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)

        for o in done[:200]:
            uuid_ = o.get('uuid')
            side = 'BUY' if o.get('side') == 'bid' else 'SELL'
            symbol = o.get('market', '')
            price = float(o.get('price') or o.get('avg_price') or 0)
            volume = float(o.get('executed_volume') or o.get('volume') or 0)
            paid_fee = float(o.get('paid_fee') or 0)
            created_at = o.get('created_at') or time.strftime('%Y-%m-%dT%H:%M:%S')

            # 최근 14일 체결만 대시보드에 동기화
            try:
                dt = datetime.fromisoformat(str(created_at).replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < cutoff:
                    continue
            except Exception:
                pass

            key = uuid_ or f"{created_at}_{side}_{symbol}_{price}_{volume}"
            if key in existing_keys:
                continue

            trade_log.append({
                'uuid': uuid_,
                'time': created_at[11:19] if isinstance(created_at, str) and len(created_at) >= 19 else '',
                'date': created_at,
                'side': side,
                'symbol': symbol,
                'price': price,
                'volume': volume,
                'value': price * volume,
                'mode': 'live',
                'pnl': 0,
                'profit': 0,
                'total_fee': paid_fee,
                'reason': 'UPBIT_SYNC',
            })
            existing_keys.add(key)
            added += 1

        if added > 0:
            trade_log = sorted(trade_log, key=lambda x: x.get('date', ''))[-TRADE_LOG_MAX_ITEMS:]
            self.save_live_trade_log(trade_log)

        try:
            LIVE_SYNC_STATE_FILE.write_text(json.dumps({'last_sync': now_ts}, ensure_ascii=False), encoding='utf-8')
        except Exception:
            pass

        return trade_log

    def ensure_position_entries(self, trade_log, positions):
        """체결 내역 API가 누락돼도 현재 보유 포지션의 진입 정보를 거래내역에 보강."""
        existing_buy_symbols = {
            t.get('symbol')
            for t in trade_log
            if t.get('side') == 'BUY'
        }
        changed = False
        for symbol, pos in (positions or {}).items():
            if symbol in existing_buy_symbols:
                continue
            entry = float(pos.get('entry', 0) or 0)
            vol = float(pos.get('volume', 0) or 0)
            if entry <= 0 or vol <= 0:
                continue
            now = time.strftime('%Y-%m-%dT%H:%M:%S')
            trade_log.append({
                'uuid': f'POSSYNC-{symbol}-{entry}-{vol}',
                'time': now[11:19],
                'date': now,
                'side': 'BUY',
                'symbol': symbol,
                'price': entry,
                'volume': vol,
                'value': entry * vol,
                'mode': 'live',
                'pnl': 0,
                'profit': 0,
                'total_fee': 0,
                'reason': 'POSITION_SYNC',
            })
            changed = True

        if changed:
            trade_log = sorted(trade_log, key=lambda x: x.get('date', ''))[-TRADE_LOG_MAX_ITEMS:]
            self.save_live_trade_log(trade_log)
        return trade_log

    def serve_ai_status(self):
        """AI 봇 상태 + 프로필 설정 반환"""
        try:
            from ai_signal_engine import AISignalEngine

            # 현재 프로필 읽기
            profile_file = BASE / 'trading_profile.json'
            profile_name = 'BALANCED'
            overrides = {}
            try:
                if profile_file.exists():
                    raw = json.loads(profile_file.read_text(encoding='utf-8'))
                    profile_name = str(raw.get('profile', 'BALANCED')).upper()
                    overrides = (raw.get('overrides') or {}).get(profile_name, {})
            except Exception:
                pass

            # PROFILE_CONFIG에서 기본값 + 오버라이드 합침
            from auto_trader import PROFILE_CONFIG
            try:
                from auto_trader import STRATEGY_PARAMS as _STRAT
            except Exception:
                try:
                    from auto_trader import RISK_CONFIG as _STRAT
                except Exception:
                    _STRAT = {}

            base = dict(PROFILE_CONFIG.get(profile_name, PROFILE_CONFIG['BALANCED']))
            for k, v in overrides.items():
                if k in base and isinstance(v, (int, float)):
                    base[k] = v

            # volatility strategy 매핑
            vol_strategy = 'MODERATE'  # default
            strategy_cfg = _STRAT.get(vol_strategy, {}) if isinstance(_STRAT, dict) else {}

            profile_config = {
                'name': profile_name,
                'min_conf': base.get('min_conf', 0.65),
                'risk_scale': base.get('risk_scale', 1.0),
                'max_order_ratio': base.get('max_order_ratio', 0.60),
                'min_net_profit_krw': base.get('min_net_profit_krw', 0),
                'ai_sell_min_hold_sec': base.get('ai_sell_min_hold_sec', 900),
                'auto_stoploss_time_sec': base.get('auto_stoploss_time_sec', 7200),
                'auto_stoploss_threshold_pct': base.get('auto_stoploss_threshold_pct', -0.02),
                'stop_loss': strategy_cfg.get('stop_loss', 0.015),
                'take_profit': strategy_cfg.get('take_profit', 0.025),
                'buy_confirmations': base.get('buy_confirmations', 1),
                'daily_loss_limit': '5%',
                'scalp_take_profit': base.get('scalp_take_profit'),
                'scalp_trail_arm': base.get('scalp_trail_arm'),
                'scalp_trail_gap': base.get('scalp_trail_gap'),
                'scalp_time_exit_min': base.get('scalp_time_exit_min'),
            }

            # 1순위: AutoTrader가 기록한 실시간 스냅샷 사용 (실주문 로직과 동일 소스)
            try:
                if AI_STATUS_FILE.exists():
                    live_raw = json.loads(AI_STATUS_FILE.read_text(encoding='utf-8'))
                    symbols_obj = live_raw.get('symbols') or {}
                    if isinstance(symbols_obj, dict) and symbols_obj:
                        symbols_data = []
                        for sym in ['KRW-BTC', 'KRW-ETH', 'KRW-XRP', 'KRW-SOL', 'KRW-ADA', 'KRW-DOGE', 'KRW-DOT', 'KRW-LINK', 'KRW-POL', 'KRW-AVAX']:
                            row = symbols_obj.get(sym) or {'symbol': sym, 'signal': 'NO_DATA', 'confidence': 0, 'votes': {}, 'agents': []}
                            symbols_data.append({
                                'symbol': sym,
                                'signal': row.get('signal', 'HOLD'),
                                'confidence': row.get('confidence', 0),
                                'votes': row.get('votes', {}),
                                'agents': row.get('agents', []),
                                'strategy': row.get('strategy', live_raw.get('current_strategy', vol_strategy)),
                                'profile': row.get('profile', live_raw.get('profile', profile_name)),
                                'min_conf': row.get('min_conf', profile_config.get('min_conf', 0.65)),
                                'required_confirms': row.get('required_confirms', profile_config.get('buy_confirmations', 1)),
                                'buy_streak': row.get('buy_streak', 0),
                                'updated_at': row.get('updated_at', live_raw.get('ts')),
                            })

                        self.send_json({
                            'symbols': symbols_data,
                            'profile_config': profile_config,
                            'source': 'auto_trader_live',
                            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                        })
                        return
            except Exception:
                pass

            # 2순위 fallback: 대시보드에서 직접 계산
            symbols_data = []
            engine = AISignalEngine()
            symbols = ['KRW-BTC', 'KRW-ETH', 'KRW-XRP', 'KRW-SOL', 'KRW-ADA', 'KRW-DOGE', 'KRW-DOT', 'KRW-LINK', 'KRW-POL', 'KRW-AVAX']

            for sym in symbols:
                try:
                    candles = upbit.get_candles(sym, unit=5, count=50) if UPBIT_AVAILABLE else []
                    if not candles or not isinstance(candles, list) or len(candles) < 20:
                        symbols_data.append({'symbol': sym, 'signal': 'NO_DATA', 'confidence': 0, 'votes': {}, 'agents': []})
                        continue

                    prices = [float(c.get('trade_price', 0) or c.get('closing_price', 0)) for c in reversed(candles)]
                    prices = [p for p in prices if p > 0]
                    if len(prices) < 20:
                        symbols_data.append({'symbol': sym, 'signal': 'NO_DATA', 'confidence': 0, 'votes': {}, 'agents': []})
                        continue

                    import statistics
                    returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
                    vol = statistics.stdev(returns[-20:]) if len(returns) >= 20 else 0.005

                    decision = engine.decide(sym, prices, vol, strategy=vol_strategy)
                    symbols_data.append({
                        'symbol': sym,
                        'signal': decision.get('signal', 'HOLD'),
                        'confidence': decision.get('confidence', 0),
                        'votes': decision.get('votes', {}),
                        'agents': decision.get('agents', []),
                        'current_price': prices[-1] if prices else 0,
                    })
                except Exception as e:
                    symbols_data.append({'symbol': sym, 'signal': 'ERROR', 'confidence': 0, 'votes': {}, 'agents': [], 'error': str(e)})

            self.send_json({
                'symbols': symbols_data,
                'profile_config': profile_config,
                'source': 'dashboard_fallback',
                'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            })
        except Exception as e:
            self.send_json({'error': str(e), 'symbols': [], 'profile_config': {}}, 500)

    def serve_profile(self):
        p = BASE / 'trading_profile.json'
        profile = 'BALANCED'
        all_in_min = 30
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding='utf-8'))
                profile = raw.get('profile', 'BALANCED')
                all_in_min = float(((raw.get('overrides') or {}).get('ALL_IN') or {}).get('min_net_profit_krw', 30) or 0)
            except Exception:
                pass
        self.send_json({'profile': profile, 'all_in_min_net_profit_krw': all_in_min})

    def update_profile(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            body = self.rfile.read(length) if length > 0 else b'{}'
            req = json.loads(body.decode('utf-8'))
            p = BASE / 'trading_profile.json'
            cur = {}
            if p.exists():
                try:
                    cur = json.loads(p.read_text(encoding='utf-8'))
                except Exception:
                    cur = {}

            if 'profile' in req:
                profile = str(req.get('profile', 'BALANCED')).upper()
                if profile not in ('SAFE', 'BALANCED', 'AGGRESSIVE', 'SCALP', 'ALL_IN'):
                    self.send_json({'error': 'invalid profile'}, 400)
                    return
                cur['profile'] = profile

            if 'all_in_min_net_profit_krw' in req:
                v = float(req.get('all_in_min_net_profit_krw') or 0)
                if v < 0:
                    v = 0
                cur.setdefault('overrides', {}).setdefault('ALL_IN', {})['min_net_profit_krw'] = v

            cur['updated_at'] = time.time()
            p.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding='utf-8')

            out_profile = cur.get('profile', 'BALANCED')
            out_min = float(((cur.get('overrides') or {}).get('ALL_IN') or {}).get('min_net_profit_krw', 30) or 0)
            self.send_json({'ok': True, 'profile': out_profile, 'all_in_min_net_profit_krw': out_min})
        except Exception as e:
            self.send_json({'error': str(e)}, 500)

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.respond(code, 'application/json; charset=utf-8', body)

    def log_message(self, *args):
        pass  # 로그 생략

def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return '127.0.0.1'

if __name__ == '__main__':
    os.chdir(BASE)
    ip = get_ip()
    print(f'🚀 트레이더 마크 대시보드 시작')
    print(f'📍 로컬:    http://localhost:{PORT}')
    print(f'🌐 네트워크: http://{ip}:{PORT}')
    print('=' * 40)
    with DashboardServer(('0.0.0.0', PORT), Handler) as srv:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print('\n👋 종료')

