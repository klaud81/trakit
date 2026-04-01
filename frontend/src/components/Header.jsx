export default function Header({ portfolio, weekIdx, totalWeeks, onPrevWeek, onNextWeek }) {
  const weekNum = portfolio ? portfolio.week_num : '-';
  const dateRange = portfolio ? portfolio.date_range : '';
  const canPrev = weekIdx > 0;
  const canNext = weekIdx < totalWeeks - 1;

  return (
    <header className="header">
      <div className="header-left">
        <div className="logo">TRAKIT</div>
        <div className="badge badge-week">
          <button className="week-nav-btn" onClick={onPrevWeek} disabled={!canPrev} title="이전 주차">
            ◀
          </button>
          <span className="week-label">{weekNum}주차{dateRange ? ` · ${dateRange}` : ''}</span>
          <button className="week-nav-btn" onClick={onNextWeek} disabled={!canNext} title="다음 주차">
            ▶
          </button>
        </div>
        <div className="badge badge-goal">GOAL: 560주차</div>
      </div>
    </header>
  );
}
