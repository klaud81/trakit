import { useState } from 'react';

export default function Header({ portfolio, weekIdx, totalWeeks, onPrevWeek, onNextWeek }) {
  const weekNum = portfolio ? portfolio.week_num : '-';
  const dateRange = portfolio ? portfolio.date_range : '';
  const canPrev = weekIdx > 0;
  const canNext = weekIdx < totalWeeks - 1;
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    const text = '1005204834806';
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text);
    } else {
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

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
      <div className="header-right">
        <button className="sponsor-btn" onClick={handleCopy} title="우리은행 1005204834806 (주)스노우볼">
          ☕ {copied ? '복사됨!' : '후원하기'}
        </button>
      </div>
    </header>
  );
}
