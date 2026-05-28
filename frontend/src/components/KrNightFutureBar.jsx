import { useEffect, useState } from 'react';

/* KOSPI200 야간선물 실시간 바.
   - 야간장(KST 18:00~05:00): 10초 폴링 — 백엔드가 socket.io 로 받은 최신 tick 반환
   - 그 외 시간: 마지막 tick freeze (백엔드에서 session='closed' 로 표시) */

function fmt(n, d = 2) {
  if (n == null || isNaN(n)) return '—';
  return Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
}

export default function KrNightFutureBar({ className = '' }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const r = await fetch('/api/kr-night-future');
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        if (!cancelled) { setData(d); setErr(null); }
      } catch (e) {
        if (!cancelled) setErr(String(e.message || e));
      }
    };
    load();
    const id = setInterval(load, 10_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  if (!data || data.value == null) {
    return (
      <div className={`kr-night-future-bar ${className}`.trim()}>
        <span className="kr-nf-label">코스피200 야간선물</span>
        <span className="kr-nf-loading">{err ? '연결 실패' : '로딩 중…'}</span>
      </div>
    );
  }

  const isUp = (data.change_pct ?? 0) >= 0;
  const color = isUp ? '#E53935' : '#1E88E5';
  const sign = isUp ? '+' : '';
  const sessionLabel = data.session === 'night' ? '실시간' : '장종료';

  return (
    <div className={`kr-night-future-bar ${className}`.trim()}>
      <span className="kr-nf-label">코스피200 야간선물</span>
      <span className="kr-nf-price">{fmt(data.value)}</span>
      <span className="kr-nf-change" style={{ color }}>
        ({sign}{fmt(data.value_diff)}, {sign}{fmt(data.change_pct)}%)
      </span>
      <span className="kr-nf-session">{sessionLabel}</span>
    </div>
  );
}
