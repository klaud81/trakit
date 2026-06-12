import { useEffect, useRef, useState } from 'react';

// VI 차익거래 실시간 관측 대시보드 (rq-01).
// backend /api/ws/vi-arb WebSocket 스트림을 구독해 VI 발동·스프레드·랜덤엔드 재개를 표시.
// A단계: mock 피드. B단계에서 Kiwoom observer 로 데이터만 교체(스키마 동일).

function wsUrl() {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.host}/api/ws/vi-arb`;
}

const fmt = (n) => (n == null ? '-' : Number(n).toLocaleString());

// 보유종목 '지금 청산 시' 세후 순손익. 브로커 평가손익(pl)·평가금액(evlt)을 기준으로
// 매도 거래세+수수료만 차감 (cur/avg 재계산은 브로커 내부가와 불일치하므로 신뢰하지 않음).
function netAfterCost(h, p) {
  if (!h || h.pl == null) return null;
  const tax = p?.TAX ?? 0.0015, fee = p?.FEE ?? 0.00015;
  const evlt = h.evlt || h.cur * h.qty;                 // 평가금액(매도 시 총액)
  const basis = evlt - h.pl || h.avg * h.qty;           // 매수원금 = 평가금액 − 평가손익
  if (!evlt || !basis) return null;
  const net = h.pl - evlt * (tax + fee);                // 평가손익 − 매도 거래세·수수료
  return { net: Math.round(net), rate: (net / basis) * 100 };
}

// 지정가 매도 체결 축하 폭죽 — trigger 가 바뀔 때마다 캔버스 파티클 버스트 (~2초)
function Fireworks({ trigger }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!trigger || !ref.current) return undefined;
    const canvas = ref.current;
    const ctx = canvas.getContext('2d');
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    const colors = ['#E53935', '#FDD835', '#1E88E5', '#43A047', '#FB8C00', '#8E24AA', '#00ACC1', '#F06292'];
    const parts = [];
    // 8발을 시간차로 발사 (~7.5초 지속), 입자 크고 수명 길게 + 잔상 트레일
    for (let b = 0; b < 8; b += 1) {
      const delay = b * 45;   // 버스트 간 시간차 0.75초 (frame, 60fps 기준)
      const cx = canvas.width * (0.2 + Math.random() * 0.6);
      const cy = canvas.height * (0.15 + Math.random() * 0.35);
      for (let i = 0; i < 80; i += 1) {
        const a = (Math.PI * 2 * i) / 80 + Math.random() * 0.2;
        const v = 2.5 + Math.random() * 5;
        parts.push({
          delay, x: cx, y: cy, vx: Math.cos(a) * v, vy: Math.sin(a) * v,
          life: 90 + Math.random() * 50, size: 2.5 + Math.random() * 2.5,
          c: colors[(Math.random() * colors.length) | 0],
        });
      }
    }
    let raf;
    let frame = 0;
    const tick = () => {
      frame += 1;
      // 전체 지우기 대신 저알파 페이드 → 꼬리(잔상) 효과
      ctx.globalCompositeOperation = 'destination-out';
      ctx.fillStyle = 'rgba(0,0,0,0.16)';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.globalCompositeOperation = 'source-over';
      let alive = false;
      for (const p of parts) {
        if (frame < p.delay) { alive = true; continue; }
        if (p.life <= 0) continue;
        alive = true;
        p.x += p.vx; p.y += p.vy; p.vy += 0.05; p.vx *= 0.992; p.life -= 1;
        ctx.globalAlpha = Math.min(Math.max(p.life / 110, 0), 1);
        ctx.fillStyle = p.c;
        ctx.fillRect(p.x, p.y, p.size, p.size);
      }
      ctx.globalAlpha = 1;
      if (alive) raf = requestAnimationFrame(tick);
      else ctx.clearRect(0, 0, canvas.width, canvas.height);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [trigger]);
  if (!trigger) return null;
  return <canvas ref={ref} style={{ position: 'fixed', inset: 0, pointerEvents: 'none', zIndex: 9999 }} />;
}

export default function ViArbPanel() {
  const [connected, setConnected] = useState(false);
  const [mode, setMode] = useState('');
  const [params, setParams] = useState(null);
  const [opps, setOpps] = useState([]);     // opportunity=1 스프레드 틱
  const [events, setEvents] = useState([]); // VI 발동/해제/재개 로그
  const [stats, setStats] = useState({ vi: 0, opp: 0, ticks: 0, buys: 0 });
  const [sim, setSim] = useState({ fills: 0, wins: 0, pnl: 0 }); // Phase2 모의 체결
  const [dir, setDir] = useState('+'); // VI 방향 필터 기본=상방. all | + (상방) | - (하방)
  const [bal, setBal] = useState(null);  // 모의계좌 잔고 (kt00004)
  const [dirByCode, setDirByCode] = useState({}); // 종목코드 → VI 방향(+/-) (이벤트서 누적)
  const [buyDirs, setBuyDirs] = useState({});     // 오늘 매수 종목 → 매수 시점 VI 방향 (서버 영속, 새로고침 유지)
  const [trading, setTrading] = useState(false);  // 모의주문 시작/종료 토글
  const [budget, setBudget] = useState(0);         // 목표 매수 원금(원). 0=무제한
  const [minMcap, setMinMcap] = useState(0);       // VI 매수 시총 하한(억원). 0=필터 없음
  const [invested, setInvested] = useState(0);     // 현재 매수원금(서버 동기화)
  const wsRef = useRef(null);
  const retryRef = useRef(null);
  // 지정가 매도 체결 알림 (토스트 + 폭죽)
  const [toasts, setToasts] = useState([]);
  const [burst, setBurst] = useState(0);
  const limitSellsRef = useRef({});   // WS 핸들러(1회 마운트 클로저)에서 최신 등록 상태 조회용
  useEffect(() => { limitSellsRef.current = bal?.limit_sells || {}; }, [bal]);

  // 모의계좌 잔고 폴링 (15초 + 체결 시 갱신)
  useEffect(() => {
    let stop = false;
    const fetchBal = async () => {
      try {
        const r = await fetch('/api/vi-arb/balance');
        const b = await r.json();
        if (!stop && b.ok) setBal(b);
      } catch { /* noop */ }
    };
    fetchBal();
    const t = setInterval(fetchBal, 15000);
    return () => { stop = true; clearInterval(t); };
  }, []);

  // 모의주문 제어 서버 동기화 — 초기 1회 + 15초 폴링 (서버 재시작/다른 탭 변경도 반영)
  useEffect(() => {
    let stop = false;
    const sync = () => fetch('/api/vi-arb/order-control')
      .then((r) => r.json())
      .then((s) => {
        if (stop || !s) return;
        if (typeof s.enabled === 'boolean') setTrading(s.enabled);
        if (s.dir === 'all' || s.dir === '+' || s.dir === '-') setDir(s.dir);
        if (typeof s.invested === 'number') setInvested(s.invested);
        // 목표 매수원금/시총 하한: 입력 중(포커스)일 때는 덮어쓰지 않음
        if (typeof s.budget === 'number' && document.activeElement?.dataset?.budgetInput !== '1') {
          setBudget(s.budget);
        }
        if (typeof s.min_mcap === 'number' && document.activeElement?.dataset?.mcapInput !== '1') {
          setMinMcap(s.min_mcap);
        }
      })
      .catch(() => {});
    sync();
    const t = setInterval(sync, 15000);
    return () => { stop = true; clearInterval(t); };
  }, []);

  useEffect(() => {
    let closed = false;

    const connect = () => {
      const ws = new WebSocket(wsUrl());
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!closed) retryRef.current = setTimeout(connect, 2000); // 자동 재접속
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (e) => {
        let m;
        try { m = JSON.parse(e.data); } catch { return; }
        // 종목별 VI 방향 누적 (매수 보유종목에 +/- 표시용)
        if (m.code && (m.direction === '+' || m.direction === '-')) {
          setDirByCode((d) => (d[m.code] === m.direction ? d : { ...d, [m.code]: m.direction }));
        }
        if (m.type === 'hello') {
          setMode(m.mode); setParams(m.params);
          if (m.buy_dirs) setBuyDirs((d) => ({ ...m.buy_dirs, ...d }));
          // 당일 카운터 서버 복원 (vi_arb.db 집계) — 새로고침/재접속에도 유지
          if (m.stats) {
            setStats({ vi: m.stats.vi || 0, opp: m.stats.opp || 0, ticks: m.stats.ticks || 0, buys: m.stats.buys || 0 });
            if (m.stats.sim) setSim({ fills: m.stats.sim.fills || 0, wins: m.stats.sim.wins || 0, pnl: m.stats.sim.pnl || 0 });
          }
        } else if (m.type === 'vi') {
          setEvents((p) => [{ ...m, id: `${m.code}-${m.ts}` }, ...p].slice(0, 40));
          if (m.kind === '발동') setStats((s) => ({ ...s, vi: s.vi + 1 }));
        } else if (m.type === 'krx_resume') {
          setEvents((p) => [{ ...m, id: `${m.code}-${m.ts}-r` }, ...p].slice(0, 40));
        } else if (m.type === 'spread') {
          setStats((s) => ({ ...s, ticks: s.ticks + 1, opp: s.opp + (m.opportunity ? 1 : 0) }));
          if (m.opportunity) {
            setOpps((p) => [{ ...m, id: `${m.code}-${m.ts}` }, ...p].slice(0, 60));
          }
        } else if (m.type === 'sim_fill') {
          setSim((s) => ({ fills: s.fills + 1, wins: s.wins + (m.win ? 1 : 0), pnl: s.pnl + (m.net || 0) }));
          setEvents((p) => [{ ...m, id: `${m.code}-${m.ts}-f`, kind: 'sim' }, ...p].slice(0, 40));
        } else if (m.type === 'order') {
          setEvents((p) => [{ ...m, id: `${m.code}-${m.ts}-o`, kind: 'order' }, ...p].slice(0, 40));
          // 매수 주문 접수 성공 → 매수 횟수 카운트 + 매수 시점 VI 방향 고정 (배지용)
          if (m.ok && m.side !== '매도') {
            setStats((s) => ({ ...s, buys: s.buys + 1 }));
            if (m.direction) setBuyDirs((d) => ({ ...d, [m.code]: m.direction }));
          }
        } else if (m.type === 'order_fill') {
          setEvents((p) => [{ ...m, id: `${m.code}-${m.ts}-${m.status}-of`, kind: 'order_fill' }, ...p].slice(0, 40));
          // 체결 토스트 + 폭죽 🎆 (매수/지정가 매도)
          const pushToast = (title, color) => {
            const tid = `${m.code}-${m.ts}-${m.side}-toast`;
            setToasts((p) => [...p, {
              id: tid, title, color,
              text: `${m.name || m.code} ${m.fill_qty}주 @${fmt(m.fill_price)}원 체결`,
            }]);
            // 5.5초 표시 → 1.5초 페이드아웃 → 제거
            setTimeout(() => setToasts((p) => p.map((x) => (x.id === tid ? { ...x, fading: true } : x))), 5500);
            setTimeout(() => setToasts((p) => p.filter((x) => x.id !== tid)), 7000);
            setBurst((b) => b + 1);
          };
          if (m.side === '매수' && (m.fill_qty || 0) > 0) pushToast('⚡ VI 매수 체결!', '#E53935');
          // 매도 체결 → 보유종목에서 실시간 차감/제거 (WSS 이벤트 기반, 폴링 기다리지 않음)
          if (m.side === '매도' && (m.fill_qty || 0) > 0) {
            // 등록된 지정가 매도 체결 → 토스트 + 폭죽
            if (limitSellsRef.current[m.code]) pushToast('🎉 지정가 매도 체결!', '#1E88E5');
            setBal((b) => {
              if (!b || !b.holdings) return b;
              const holdings = b.holdings
                .map((h) => (h.code === m.code ? { ...h, qty: h.qty - m.fill_qty } : h))
                .filter((h) => h.qty > 0);
              return { ...b, holdings };
            });
            setPendingSell((s) => { const n = new Set(s); n.delete(m.code); return n; });
          }
        }
      };
    };

    connect();
    return () => {
      closed = true;
      clearTimeout(retryRef.current);
      wsRef.current?.close();
    };
  }, []);

  const tradeVerb = dir === '+' ? '매수' : dir === '-' ? '매도' : '매수·매도';
  const postOrderControl = (enabled, d, b = budget, m = minMcap) => {
    fetch('/api/vi-arb/order-control', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled, dir: d, budget: b, min_mcap: m }),
    })
      .then((r) => r.json())
      .then((s) => {
        if (s && typeof s.budget === 'number') setBudget(s.budget);
        if (s && typeof s.min_mcap === 'number') setMinMcap(s.min_mcap);
      })
      .catch(() => {});
  };
  const toggleTrading = () => {
    const next = !trading;
    setTrading(next);
    postOrderControl(next, dir);
  };
  const applyBudget = (won) => {
    setBudget(won);
    postOrderControl(trading, dir, won);
  };
  const applyMinMcap = (eok) => {
    setMinMcap(eok);
    postOrderControl(trading, dir, budget, eok);
  };
  const [selling, setSelling] = useState(false);
  const [sellingCode, setSellingCode] = useState(null); // 개별 매도 진행중 종목
  const [sellProgress, setSellProgress] = useState(null); // 일괄매도 진행률 0~100 (null=숨김)
  const [pendingSell, setPendingSell] = useState(() => new Set()); // 매도 접수돼 체결 대기중 종목코드
  const refreshBal = () => fetch('/api/vi-arb/balance').then((r) => r.json())
    .then((b) => { if (b && b.ok) setBal(b); }).catch(() => {});
  // 추천 매도가 지정가 매도 등록/취소
  const [limitBusy, setLimitBusy] = useState(null); // 처리중 종목코드
  const postLimitSell = (path, body, code) => {
    setLimitBusy(code);
    fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then((r) => r.json())
      .then((res) => {
        if (res.limit_sells) setBal((b) => (b ? { ...b, limit_sells: res.limit_sells } : b));
        if (!res.ok && res.reason) window.alert(`지정가 매도 실패: ${res.reason}`);
      })
      .catch(() => {})
      .finally(() => setLimitBusy(null));
  };
  const registerLimitSell = (h) => {
    if (!h.sell_target || limitBusy) return;
    postLimitSell('/api/vi-arb/sell-limit', { code: h.code, price: h.sell_target, qty: h.qty }, h.code);
  };
  const cancelLimitSell = (h) => {
    if (limitBusy) return;
    postLimitSell('/api/vi-arb/sell-limit/cancel', { code: h.code }, h.code);
  };
  // 일괄 지정가 매도 — 세후 수익률 ≥ 필터% 인 미등록 종목 전부 추천가로 등록
  const [bulkPct, setBulkPct] = useState(7);
  const [bulkBusy, setBulkBusy] = useState(false);
  const bulkLimitSell = () => {
    if (bulkBusy) return;
    const cand = (bal?.holdings || []).filter((h) =>
      h.sell_target && (h.sell_target_rt ?? -1) >= bulkPct && !bal?.limit_sells?.[h.code]);
    if (!cand.length) { window.alert(`세후 수익률 +${bulkPct}% 이상인 미등록 종목이 없습니다.`); return; }
    if (!window.confirm(`세후 수익률 +${bulkPct}% 이상 ${cand.length}종목을 추천 매도가로 일괄 지정가매도 등록할까요?\n\n${cand.map((h) => `· ${h.name} ${h.qty}주 @${fmt(h.sell_target)} (+${h.sell_target_rt}%)`).join('\n')}`)) return;
    setBulkBusy(true);
    fetch('/api/vi-arb/sell-limit/bulk', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ min_rt: bulkPct }),
    })
      .then((r) => r.json())
      .then((res) => {
        if (res.limit_sells) setBal((b) => (b ? { ...b, limit_sells: res.limit_sells } : b));
        if (res.ok) {
          const fail = (res.results || []).filter((x) => !x.ok);
          window.alert(`일괄 지정가매도: ${res.registered}/${res.total}종목 등록 완료${fail.length ? `\n실패: ${fail.map((f) => `${f.name}(${f.reason})`).join(', ')}` : ''}`);
        } else if (res.reason) {
          window.alert(`일괄 지정가매도 실패: ${res.reason}`);
        }
      })
      .catch(() => {})
      .finally(() => setBulkBusy(false));
  };
  const sellAll = async () => {
    if (selling) return;
    const lsCodes = Object.keys(bal?.limit_sells || {});
    const lsWarn = lsCodes.length
      ? `\n\n⚠️ 지정가 매도가 등록된 종목 ${lsCodes.length}개가 있습니다.`
        + '\n지정가 매도가 걸린 수량은 묶여 있으므로, 해당 종목은 먼저 취소해야 합니다'
        + ' — 안 그러면 잔량 부족으로 거부될 수 있습니다.'
      : '';
    if (!window.confirm(`모의계좌 전 보유종목을 시장가로 일괄매도할까요?${lsWarn}`)) return;
    setSelling(true);
    setSellProgress(0);
    // 일괄매도 등록 → 전 보유종목 버튼 즉시 '매도중' 표시
    setPendingSell(new Set((bal?.holdings || []).map((h) => h.code)));
    // 서버가 종목당 ~0.3s throttle → 총 소요 추정해 진행바 애니메이션 (응답 전 95%까지)
    const total = bal?.holdings?.length || 1;
    const estMs = total * 350;
    const start = Date.now();
    const timer = setInterval(() => {
      setSellProgress(Math.min(95, ((Date.now() - start) / estMs) * 100));
    }, 200);
    try {
      const r = await fetch('/api/vi-arb/sell-all', { method: 'POST' });
      const d = await r.json();
      clearInterval(timer);
      setSellProgress(100);
      // 접수 성공분만 '매도중' 유지 (실패분은 버튼 복구)
      if (d.results) setPendingSell(new Set(d.results.filter((x) => x.ok).map((x) => x.code)));
      window.alert(d.ok ? `일괄매도 접수: ${d.sold}/${d.total} 종목` : `일괄매도 실패: ${d.reason || '오류'}`);
      refreshBal();
    } catch {
      clearInterval(timer);
      setPendingSell(new Set());
      window.alert('일괄매도 요청 실패');
    } finally {
      setSelling(false);
      setTimeout(() => setSellProgress(null), 800);
    }
  };
  const sellOne = async (h) => {
    if (sellingCode) return;
    if (!window.confirm(`${h.name}(${h.code}) ${fmt(h.qty)}주를 시장가로 매도할까요?`)) return;
    setSellingCode(h.code);
    try {
      const r = await fetch('/api/vi-arb/sell', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: h.code, qty: h.qty }),
      });
      const d = await r.json();
      if (d.ok) setPendingSell((s) => new Set(s).add(h.code));
      window.alert(d.ok ? `${h.name} 매도 접수 (주문 #${d.ord_no})` : `매도 실패: ${d.reason || '오류'}`);
      refreshBal();
    } catch {
      window.alert('매도 요청 실패');
    } finally {
      setSellingCode(null);
    }
  };
  // 거래중 방향 필터 변경 시 스코프 재전송
  useEffect(() => {
    if (trading) postOrderControl(true, dir);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dir]);

  const match = (x) => dir === 'all' || x.direction === dir;
  const fOpps = opps.filter(match);
  const fEvents = events.filter(match);

  // 보유종목 합계 (평가손익·세후순손익·매수원금) + 전체 수익률
  const holdings = bal?.holdings || [];
  const holdTotals = holdings.reduce((a, h) => {
    const nr = netAfterCost(h, params);
    const evlt = h.evlt || h.cur * h.qty;
    const basis = (evlt - h.pl) || (h.avg * h.qty);
    a.pl += h.pl || 0;
    a.net += nr ? nr.net : 0;
    a.basis += basis || 0;
    return a;
  }, { pl: 0, net: 0, basis: 0 });
  const totalPlRate = holdTotals.basis ? (holdTotals.pl / holdTotals.basis) * 100 : 0;
  const totalNetRate = holdTotals.basis ? (holdTotals.net / holdTotals.basis) * 100 : 0;

  return (
    <div className="vi-arb">
      <Fireworks trigger={burst} />
      {toasts.length > 0 && (
        <div style={{
          position: 'fixed', top: 16, left: '50%', transform: 'translateX(-50%)', zIndex: 10000,
          display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8,
        }}>
          {toasts.map((t) => (
            <div key={t.id} style={{
              background: 'rgba(28,28,30,.96)', border: `1px solid ${t.color || '#E53935'}`, borderRadius: 8,
              padding: '10px 14px', color: '#fff', minWidth: 240,
              boxShadow: '0 4px 16px rgba(0,0,0,.45)',
              opacity: t.fading ? 0 : 1, transition: 'opacity 1.5s ease',   // 페이드아웃
            }}>
              <div style={{ fontWeight: 700, fontSize: 14 }}>{t.title || '🎉 체결!'}</div>
              <div style={{ fontSize: 13, marginTop: 3 }}>{t.text}</div>
            </div>
          ))}
        </div>
      )}
      <div className="vi-arb-head">
        <div>
          <h2 style={{ margin: 0, fontSize: 20 }}>⚡ VI 랜덤엔드 차익거래 관측</h2>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
            KRX×NXT 변동성완화장치 재개 시점 불일치 구간 실시간 관측 ·
            <span style={{ color: 'var(--text-muted)' }}> 관측 전용 (주문 없음)</span>
          </p>
        </div>
        <div className={`vi-status ${connected ? 'on' : 'off'}`}>
          <span className="vi-dot" />
          {connected ? `실시간 연결됨${mode ? ` · ${mode}` : ''}` : '연결 끊김 — 재시도 중'}
        </div>
      </div>

      <div className="vi-controls">
        <div className="vi-filter" role="group" aria-label="VI 방향 필터">
          {[['all', '전체'], ['+', '▲ 상방 VI'], ['-', '▼ 하방 VI']].map(([v, label]) => (
            <button
              key={v}
              className={`vi-filter-btn ${dir === v ? 'active' : ''} ${v === '+' ? 'up' : v === '-' ? 'down' : ''}`}
              onClick={() => { setDir(v); postOrderControl(trading, v); }}
            >
              {label}
            </button>
          ))}
          <label style={{ marginLeft: 10, display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: 'var(--text-muted)' }}>
            목표 매수원금
            <input
              type="text" inputMode="numeric" data-budget-input="1"
              defaultValue={budget ? budget.toLocaleString() : ''}
              key={budget}
              onChange={(e) => { const raw = e.target.value.replace(/[^0-9]/g, ''); e.target.value = raw ? Number(raw).toLocaleString() : ''; }}
              onBlur={(e) => applyBudget(Number(e.target.value.replace(/,/g, '')) || 0)}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.currentTarget.blur(); } }}
              placeholder="0=무제한"
              style={{ width: 140, padding: '5px 8px', borderRadius: 5, border: '1px solid var(--border, #444)', background: 'var(--card, #1a1a1a)', color: 'inherit', fontSize: 13, textAlign: 'right' }}
            />
            원
          </label>
          <label style={{ marginLeft: 10, display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: 'var(--text-muted)' }}
            title="VI 발동 종목의 시가총액이 이 값 미만이면 매수 스킵 (유동성 보호)">
            시총
            <input
              type="text" inputMode="numeric" data-mcap-input="1"
              defaultValue={minMcap ? minMcap.toLocaleString() : ''}
              key={minMcap}
              onChange={(e) => { const raw = e.target.value.replace(/[^0-9]/g, ''); e.target.value = raw ? Number(raw).toLocaleString() : ''; }}
              onBlur={(e) => applyMinMcap(Number(e.target.value.replace(/,/g, '')) || 0)}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.currentTarget.blur(); } }}
              placeholder="0=제한없음"
              style={{ width: 90, padding: '5px 8px', borderRadius: 5, border: '1px solid var(--border, #444)', background: 'var(--card, #1a1a1a)', color: 'inherit', fontSize: 13, textAlign: 'right' }}
            />
            억 이상
          </label>
        </div>
        <button
          className="vi-clear"
          onClick={() => { setOpps([]); setEvents([]); setStats({ vi: 0, opp: 0, ticks: 0, buys: 0 }); setSim({ fills: 0, wins: 0, pnl: 0 }); }}
          title="기회 포착·VI 이벤트 로그 전체 비우기"
        >
          🗑 전체 비우기
        </button>
      </div>

      <div className="vi-controls" style={{ marginTop: 8 }}>
        <button
          className={`vi-trade-toggle ${trading ? 'on' : ''}`}
          onClick={toggleTrading}
          title={`선택된 필터(${dir === 'all' ? '전체' : dir === '+' ? '상방' : '하방'}) 기준 모의주문 ${trading ? '종료' : '시작'}`}
          style={{
            padding: '8px 20px', borderRadius: 6, fontWeight: 700, fontSize: 14,
            border: 'none', cursor: 'pointer', color: '#fff',
            background: trading ? '#E53935' : '#2e7d32',
          }}
        >
          {trading ? `■ ${tradeVerb} 종료` : `▶ ${tradeVerb} 시작`}
        </button>
        <span style={{ marginLeft: 12, fontSize: 12, color: 'var(--text-muted)' }}>
          매수원금 <b style={{ color: 'inherit' }}>{fmt(bal?.buy_amount ?? invested)}원</b>
          {budget ? <> / 목표 {fmt(budget)}원 {(bal?.buy_amount ?? invested) >= budget && <span style={{ color: '#E53935' }}>· 목표도달, 매수중단</span>}</> : ' (무제한)'}
        </span>
      </div>

      {bal && (
        <div className="vi-balance">
          <span className="vi-bal-acct">🏦 모의계좌 {bal.account}</span>
          <div className="vi-bal-item"><span>예수금</span><b>{fmt(bal.deposit)}원</b></div>
          <div className="vi-bal-item"><span>예탁자산평가</span><b>{fmt(bal.asset_value)}원</b></div>
          <div className="vi-bal-item">
            <span>평가손익 (미실현)</span>
            <b style={{ color: (bal.eval_pl || 0) >= 0 ? '#E53935' : '#1E88E5' }}>
              {(bal.eval_pl || 0) >= 0 ? '+' : ''}{fmt(bal.eval_pl)}원 ({(bal.eval_pl_rt || 0) >= 0 ? '+' : ''}{bal.eval_pl_rt}%)
            </b>
          </div>
          <div className="vi-bal-item" title={`누적 실현손익 ${(bal.realized_pl || 0) >= 0 ? '+' : ''}${fmt(bal.realized_pl)}원 (${(bal.realized_pl_rt || 0) >= 0 ? '+' : ''}${bal.realized_pl_rt}%)`}>
            <span>실현손익 (오늘)</span>
            <b style={{ color: (bal.realized_pl_today ?? 0) >= 0 ? '#E53935' : '#1E88E5' }}>
              {(bal.realized_pl_today ?? 0) >= 0 ? '+' : ''}{fmt(bal.realized_pl_today ?? 0)}원
              {bal.buy_amount > 0 && (
                <> ({(bal.realized_pl_today ?? 0) >= 0 ? '+' : ''}{(((bal.realized_pl_today ?? 0) / bal.buy_amount) * 100).toFixed(2)}%)</>
              )}
            </b>
          </div>
          <div className="vi-bal-item"><span>보유종목</span><b>{bal.holdings?.length || 0}종목</b></div>
        </div>
      )}

      <div className="vi-stats">
        <div className="vi-stat"><span>VI 발동</span><b>{stats.vi}</b></div>
        <div className="vi-stat"><span>기회 포착</span><b style={{ color: 'var(--up, #E53935)' }}>{stats.opp}</b></div>
        <div className="vi-stat"><span>스프레드 틱</span><b>{fmt(stats.ticks)}</b></div>
        <div className="vi-stat"><span>매수 횟수</span><b style={{ color: '#E53935' }}>{stats.buys}</b></div>
        <div className="vi-stat">
          <span>모의손익 (체결 {sim.fills} · 승 {sim.fills ? Math.round((sim.wins / sim.fills) * 100) : 0}%)</span>
          <b style={{ color: sim.pnl >= 0 ? '#E53935' : '#1E88E5' }}>{sim.pnl >= 0 ? '+' : ''}{fmt(sim.pnl)}원</b>
        </div>
        {params && (
          <div className="vi-stat vi-stat-params">
            <span>비용 파라미터</span>
            <b style={{ fontSize: 12 }}>세금 {params.TAX} · 수수료 {params.FEE} · 버퍼 {params.EDGE_BUFFER}</b>
          </div>
        )}
      </div>

      {(
        <div className="vi-card" style={{ marginBottom: 12 }}>
          <div className="vi-card-title">💼 모의 매수 보유 종목 · 세후 손익 (수수료+세금 포함) · {holdings.length}종목</div>
          {sellProgress != null && (
            <div style={{ margin: '0 0 8px' }}>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 3 }}>
                일괄매도 진행 중… {Math.round(sellProgress)}%
              </div>
              <div style={{ height: 6, background: 'rgba(255,255,255,.1)', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${sellProgress}%`, background: '#E53935', transition: 'width .2s' }} />
              </div>
            </div>
          )}
          <div className="vi-table-wrap">
            <table className="vi-table">
              <thead>
                <tr>
                  <th>종목</th><th>수량</th><th>평균단가</th><th>현재가</th>
                  <th title="당일 변동폭 기반 익절 목표 · 10분 갱신">추천 매도가</th>
                  <th>평가손익</th><th>순손익 (세후)</th><th>매도</th>
                </tr>
              </thead>
              <tbody>
                <tr style={{ background: 'rgba(255,255,255,.04)', fontWeight: 700 }}>
                  <td><b>총합</b><span className="vi-code">{holdings.length}종목</span></td>
                  <td>—</td>
                  <td colSpan={2}>매수원금 {fmt(holdTotals.basis)}</td>
                  <td>
                    <span style={{ whiteSpace: 'nowrap', fontWeight: 400, fontSize: 24 }}>
                      <input
                        type="number" step="0.5"
                        value={bulkPct}
                        onChange={(e) => setBulkPct(Number(e.target.value))}
                        title="세후 수익률 필터 (이 % 이상인 종목만 일괄 등록)"
                        style={{
                          width: 110, padding: '4px 6px', borderRadius: 4, fontSize: 26, textAlign: 'right',
                          border: '1px solid var(--border, #444)', background: 'var(--card, #1a1a1a)', color: 'inherit',
                        }}
                      />% ↑
                    </span>
                    <div style={{ marginTop: 3 }}>
                      <button
                        onClick={bulkLimitSell}
                        disabled={bulkBusy}
                        title={`세후 수익률 +${bulkPct}% 이상 미등록 종목을 추천 매도가로 일괄 지정가매도`}
                        style={{
                          padding: '2px 8px', borderRadius: 5, fontSize: 11, fontWeight: 700,
                          border: '1px solid #1E88E5', cursor: bulkBusy ? 'default' : 'pointer',
                          color: '#fff', background: '#1E88E5', opacity: bulkBusy ? 0.5 : 1,
                        }}
                      >
                        {bulkBusy ? '등록중…' : '일괄지정가매도'}
                      </button>
                    </div>
                  </td>
                  <td style={{ color: holdTotals.pl >= 0 ? '#E53935' : '#1E88E5' }}>
                    {holdTotals.pl >= 0 ? '+' : ''}{fmt(holdTotals.pl)} ({totalPlRate >= 0 ? '+' : ''}{totalPlRate.toFixed(2)}%)
                  </td>
                  <td style={{ color: holdTotals.net >= 0 ? '#E53935' : '#1E88E5' }}>
                    {holdTotals.net >= 0 ? '+' : ''}{fmt(holdTotals.net)}원 ({totalNetRate >= 0 ? '+' : ''}{totalNetRate.toFixed(2)}%)
                  </td>
                  <td>
                    <button
                      onClick={sellAll}
                      disabled={selling}
                      title="전 보유종목 시장가 일괄매도"
                      style={{
                        padding: '4px 10px', borderRadius: 5, fontWeight: 700, fontSize: 12,
                        border: '1px solid #E53935', cursor: selling ? 'default' : 'pointer',
                        color: '#fff', background: '#E53935', opacity: selling ? 0.5 : 1,
                      }}
                    >
                      {selling ? '매도 중…' : '💸 일괄매도'}
                    </button>
                  </td>
                </tr>
                {holdings.length === 0 && (
                  <tr><td colSpan={8} className="vi-empty">보유 종목 없음</td></tr>
                )}
                {holdings.map((h) => {
                  const nr = netAfterCost(h, params);
                  const sellBusy = sellingCode === h.code || pendingSell.has(h.code);
                  // 매수 시점 방향(영속) 우선 — 이후 반대 방향 VI 가 관측돼도 배지가 뒤집히지 않음
                  const hd = buyDirs[h.code] || dirByCode[h.code];
                  return (
                    <tr key={h.code}>
                      <td>
                        {hd && (
                          <span className={`vi-dir ${hd === '+' ? 'up' : 'down'}`}>
                            {hd === '+' ? '▲' : '▼'}
                          </span>
                        )}
                        <b>{h.name}</b><span className="vi-code">{h.code}</span>
                        {hd && (
                          <span style={{
                            marginLeft: 5, fontSize: 11, fontWeight: 700,
                            color: hd === '+' ? '#E53935' : '#1E88E5',
                          }}>VI{hd}</span>
                        )}
                      </td>
                      <td>{fmt(h.qty)}</td>
                      <td>{fmt(h.avg)}</td>
                      <td>{fmt(h.cur)}</td>
                      <td title="max(세후 손익분기, 현재가+당일변동폭×0.5) · 상한가 캡 · 10분 갱신 · %는 평단 대비 세후(세금·수수료 차감)">
                        {h.sell_target ? (
                          <>
                            {/* 추천가가 현재가보다 높으면(미도달 익절 목표) 엣지 박스 강조 */}
                            <span style={h.sell_target > h.cur ? {
                              display: 'inline-block', padding: '1px 6px', borderRadius: 5,
                              border: '1px solid rgba(229,57,53,.55)', background: 'rgba(229,57,53,.08)',
                            } : undefined}>
                              <b>{fmt(h.sell_target)}</b>
                              <span style={{
                                marginLeft: 4, fontSize: 11,
                                color: (h.sell_target_rt ?? 0) > 0 ? '#E53935' : 'var(--text-muted)',
                              }}>
                                ({(h.sell_target_rt ?? 0) > 0 ? '+' : ''}{h.sell_target_rt}%)
                              </span>
                              {h.sell_target_kind === 'stoploss' && (
                                <span style={{ marginLeft: 4, fontSize: 10, fontWeight: 700, color: '#1E88E5' }}
                                  title="이월 보유 손실 -7% 이하 — 손실률 1/3 지점 반등 시 탈출 권고">손절</span>
                              )}
                            </span>
                            {(() => {
                              const ls = bal?.limit_sells?.[h.code];
                              const busy = limitBusy === h.code;
                              return (
                                <div style={{ marginTop: 3 }}>{/* 버튼은 가격 아래 2줄째 */}
                                  {ls ? (
                                    <button
                                      onClick={() => cancelLimitSell(h)}
                                      disabled={busy}
                                      title={`지정가 ${fmt(ls.price)}원 × ${ls.qty}주 매도 주문 취소`}
                                      style={{
                                        padding: '2px 8px', borderRadius: 5, fontSize: 11, fontWeight: 700,
                                        border: '1px solid #757575', cursor: busy ? 'default' : 'pointer',
                                        color: '#bbb', background: 'transparent', opacity: busy ? 0.5 : 1,
                                      }}
                                    >
                                      {busy ? '취소중…' : `✕ ${fmt(ls.price)} 취소`}
                                    </button>
                                  ) : (
                                    <button
                                      onClick={() => registerLimitSell(h)}
                                      disabled={busy}
                                      title={`${fmt(h.sell_target)}원 × ${h.qty}주 지정가 매도 등록 · 추천가 변경 시 10분 간격 자동 재조정`}
                                      style={{
                                        padding: '2px 8px', borderRadius: 5, fontSize: 11, fontWeight: 700,
                                        border: '1px solid #1E88E5', cursor: busy ? 'default' : 'pointer',
                                        color: '#1E88E5', background: 'transparent', opacity: busy ? 0.5 : 1,
                                      }}
                                    >
                                      {busy ? '등록중…' : '매도등록'}
                                    </button>
                                  )}
                                </div>
                              );
                            })()}
                          </>
                        ) : '-'}
                      </td>
                      <td style={{ color: h.pl >= 0 ? '#E53935' : '#1E88E5' }}>
                        {h.pl >= 0 ? '+' : ''}{fmt(h.pl)}{h.pl_rt !== '' ? ` (${h.pl_rt}%)` : ''}
                      </td>
                      <td style={{ color: nr && nr.net >= 0 ? '#E53935' : '#1E88E5', fontWeight: 700 }}>
                        {nr ? `${nr.net >= 0 ? '+' : ''}${fmt(nr.net)}원 (${nr.rate >= 0 ? '+' : ''}${nr.rate.toFixed(2)}%)` : '-'}
                      </td>
                      <td>
                        <button
                          onClick={() => sellOne(h)}
                          disabled={sellBusy}
                          title={`${h.name} 시장가 매도`}
                          style={{
                            padding: '3px 10px', borderRadius: 5, fontWeight: 700, fontSize: 12,
                            border: '1px solid #E53935', cursor: sellBusy ? 'default' : 'pointer',
                            color: sellBusy ? '#fff' : '#E53935',
                            background: sellBusy ? '#E53935' : 'transparent', opacity: sellBusy ? 0.7 : 1,
                          }}
                        >
                          {sellBusy ? '매도중' : '매도'}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="vi-grid">
        {/* 실시간 기회 피드 */}
        <div className="vi-card">
          <div className="vi-card-title">🎯 기회 포착 (opportunity = net &gt; 비용버퍼)</div>
          <div className="vi-table-wrap">
            <table className="vi-table">
              <thead>
                <tr>
                  <th>종목</th><th>VI후(s)</th><th>KRX가격</th><th>NXT가격</th>
                  <th>잔량</th><th>스프레드</th><th>순이익</th><th>최대수익%</th>
                </tr>
              </thead>
              <tbody>
                {fOpps.length === 0 && (
                  <tr><td colSpan={8} className="vi-empty">기회 대기 중…</td></tr>
                )}
                {fOpps.map((o) => (
                  <tr key={o.id} className="vi-opp-row">
                    <td>
                      <span className={`vi-dir ${o.direction === '+' ? 'up' : 'down'}`}>{o.direction === '+' ? '▲' : '▼'}</span>
                      <b>{o.name}</b>
                      {o.side && (
                        <span style={{
                          marginLeft: 5, fontSize: 11, fontWeight: 700, padding: '1px 5px', borderRadius: 4,
                          background: o.side === '매수' ? 'rgba(229,57,53,.15)' : 'rgba(30,136,229,.15)',
                          color: o.side === '매수' ? '#E53935' : '#1E88E5',
                        }}>NXT {o.side}</span>
                      )}
                      <span className="vi-code">{o.code}</span>
                    </td>
                    <td>{o.sec_since_vi}</td>
                    <td>{fmt(o.krx_expected)}</td>
                    <td>{fmt(o.nxt_best_ask)}</td>
                    <td>{fmt(o.nxt_ask_qty)}</td>
                    <td>{fmt(o.spread)}</td>
                    <td className="vi-net">+{fmt(o.net_spread)}<span className="vi-pct">+{o.net_pct?.toFixed(2)}%</span></td>
                    <td className="vi-max" title={`최초매수가 ${fmt(o.first_buy)} 기준`}>+{o.max_profit_pct?.toFixed(2)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* VI 이벤트 로그 */}
        <div className="vi-card">
          <div className="vi-card-title">📋 VI 이벤트 로그</div>
          <div className="vi-log">
            {fEvents.length === 0 && <div className="vi-empty">이벤트 대기 중…</div>}
            {fEvents.map((e) => (
              <div key={e.id} className="vi-log-row">
                <span className="vi-log-ts">{(e.ts || '').slice(11, 19)}</span>
                {e.kind === 'order' ? (
                  <span>
                    <span className={`vi-badge ${e.ok ? 'ord' : 'rel'}`}>모의계좌매수</span>
                    <b>{e.name}</b> <span className="vi-code">{e.code}</span>
                    {e.ok ? ` · 주문 #${e.ord_no}` : ` · 거부: ${e.reason}`}
                  </span>
                ) : e.kind === 'order_fill' ? (
                  <span>
                    <span className="vi-badge sim">체결</span>
                    <b>{e.name}</b> {e.side} {e.status} · {fmt(e.fill_qty)}/{fmt(e.ord_qty)}주 @ {fmt(e.fill_price)} <span className="vi-code">{e.exchange}</span>
                  </span>
                ) : e.kind === 'sim' ? (
                  <span>
                    <span className="vi-badge sim">모의체결</span>
                    <b>{e.name}</b> {e.qty}주 · {fmt(e.entry_buy)}→{fmt(e.krx_confirm)} ·{' '}
                    <b style={{ color: e.net >= 0 ? '#E53935' : '#1E88E5' }}>{e.net >= 0 ? '+' : ''}{fmt(e.net)}원 ({e.ret_pct}%)</b>
                  </span>
                ) : e.type === 'krx_resume' ? (
                  <span><b>{e.name}</b> KRX 재개 · 랜덤엔드 <b className="vi-re">{e.randomend_sec ?? '—'}s</b></span>
                ) : (
                  <span>
                    <span className={`vi-badge ${e.kind === '발동' ? 'trig' : 'rel'}`}>{e.kind}</span>
                    <span className={`vi-dir ${e.direction === '+' ? 'up' : 'down'}`}>{e.direction === '+' ? '▲' : '▼'}</span>
                    <b>{e.name}</b> <span className="vi-code">{e.code}</span>
                    {' '}<span className={`vi-stage ${e.gubun === '정적' ? 'static' : 'dynamic'}`}>{e.gubun} VI {e.direction}{e.vi_pct}%</span>
                    {' '}· 발동가 {fmt(e.trigger_price)}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
