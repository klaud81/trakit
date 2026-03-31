import { fmtPct } from '../utils/format';

export default function ProgressCard({ portfolio, remaining }) {
  if (!portfolio) return null;
  const pct = portfolio.goal_progress || 0;

  return (
    <div className="card">
      <div className="card-title">Goal Progress</div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span style={{ fontSize: '28px', fontWeight: '700', color: 'var(--primary)' }}>{fmtPct(pct)}</span>
        <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>of 10억원 ($714,286)</span>
      </div>
      <div className="progress-bar-bg">
        <div className="progress-bar-fill" style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      <div className="progress-info">
        <span>현재: {portfolio.week_num}주차</span>
        {remaining && <span>남은 적립: {remaining.remaining_cycles}회</span>}
        <span>목표: 560주차</span>
      </div>
    </div>
  );
}
