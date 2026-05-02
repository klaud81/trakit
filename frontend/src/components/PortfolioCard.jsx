import { fmt, fmtUSD } from '../utils/format';

export default function PortfolioCard({ portfolio, signal, prevWeek, exchangeRate, tradePoints }) {
  if (!portfolio) return null;
  const signalType = signal ? signal.signal_type : 'HOLD';
  const rate = exchangeRate?.rate || 1400;
  const valKrw = Math.round(portfolio.valuation * rate);

  // 회차 매매: 이전 주차의 회차기록(executed_prices) × 이전 주차 시점의 거래단위로 표시
  // (= 현재 주차 시작 직전에 어떤 매매가 있었는지)
  const prevExecuted = prevWeek?.executed_prices || [];
  const prevShares = prevWeek?.shares || portfolio.shares;
  const sharesDelta = portfolio.shares - prevShares;
  const tradeDir = sharesDelta > 0 ? 'buy' : sharesDelta < 0 ? 'sell' : null;
  // 단위 = |shares delta| / 체결가 개수 (체결가가 N회면 회당 |delta|/N 주)
  const unit = (prevExecuted.length > 0 && sharesDelta !== 0)
    ? Math.round(Math.abs(sharesDelta) / prevExecuted.length)
    : 0;
  const tradeRounds = prevExecuted.length;
  const tradeUnits = Math.abs(sharesDelta);
  const tradeMoney = prevExecuted.reduce((s, p) => s + p * unit, 0);


  const vrColor = portfolio.vr_mode === '적립식 VR' ? '#2e7d32'
    : portfolio.vr_mode === '인출식 VR' ? '#c62828' : 'var(--text-muted)';
  return (
    <div className="card">
      <div className="card-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>Portfolio</span>
        {portfolio.vr_mode && (
          <span style={{ fontSize: '11px', fontWeight: 600, color: vrColor, padding: '2px 8px', borderRadius: '10px', border: `1px solid ${vrColor}` }}>
            {portfolio.vr_mode}
          </span>
        )}
      </div>
      <div className={`signal-badge signal-${signalType}`}>
        {signalType === 'BUY' ? '▼ 매수' : signalType === 'SELL' ? '▲ 매도' : '━ 홀드'}
      </div>
      <div className="portfolio-value">
        {fmtUSD(portfolio.valuation)}
        <span style={{ fontSize: '16px', color: 'var(--text-muted)', marginLeft: '8px', fontWeight: 500 }}>
          ({fmt(valKrw, 0)}원)
        </span>
      </div>
      <div className="portfolio-shares">
        {fmt(portfolio.shares, 0)}주 보유 · 평단 {fmtUSD(portfolio.avg_cost)}
        {tradeRounds > 0 && (
          <span className={tradeDir === 'buy' ? 'price-up' : 'price-down'} style={{ marginLeft: '8px', fontSize: '12px' }}>
            ({tradeDir === 'buy' ? '매수' : '매도'} {tradeRounds}회, 총 {tradeUnits}주 {tradeDir === 'buy' ? '매수' : '매도'}, 총거래액 {tradeDir === 'buy' ? '-' : '+'}{fmtUSD(tradeMoney)})
          </span>
        )}
        <span style={{ marginLeft: '8px', fontSize: '11px', color: 'var(--text-muted)' }}>
          환율 {fmt(rate, 0)}원
        </span>
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
