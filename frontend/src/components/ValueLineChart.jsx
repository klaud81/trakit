import { useMemo } from 'react';
import {
  LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Legend, ReferenceLine,
} from 'recharts';

export default function ValueLineChart({ history, currentWeek }) {
  if (!history || history.length === 0) return null;

  // 1주당 가격으로 환산
  const perShareData = useMemo(() => {
    return history.map((d) => {
      const shares = d.shares || 1;
      return {
        week_num: d.week_num,
        price: d.price,
        e_per_share: d.valuation ? +(d.valuation / shares).toFixed(2) : null,
        v_per_share: d.target_value ? +(d.target_value / shares).toFixed(2) : null,
        min_per_share: d.min_band ? +(d.min_band / shares).toFixed(2) : null,
        max_per_share: d.max_band ? +(d.max_band / shares).toFixed(2) : null,
      };
    });
  }, [history]);

  // Y축 범위 계산 (여유 있게)
  const yDomain = useMemo(() => {
    const vals = perShareData.flatMap((d) =>
      [d.price, d.e_per_share, d.v_per_share, d.min_per_share, d.max_per_share].filter((v) => v != null)
    );
    if (vals.length === 0) return [0, 100];
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const padding = (max - min) * 0.15;
    return [Math.max(0, Math.floor(min - padding)), Math.ceil(max + padding)];
  }, [perShareData]);

  return (
    <div className="card">
      <div className="card-title">Value Movement / 주당 가격 (가치 이동선)</div>
      <div className="chart-container">
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={perShareData}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis
              dataKey="week_num"
              type="number"
              domain={['dataMin', 'dataMax']}
              stroke="var(--text-muted)"
              fontSize={11}
              tickFormatter={(v) => `${v}w`}
            />
            <YAxis
              stroke="var(--text-muted)"
              fontSize={11}
              domain={yDomain}
              tickFormatter={(v) => `$${v}`}
            />
            <Tooltip
              wrapperStyle={{ opacity: 1 }}
              contentStyle={{ background: '#FFFFFF', color: '#111', border: '1px solid var(--border)', borderRadius: '8px', opacity: 1 }}
              labelStyle={{ color: '#111', fontWeight: 600 }}
              labelFormatter={(v) => `${v}주차`}
              formatter={(v, name) => [`$${Number(v).toFixed(2)}`, name]}
            />
            <Legend wrapperStyle={{ fontSize: '12px' }} />
            {currentWeek && (
              <ReferenceLine x={currentWeek} stroke="#FF8400" strokeDasharray="4 4" strokeWidth={1.5} label={{ value: `${currentWeek}w`, position: 'top', fontSize: 10, fill: '#FF8400' }} />
            )}
            <Line type="monotone" dataKey="e_per_share" stroke="#9C27B0" strokeWidth={2} dot={false} name="평가금(E)/주" />
            <Line type="monotone" dataKey="price" stroke="#4CAF50" strokeWidth={2} dot={{ r: 2 }} name="TQQQ 가격" />
            <Line type="monotone" dataKey="v_per_share" stroke="#FF8400" strokeWidth={2} strokeDasharray="6 3" dot={false} name="V/주" />
            <Line type="monotone" dataKey="max_per_share" stroke="#D32F2F" strokeWidth={1} dot={false} name="최대/주" />
            <Line type="monotone" dataKey="min_per_share" stroke="#1565C0" strokeWidth={1} dot={false} name="최소/주" />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
