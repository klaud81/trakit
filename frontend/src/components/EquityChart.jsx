import { useEffect, useMemo, useState } from 'react';
import {
  ComposedChart, Area, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Legend, ReferenceLine, Brush,
} from 'recharts';

const DEFAULT_WINDOW = 50;

export default function EquityChart({ history, currentWeek }) {
  // valuation이 0인 경우 null로 변환 (라인이 0으로 떨어지는 것 방지)
  const cleanHistory = useMemo(() => {
    if (!history) return [];
    return history.map((d) => ({
      ...d,
      valuation: d.valuation && d.valuation > 0 ? d.valuation : null,
      total: d.total && d.total > 0 ? d.total : null,
    }));
  }, [history]);

  const total = cleanHistory.length;
  const [windowStart, setWindowStart] = useState(0);
  const [windowEnd, setWindowEnd] = useState(0);

  // 데이터 길이 변경 시 마지막 50개로 리셋
  useEffect(() => {
    if (total === 0) return;
    setWindowStart(Math.max(0, total - DEFAULT_WINDOW));
    setWindowEnd(total - 1);
  }, [total]);

  const visibleData = useMemo(
    () => cleanHistory.slice(windowStart, windowEnd + 1),
    [cleanHistory, windowStart, windowEnd]
  );

  // Y축 범위는 보이는 구간 기준 (Brush 윈도우 변경 시 자동 재계산)
  const yDomain = useMemo(() => {
    const vals = visibleData.flatMap((d) =>
      [d.valuation, d.min_band, d.max_band].filter((v) => v != null && v > 0)
    );
    if (vals.length === 0) return [0, 100000];
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const padding = (max - min) * 0.15;
    return [Math.max(0, Math.floor(min - padding)), Math.ceil(max + padding)];
  }, [visibleData]);

  if (!cleanHistory.length) return null;

  const handleBrushChange = ({ startIndex, endIndex }) => {
    if (startIndex == null || endIndex == null) return;
    setWindowStart(startIndex);
    setWindowEnd(endIndex);
  };

  return (
    <div className="card">
      <div className="card-title">Value Rebalancing Chart (평가금)</div>
      <div className="chart-container">
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={cleanHistory}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis
              dataKey="week_num"
              type="number"
              domain={['dataMin', 'dataMax']}
              allowDataOverflow
              stroke="var(--text-muted)"
              fontSize={11}
              tickFormatter={(v) => `${v}w`}
            />
            <YAxis
              stroke="var(--text-muted)"
              fontSize={11}
              domain={yDomain}
              tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
            />
            <Tooltip
              wrapperStyle={{ opacity: 1 }}
              contentStyle={{ background: '#FFFFFF', color: '#111', border: '1px solid var(--border)', borderRadius: '8px', opacity: 1 }}
              labelStyle={{ color: '#111', fontWeight: 600 }}
              labelFormatter={(v) => `${v}주차`}
              formatter={(v, name) => [`$${Number(v).toLocaleString()}`, name]}
            />
            <Legend wrapperStyle={{ fontSize: '12px' }} />
            {currentWeek && (
              <ReferenceLine x={currentWeek} stroke="#FF8400" strokeDasharray="4 4" strokeWidth={1.5} label={{ value: `${currentWeek}w`, position: 'top', fontSize: 10, fill: '#FF8400' }} />
            )}
            <Area type="monotone" dataKey="max_band" stroke="#D32F2F" fill="rgba(211,47,47,0.1)" name="최대밴드" />
            <Area type="monotone" dataKey="min_band" stroke="#1565C0" fill="rgba(21,101,192,0.1)" name="최소밴드" />
            <Line type="monotone" dataKey="valuation" stroke="#4CAF50" strokeWidth={2} dot={false} connectNulls name="평가금(E)" />
            {total > DEFAULT_WINDOW && (
              <Brush
                dataKey="week_num"
                height={24}
                stroke="var(--primary)"
                startIndex={windowStart}
                endIndex={windowEnd}
                onChange={handleBrushChange}
                tickFormatter={(v) => `${v}w`}
              />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
