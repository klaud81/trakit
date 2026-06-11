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

export default function ViArbPanel() {
  const [connected, setConnected] = useState(false);
  const [mode, setMode] = useState('');
  const [params, setParams] = useState(null);
  const [opps, setOpps] = useState([]);     // opportunity=1 스프레드 틱
  const [events, setEvents] = useState([]); // VI 발동/해제/재개 로그
  const [stats, setStats] = useState({ vi: 0, opp: 0, ticks: 0 });
  const [sim, setSim] = useState({ fills: 0, wins: 0, pnl: 0 }); // Phase2 모의 체결
  const [dir, setDir] = useState('+'); // VI 방향 필터 기본=상방. all | + (상방) | - (하방)
  const [bal, setBal] = useState(null);  // 모의계좌 잔고 (kt00004)
  const [dirByCode, setDirByCode] = useState({}); // 종목코드 → VI 방향(+/-) (이벤트서 누적)
  const [trading, setTrading] = useState(false);  // 모의주문 시작/종료 토글
  const wsRef = useRef(null);
  const retryRef = useRef(null);

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

  // 모의주문 제어 초기 상태 동기화 (서버가 env 기준으로 시작중일 수 있음)
  useEffect(() => {
    fetch('/api/vi-arb/order-control')
      .then((r) => r.json())
      .then((s) => { if (s && typeof s.enabled === 'boolean') setTrading(s.enabled); })
      .catch(() => {});
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
        } else if (m.type === 'order_fill') {
          setEvents((p) => [{ ...m, id: `${m.code}-${m.ts}-${m.status}-of`, kind: 'order_fill' }, ...p].slice(0, 40));
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
  const postOrderControl = (enabled, d) => {
    fetch('/api/vi-arb/order-control', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled, dir: d }),
    }).catch(() => {});
  };
  const toggleTrading = () => {
    const next = !trading;
    setTrading(next);
    postOrderControl(next, dir);
  };
  const [selling, setSelling] = useState(false);
  const [sellingCode, setSellingCode] = useState(null); // 개별 매도 진행중 종목
  const refreshBal = () => fetch('/api/vi-arb/balance').then((r) => r.json())
    .then((b) => { if (b && b.ok) setBal(b); }).catch(() => {});
  const sellAll = async () => {
    if (selling) return;
    if (!window.confirm('모의계좌 전 보유종목을 시장가로 일괄매도할까요?')) return;
    setSelling(true);
    try {
      const r = await fetch('/api/vi-arb/sell-all', { method: 'POST' });
      const d = await r.json();
      window.alert(d.ok ? `일괄매도 접수: ${d.sold}/${d.total} 종목` : `일괄매도 실패: ${d.reason || '오류'}`);
      refreshBal();
    } catch {
      window.alert('일괄매도 요청 실패');
    } finally {
      setSelling(false);
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
              onClick={() => setDir(v)}
            >
              {label}
            </button>
          ))}
          <button
            className={`vi-trade-toggle ${trading ? 'on' : ''}`}
            onClick={toggleTrading}
            title={`선택된 필터(${dir === 'all' ? '전체' : dir === '+' ? '상방' : '하방'}) 기준 모의주문 ${trading ? '종료' : '시작'}`}
            style={{
              marginLeft: 8, padding: '6px 14px', borderRadius: 6, fontWeight: 700, fontSize: 13,
              border: 'none', cursor: 'pointer', color: '#fff',
              background: trading ? '#E53935' : '#2e7d32',
            }}
          >
            {trading ? `■ ${tradeVerb} 종료` : `▶ ${tradeVerb} 시작`}
          </button>
        </div>
        <button
          className="vi-clear"
          onClick={() => { setOpps([]); setEvents([]); setStats({ vi: 0, opp: 0, ticks: 0 }); setSim({ fills: 0, wins: 0, pnl: 0 }); }}
          title="기회 포착·VI 이벤트 로그 전체 비우기"
        >
          🗑 전체 비우기
        </button>
      </div>

      {bal && (
        <div className="vi-balance">
          <span className="vi-bal-acct">🏦 모의계좌 {bal.account}</span>
          <div className="vi-bal-item"><span>예수금</span><b>{fmt(bal.deposit)}원</b></div>
          <div className="vi-bal-item"><span>예탁자산평가</span><b>{fmt(bal.asset_value)}원</b></div>
          <div className="vi-bal-item">
            <span>당일손익</span>
            <b style={{ color: bal.today_pl >= 0 ? '#E53935' : '#1E88E5' }}>
              {bal.today_pl >= 0 ? '+' : ''}{fmt(bal.today_pl)}원 ({bal.today_pl_rt}%)
            </b>
          </div>
          <div className="vi-bal-item"><span>보유종목</span><b>{bal.holdings?.length || 0}종목</b></div>
        </div>
      )}

      <div className="vi-stats">
        <div className="vi-stat"><span>VI 발동</span><b>{stats.vi}</b></div>
        <div className="vi-stat"><span>기회 포착</span><b style={{ color: 'var(--up, #E53935)' }}>{stats.opp}</b></div>
        <div className="vi-stat"><span>스프레드 틱</span><b>{fmt(stats.ticks)}</b></div>
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

      {bal?.holdings?.length > 0 && (
        <div className="vi-card" style={{ marginBottom: 12 }}>
          <div className="vi-card-title">💼 모의 매수 보유 종목 · 세후 손익 (수수료+세금 포함)</div>
          <div className="vi-table-wrap">
            <table className="vi-table">
              <thead>
                <tr>
                  <th>종목</th><th>수량</th><th>평균단가</th><th>현재가</th>
                  <th>평가손익</th><th>순손익 (세후)</th><th>매도</th>
                </tr>
              </thead>
              <tbody>
                <tr style={{ background: 'rgba(255,255,255,.04)', fontWeight: 700 }}>
                  <td><b>총합</b><span className="vi-code">{holdings.length}종목</span></td>
                  <td>—</td>
                  <td colSpan={2}>매수원금 {fmt(holdTotals.basis)}</td>
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
                {bal.holdings.map((h) => {
                  const nr = netAfterCost(h, params);
                  return (
                    <tr key={h.code}>
                      <td>
                        {dirByCode[h.code] && (
                          <span className={`vi-dir ${dirByCode[h.code] === '+' ? 'up' : 'down'}`}>
                            {dirByCode[h.code] === '+' ? '▲' : '▼'}
                          </span>
                        )}
                        <b>{h.name}</b><span className="vi-code">{h.code}</span>
                        {dirByCode[h.code] && (
                          <span style={{
                            marginLeft: 5, fontSize: 11, fontWeight: 700,
                            color: dirByCode[h.code] === '+' ? '#E53935' : '#1E88E5',
                          }}>VI{dirByCode[h.code]}</span>
                        )}
                      </td>
                      <td>{fmt(h.qty)}</td>
                      <td>{fmt(h.avg)}</td>
                      <td>{fmt(h.cur)}</td>
                      <td style={{ color: h.pl >= 0 ? '#E53935' : '#1E88E5' }}>
                        {h.pl >= 0 ? '+' : ''}{fmt(h.pl)}{h.pl_rt !== '' ? ` (${h.pl_rt}%)` : ''}
                      </td>
                      <td style={{ color: nr && nr.net >= 0 ? '#E53935' : '#1E88E5', fontWeight: 700 }}>
                        {nr ? `${nr.net >= 0 ? '+' : ''}${fmt(nr.net)}원 (${nr.rate >= 0 ? '+' : ''}${nr.rate.toFixed(2)}%)` : '-'}
                      </td>
                      <td>
                        <button
                          onClick={() => sellOne(h)}
                          disabled={sellingCode === h.code}
                          title={`${h.name} 시장가 매도`}
                          style={{
                            padding: '3px 10px', borderRadius: 5, fontWeight: 700, fontSize: 12,
                            border: '1px solid #E53935', cursor: sellingCode === h.code ? 'default' : 'pointer',
                            color: '#E53935', background: 'transparent', opacity: sellingCode === h.code ? 0.5 : 1,
                          }}
                        >
                          {sellingCode === h.code ? '…' : '매도'}
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
