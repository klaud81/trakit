import { fmt, fmtUSD } from '../utils/format';

export default function PortfolioCard({ portfolio, signal }) {
  if (!portfolio) return null;
  const signalType = signal ? signal.signal_type : 'HOLD';

  return (
    <div className="card">
      <div className="card-title">Portfolio</div>
      <div className={`signal-badge signal-${signalType}`}>
        {signalType === 'BUY' ? '▼ 매수' : signalType === 'SELL' ? '▲ 매도' : '━ 홀드'}
      </div>
      <div className="portfolio-value">{fmtUSD(portfolio.valuation)}</div>
      <div className="portfolio-shares">
        {fmt(portfolio.shares, 0)}주 보유 · 평단 {fmtUSD(portfolio.avg_cost)}
      </div>
      <div className="portfolio-meta">
        <div className="meta-item">
          <label>Pool (가용 현금)</label>
          <div className="value">{fmtUSD(portfolio.pool)}</div>
        </div>
        <div className="meta-item">
          <label>Target (V)</label>
          <div className="value">{fmtUSD(portfolio.target_value)}</div>
        </div>
        <div className="meta-item">
          <label>Total Value</label>
          <div className="value" style={{ color: 'var(--primary)' }}>
            {fmtUSD(portfolio.total_value)}
          </div>
        </div>
      </div>
    </div>
  );
}
