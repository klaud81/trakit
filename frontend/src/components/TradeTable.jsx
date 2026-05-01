import { fmt, fmtUSD } from '../utils/format';

export default function TradeTable({ title, table, type, unitSize, cycleTrade }) {
  const color = type === 'buy' ? 'var(--buy)' : 'var(--sell)';
  const header = table?.header;
  const allRows = table?.rows || [];
  // 현재 회차에 이번 type 방향으로 거래한 주식수 / 회차수
  const tradeShares = cycleTrade?.trade_shares || 0;
  const tradeAmount = cycleTrade?.trade_amount || 0;
  const executedPrices = cycleTrade?.executed_prices || [];
  const matchesDirection = (type === 'buy' && tradeShares > 0) || (type === 'sell' && tradeShares < 0);
  const executedShares = matchesDirection ? Math.abs(tradeShares) : 0;
  const executedRounds = unitSize > 0 ? Math.floor(executedShares / unitSize) : 0;
  // 체결가가 있으면 해당 가격대를 이미 체결된 것으로 표시 (취소선)
  // 매도: 가격 ≤ max(체결가) / 매수: 가격 ≥ min(체결가)
  const isExecuted = (price) => {
    if (!matchesDirection || executedPrices.length === 0) return false;
    if (type === 'sell') return price <= Math.max(...executedPrices);
    return price >= Math.min(...executedPrices);
  };
  const rows = allRows;

  return (
    <div className="card">
      <div className="card-title" style={{ color, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>{title}</span>
        {unitSize != null && <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: 400 }}>기준수량: {unitSize}</span>}
      </div>
      {executedRounds > 0 && (
        <div style={{
          fontSize: '12px', color: 'var(--text-muted)',
          padding: '6px 10px', marginBottom: '6px',
          background: type === 'buy' ? 'rgba(30,136,229,0.08)' : 'rgba(229,57,53,0.08)',
          borderLeft: `3px solid ${color}`,
          borderRadius: '4px',
        }}>
          이번 회차 {type === 'buy' ? '매수' : '매도'} <strong style={{ color }}>{executedRounds}회</strong> 진행됨
          ({executedShares}주, {type === 'buy' ? '-' : '+'}${fmt(Math.abs(tradeAmount), 2)})
        </div>
      )}
      <table className="trade-table">
        <thead>
          <tr>
            <th>{type === 'buy' ? '최소값' : '최대값'}</th>
            <th>잔여갯수</th>
            <th>{type === 'buy' ? '매수점' : '매도점'}</th>
            <th>pool</th>
            <th>누적</th>
          </tr>
        </thead>
        <tbody>
          {header && (
            <tr style={{ fontWeight: 600, background: 'var(--bg-secondary, rgba(0,0,0,0.03))' }}>
              <td>{fmtUSD(header.band)}</td>
              <td>{fmt(header.shares, 0)}주</td>
              <td>—</td>
              <td>{fmtUSD(header.pool)}</td>
              <td>—</td>
            </tr>
          )}
          {rows && rows.map((p, i) => {
            const done = isExecuted(p.price);
            const strike = done ? { textDecoration: 'line-through', opacity: 0.55 } : {};
            return (
              <tr key={i}>
                <td style={strike}></td>
                <td style={strike}>{fmt(p.shares_after, 0)}주</td>
                <td style={{ color, ...strike }}>{fmtUSD(p.price)}</td>
                <td style={{ color: 'var(--text-muted)', ...strike }}>{fmtUSD(p.pool_after)}</td>
                <td style={{ color, fontSize: '11px', ...strike }}>{type === 'sell' ? '+' : '-'}{fmtUSD(p.cumulative)}</td>
              </tr>
            );
          })}
          {(!rows || rows.length === 0) && !header && (
            <tr><td colSpan="5" style={{ color: 'var(--text-muted)', textAlign: 'center' }}>데이터 없음</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
