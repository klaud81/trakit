import { fmt, fmtPct, fmtUSD } from '../utils/format';

export default function SignalPanel({ signal, portfolio, livePrice, priceRefreshing, tradePoints, isLastWeek }) {
  if (!signal) return null;
  const buyPrice = tradePoints?.buy_table?.rows?.[0]?.price || 0;
  const sellPrice = tradePoints?.sell_table?.rows?.[0]?.price || 0;

  const avgCost = portfolio?.avg_cost || 0;
  const currentPrice = (isLastWeek && livePrice?.price > 0) ? livePrice.price : (portfolio?.price || 0);
  const profitPerShare = avgCost > 0 ? currentPrice - avgCost : 0;
  const profitPct = avgCost > 0 ? (profitPerShare / avgCost * 100) : 0;
  const totalProfit = profitPerShare * (portfolio?.shares || 0);
  const borderColor =
    signal.signal_type === 'BUY' ? 'var(--buy)' :
    signal.signal_type === 'SELL' ? 'var(--sell)' : 'var(--hold)';

  const hasLive = livePrice && livePrice.price > 0;

  return (
    <div className="card" style={{ borderColor }}>
      <div className="card-title">Signal</div>
      {hasLive && (
        <div className="price-bar" style={{ margin: '0 0 8px 0' }}>
          <span className={`price-bar-refresh${priceRefreshing ? ' spinning' : ''}`} title="30초마다 자동 갱신">&#x21bb;</span>
          <span className="price-bar-symbol">실시간 TQQQ</span>
          <span className={`price-bar-price ${livePrice.change >= 0 ? 'price-up' : 'price-down'}`}>
            ${fmt(livePrice.price)}
          </span>
          <span className={livePrice.change >= 0 ? 'price-up' : 'price-down'}>
            {livePrice.change >= 0 ? '+' : ''}{fmt(livePrice.change)} ({fmtPct(livePrice.change_pct)})
          </span>
          {livePrice.market_open === false && (
            <span className="price-bar-closed">closed</span>
          )}
        </div>
      )}
      <div style={{ fontSize: '14px', lineHeight: '1.6', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
        <span>{signal.recommendation}</span>
        {avgCost > 0 && (
          <span className={totalProfit >= 0 ? 'price-up' : 'price-down'} style={{ fontWeight: 600 }}>
            {totalProfit >= 0 ? '+' : ''}{fmtUSD(totalProfit)} ({profitPct >= 0 ? '+' : ''}{fmtPct(profitPct)})
          </span>
        )}
      </div>
      <div style={{ marginTop: '12px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '12px' }}>
        <div>
          <span style={{ color: 'var(--text-muted)' }}>매수까지: </span>
          <span style={{ color: 'var(--buy)' }}>{fmtUSD(buyPrice)}/주</span>
        </div>
        <div>
          <span style={{ color: 'var(--text-muted)' }}>매도까지: </span>
          <span style={{ color: 'var(--sell)' }}>{fmtUSD(sellPrice)}/주</span>
        </div>
      </div>
    </div>
  );
}
