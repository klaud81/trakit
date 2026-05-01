import { fmt, fmtPct, fmtUSD } from '../utils/format';

export default function SignalPanel({ signal, livePrice, priceRefreshing, tradePoints, cycleTrade }) {
  if (!signal) return null;
  const unitSize = tradePoints?.unit_size;
  const profit = signal.profit;
  const profitPct = signal.profit_pct;
  const executedPrices = cycleTrade?.executed_prices || [];
  const tradeAmount = cycleTrade?.trade_amount || 0;
  const cycleDirection = tradeAmount > 0 ? '매도' : tradeAmount < 0 ? '매수' : null;
  const cycleColor = tradeAmount > 0 ? 'var(--sell)' : 'var(--buy)';
  // 이번 회차 체결가 적용: 이미 처리된 tier 제외하고 다음 tier 픽
  const allBuyRows = tradePoints?.buy_table?.rows || [];
  const allSellRows = tradePoints?.sell_table?.rows || [];
  const buyRows = (executedPrices.length > 0 && tradeAmount < 0)
    ? allBuyRows.filter((r) => r.price < Math.min(...executedPrices))
    : allBuyRows;
  const sellRows = (executedPrices.length > 0 && tradeAmount > 0)
    ? allSellRows.filter((r) => r.price > Math.max(...executedPrices))
    : allSellRows;
  const buyPrice = buyRows[0]?.price || 0;
  const sellPrice = sellRows[0]?.price || 0;
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
        {profit != null && (
          <span className={profit >= 0 ? 'price-up' : 'price-down'} style={{ fontWeight: 600 }}>
            {profit >= 0 ? '+' : ''}{fmtUSD(profit)} ({profitPct >= 0 ? '+' : ''}{fmtPct(profitPct)})
          </span>
        )}
      </div>
      <div style={{ marginTop: '12px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '12px' }}>
        <div>
          <span style={{ color: 'var(--text-muted)' }}>매수까지: </span>
          <span style={{ color: 'var(--buy)' }}>{fmtUSD(buyPrice)}/주</span>
          {unitSize && <span style={{ color: 'var(--text-muted)', marginLeft: '4px' }}>({unitSize}주)</span>}
        </div>
        <div>
          <span style={{ color: 'var(--text-muted)' }}>매도까지: </span>
          <span style={{ color: 'var(--sell)' }}>{fmtUSD(sellPrice)}/주</span>
          {unitSize && <span style={{ color: 'var(--text-muted)', marginLeft: '4px' }}>({unitSize}주)</span>}
        </div>
      </div>
      {signal.total_profit != null && (
        <div style={{ marginTop: '8px', fontSize: '14px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ color: 'var(--text-muted)' }}>총누적수익 (원금 {fmtUSD(signal.total_invested)})</span>
          <span className={signal.total_profit >= 0 ? 'price-up' : 'price-down'} style={{ fontWeight: 700, fontSize: '15px' }}>
            {signal.total_profit >= 0 ? '+' : ''}{fmtUSD(signal.total_profit)} ({signal.total_profit_pct >= 0 ? '+' : ''}{fmtPct(signal.total_profit_pct)})
          </span>
        </div>
      )}
      {executedPrices.length > 0 && cycleDirection && (
        <div style={{ marginTop: '8px', fontSize: '12px', color: 'var(--text-muted)' }}>
          이번 회차 요약:{' '}
          <span style={{ color: cycleColor, fontWeight: 600 }}>{cycleDirection}</span>:{' '}
          {executedPrices.map((p) => `$${p}`).join(', ')}
        </div>
      )}
    </div>
  );
}
