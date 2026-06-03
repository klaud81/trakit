import { fmt, fmtUSD } from '../utils/format';

export default function TradeTable({ title, table, type, unitSize, cycleTrade }) {
  const color = type === 'buy' ? 'var(--buy)' : 'var(--sell)';
  const header = table?.header;
  const allRows = table?.rows || [];
  // 회차기록 체결가 형식
  //  - 신 형식(부호): 매도=양수, 매수=음수 → 한 회차에 매수·매도 혼재 가능
  //  - 구 형식(부호 없음): 전부 양수, 방향은 trade_shares 부호로 판별(양수=매수)
  const tradeShares = cycleTrade?.trade_shares || 0;
  const executedPrices = cycleTrade?.executed_prices || [];
  const hasSigned = executedPrices.some((p) => p < 0);
  let buyExec, sellExec;
  if (hasSigned) {
    sellExec = executedPrices.filter((p) => p > 0);
    buyExec = executedPrices.filter((p) => p < 0).map((p) => Math.abs(p));
  } else {
    buyExec = tradeShares > 0 ? executedPrices : [];
    sellExec = tradeShares < 0 ? executedPrices : [];
  }
  // 이 테이블 방향의 체결가(양수). 개수 = 회차 수 (1 price = 1 round = unitSize 주)
  const myExec = type === 'buy' ? buyExec : sellExec;
  const executedRounds = myExec.length;
  const executedShares = executedRounds * (unitSize || 0);
  // 취소선: 매도 가격 ≤ max(매도체결) / 매수 가격 ≥ min(매수체결)
  const isExecuted = (price) => {
    if (myExec.length === 0) return false;
    if (type === 'sell') return price <= Math.max(...sellExec);
    return price >= Math.min(...buyExec);
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
          이번 회차 {type === 'buy' ? '매수' : '매도'}{' '}
          <strong style={{ color }}>{executedRounds}회 × {unitSize}주</strong>
          {' '}= {executedShares}주
          {' '}({type === 'buy' ? '-' : '+'}${fmt(myExec.reduce((s, p) => s + p * unitSize, 0), 2)})
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
