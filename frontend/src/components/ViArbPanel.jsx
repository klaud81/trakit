import { useEffect, useRef, useState } from 'react';

// VI 차익거래 실시간 관측 대시보드 (rq-01).
// backend /api/ws/vi-arb WebSocket 스트림을 구독해 VI 발동·스프레드·랜덤엔드 재개를 표시.
// A단계: mock 피드. B단계에서 Kiwoom observer 로 데이터만 교체(스키마 동일).

function wsUrl() {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.host}/api/ws/vi-arb`;
}

const fmt = (n) => (n == null ? '-' : Number(n).toLocaleString());

export default function ViArbPanel() {
  const [connected, setConnected] = useState(false);
  const [mode, setMode] = useState('');
  const [params, setParams] = useState(null);
  const [opps, setOpps] = useState([]);     // opportunity=1 스프레드 틱
  const [events, setEvents] = useState([]); // VI 발동/해제/재개 로그
  const [stats, setStats] = useState({ vi: 0, opp: 0, ticks: 0 });
  const [sim, setSim] = useState({ fills: 0, wins: 0, pnl: 0 }); // Phase2 모의 체결
  const [dir, setDir] = useState('all'); // VI 방향 필터: all | + (상방) | - (하방)
  const wsRef = useRef(null);
  const retryRef = useRef(null);

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

  const match = (x) => dir === 'all' || x.direction === dir;
  const fOpps = opps.filter(match);
  const fEvents = events.filter(match);

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
      </div>

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

      <div className="vi-grid">
        {/* 실시간 기회 피드 */}
        <div className="vi-card">
          <div className="vi-card-title">🎯 기회 포착 (opportunity = net &gt; 비용버퍼)</div>
          <div className="vi-table-wrap">
            <table className="vi-table">
              <thead>
                <tr>
                  <th>종목</th><th>VI후(s)</th><th>KRX예상</th><th>NXT매도</th>
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
                      <b>{o.name}</b><span className="vi-code">{o.code}</span>
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
