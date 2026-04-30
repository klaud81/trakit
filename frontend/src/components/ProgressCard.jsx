import { useEffect, useState } from 'react';
import { fmt, fmtPct } from '../utils/format';
import { fetchApi } from '../utils/api';

export default function ProgressCard({ portfolio, exchangeRate, offset = 0 }) {
  const [goal, setGoal] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetchApi(`/goal?offset=${offset}`).then((data) => {
      if (!cancelled && data) setGoal(data);
    });
    return () => { cancelled = true; };
  }, [offset, portfolio?.week_num]);

  if (!portfolio || !goal) return null;

  const rate = goal.rate || exchangeRate?.rate || 1400;
  const goalUsd = goal.goal_usd || Math.round(1_000_000_000 / rate);
  const pct = goal.goal_progress || 0;
  const planPct = goal.plan_pct || 0;
  const weeksDiff = goal.weeks_diff || 0;
  const timeLabel = goal.time_label || '계획대로';
  const timeColor = weeksDiff > 0 ? '#E53935' : weeksDiff < 0 ? '#1E88E5' : 'var(--text-muted)';
  const remainingStr = goal.years_left > 0
    ? `${goal.years_left}년 ${goal.weeks_left_in_year}주 남음`
    : `${goal.weeks_left_in_year}주 남음`;

  const MAX_SCALE = 26;
  const clamped = Math.max(-MAX_SCALE, Math.min(MAX_SCALE, weeksDiff));
  const barPct = (Math.abs(clamped) / MAX_SCALE) * 50;
  const barLeft = weeksDiff >= 0 ? '50%' : `${50 - barPct}%`;

  return (
    <div className="card">
      <div className="card-title">Goal Progress</div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span style={{ fontSize: '28px', fontWeight: '700', color: 'var(--primary)' }}>{fmtPct(pct)}</span>
        <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>of 10억원 (${fmt(goalUsd, 0)}) · 환율 {fmt(rate, 0)}원</span>
      </div>
      <div className="progress-bar-bg">
        <div className="progress-bar-fill" style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      <div className="progress-info">
        <span>{offset === 0 ? '현재' : '조회'}: {goal.week_num}주차</span>
        <span>남은 횟수: {goal.remaining_cycles}회 ({remainingStr})</span>
        <span>목표: 560주차</span>
      </div>
      {goal.planned > 0 && (
        <div style={{ marginTop: '10px', paddingTop: '10px', borderTop: '1px solid var(--border)' }}>
          <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            fontSize: '13px', flexWrap: 'wrap', gap: '6px', marginBottom: '8px',
          }}>
            <span style={{ color: 'var(--text-muted)' }}>
              계획 대비:{' '}
              <strong style={{ color: 'var(--text)' }}>{fmtPct(planPct)}</strong>
              <span style={{ marginLeft: '6px', fontSize: '12px' }}>
                (${fmt(goal.actual_value, 0)} / ${fmt(goal.planned, 0)})
              </span>
            </span>
            <span style={{ color: timeColor, fontWeight: 700 }}>{timeLabel}</span>
          </div>
          <div style={{ position: 'relative', height: '10px', background: 'var(--border)', borderRadius: '5px' }}>
            <div style={{
              position: 'absolute', left: barLeft, width: `${barPct}%`,
              top: 0, bottom: 0, background: timeColor, borderRadius: '5px',
              transition: 'left 0.3s, width 0.3s',
            }} />
            <div style={{
              position: 'absolute', left: 'calc(50% - 1px)', top: '-3px',
              width: '2px', height: '16px', background: 'var(--text)', opacity: 0.6,
            }} />
          </div>
          <div style={{
            display: 'flex', justifyContent: 'space-between',
            fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px',
          }}>
            <span>← {MAX_SCALE}주 느림</span>
            <span>계획대로</span>
            <span>{MAX_SCALE}주 빠름 →</span>
          </div>
        </div>
      )}
    </div>
  );
}
