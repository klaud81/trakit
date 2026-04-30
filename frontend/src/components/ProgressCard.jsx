import { useMemo } from 'react';
import { fmt, fmtPct } from '../utils/format';

const CONTRIBUTION = 200;
const GOAL_WEEK = 560;
const RATIO_ODD = 1.03;
const RATIO_EVEN = 1.0;

// 계획 V 누적: 매 cycle 마다 (V_prev + 200) × ratio (홀수 cycle=1.03, 짝수=1.0)
function buildPlannedTrajectory(maxCycles) {
  const arr = [0];
  let v = 0;
  for (let i = 1; i <= maxCycles; i++) {
    v = (v + CONTRIBUTION) * (i % 2 === 1 ? RATIO_ODD : RATIO_EVEN);
    arr.push(v);
  }
  return arr;
}

export default function ProgressCard({ portfolio, remaining, exchangeRate }) {
  const trajectory = useMemo(() => buildPlannedTrajectory(GOAL_WEEK / 2 + 100), []);

  if (!portfolio) return null;
  const pct = portfolio.goal_progress || 0;
  const rate = exchangeRate?.rate || 1400;
  const goalUsd = Math.round(1_000_000_000 / rate);

  const weekNum = parseInt(portfolio.week_num) || 0;
  const currentCycle = Math.floor(weekNum / 2);
  // goal_progress 퍼센트가 가리키는 달러 금액 = 계획 대비 비교용 실제값
  const actualUsd = (pct / 100) * goalUsd;
  const plannedNow = trajectory[currentCycle] || 0;
  const planPct = plannedNow > 0 ? (actualUsd / plannedNow) * 100 : 0;

  // 현재 actualUsd 가 계획상 도달하는 cycle 검색
  let targetCycle = trajectory.length - 1;
  for (let i = 0; i < trajectory.length; i++) {
    if (trajectory[i] >= actualUsd) { targetCycle = i; break; }
  }
  const weeksDiff = (targetCycle - currentCycle) * 2;
  const timeLabel = weeksDiff > 0
    ? `${weeksDiff}주 빠름`
    : weeksDiff < 0
      ? `${Math.abs(weeksDiff)}주 느림`
      : '계획대로';
  const timeColor = weeksDiff > 0 ? '#E53935' : weeksDiff < 0 ? '#1E88E5' : 'var(--text-muted)';

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
        <span>현재: {portfolio.week_num}주차</span>
        {remaining && (() => {
          const wkLeft = Math.max(0, GOAL_WEEK - weekNum);
          const yrs = Math.floor(wkLeft / 52);
          const wks = wkLeft % 52;
          const timeStr = yrs > 0 ? `${yrs}년 ${wks}주 남음` : `${wks}주 남음`;
          return <span>남은 횟수: {remaining.remaining_cycles}회 ({timeStr})</span>;
        })()}
        <span>목표: 560주차</span>
      </div>
      {plannedNow > 0 && (() => {
        const MAX_SCALE = 26; // ±26주(반년) 기준 풀스케일
        const clamped = Math.max(-MAX_SCALE, Math.min(MAX_SCALE, weeksDiff));
        const barPct = (Math.abs(clamped) / MAX_SCALE) * 50; // 0~50%
        const barLeft = weeksDiff >= 0 ? '50%' : `${50 - barPct}%`;
        return (
          <div style={{ marginTop: '10px', paddingTop: '10px', borderTop: '1px solid var(--border)' }}>
            <div style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              fontSize: '13px', flexWrap: 'wrap', gap: '6px', marginBottom: '8px',
            }}>
              <span style={{ color: 'var(--text-muted)' }}>
                계획 대비:{' '}
                <strong style={{ color: 'var(--text)' }}>{fmtPct(planPct)}</strong>
                <span style={{ marginLeft: '6px', fontSize: '12px' }}>
                  (${fmt(actualUsd, 0)} / ${fmt(plannedNow, 0)})
                </span>
              </span>
              <span style={{ color: timeColor, fontWeight: 700 }}>{timeLabel}</span>
            </div>
            {/* 시간 차이 막대: 중앙 기준 좌(느림, 파랑) / 우(빠름, 빨강) */}
            <div style={{
              position: 'relative', height: '10px',
              background: 'var(--border)', borderRadius: '5px',
            }}>
              <div style={{
                position: 'absolute', left: barLeft, width: `${barPct}%`,
                top: 0, bottom: 0, background: timeColor, borderRadius: '5px',
                transition: 'left 0.3s, width 0.3s',
              }} />
              {/* 중앙 마커 */}
              <div style={{
                position: 'absolute', left: 'calc(50% - 1px)', top: '-3px',
                width: '2px', height: '16px', background: 'var(--text)',
                opacity: 0.6,
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
        );
      })()}
    </div>
  );
}
