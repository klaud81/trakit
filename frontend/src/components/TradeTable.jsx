import { fmt, fmtUSD } from '../utils/format';

export default function TradeTable({ title, table, type, unitSize }) {
  const color = type === 'buy' ? 'var(--buy)' : 'var(--sell)';
  const header = table?.header;
  const rows = table?.rows;

  return (
    <div className="card">
      <div className="card-title" style={{ color, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>{title}</span>
        {unitSize != null && <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: 400 }}>기준수량: {unitSize}</span>}
      </div>
      <table className="trade-table">
        <thead>
          <tr>
            <th>{type === 'buy' ? '최소값' : '최대값'}</th>
            <th>잔여갯수</th>
            <th>{type === 'buy' ? '매수점' : '매도점'}</th>
            <th>pool</th>
          </tr>
        </thead>
        <tbody>
          {header && (
            <tr style={{ fontWeight: 600, background: 'var(--bg-secondary, rgba(0,0,0,0.03))' }}>
              <td>{fmtUSD(header.band)}</td>
              <td>{fmt(header.shares, 0)}주</td>
              <td>—</td>
              <td>{fmtUSD(header.pool)}</td>
            </tr>
          )}
          {rows && rows.map((p, i) => (
            <tr key={i}>
              <td></td>
              <td>{fmt(p.shares_after, 0)}주</td>
              <td style={{ color }}>{fmtUSD(p.price)}</td>
              <td style={{ color: 'var(--text-muted)' }}>{fmtUSD(p.pool_after)}</td>
            </tr>
          ))}
          {(!rows || rows.length === 0) && !header && (
            <tr><td colSpan="4" style={{ color: 'var(--text-muted)', textAlign: 'center' }}>데이터 없음</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
