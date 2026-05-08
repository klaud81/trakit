import { useEffect, useMemo, useState } from 'react';
import {
  LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Legend, ReferenceLine, Brush,
} from 'recharts';

const DEFAULT_WINDOW = 50;

export default function PlanVsActualChart({ history, currentWeek }) {
  const data = useMemo(() => {
    if (!history) return [];
    return history
      .filter((d) => (d.planned || 0) > 0 || (d.total || 0) > 0)
      .map((d) => ({
        week_num: d.week_num,
        planned: d.planned || null,
        total: d.total && d.total > 0 ? d.total : null,
      }));
  }, [history]);

  const total = data.length;
  const [windowStart, setWindowStart] = useState(0);
  const [windowEnd, setWindowEnd] = useState(0);

  useEffect(() => {
    if (total === 0) return;
    setWindowStart(Math.max(0, total - DEFAULT_WINDOW));
    setWindowEnd(total - 1);
  }, [total]);

  const visible = useMemo(
    () => data.slice(windowStart, windowEnd + 1),
    [data, windowStart, windowEnd]
  );

  const yDomain = useMemo(() => {
    const vals = visible.flatMap((d) => [d.planned, d.total].filter((v) => v != null));
    if (vals.length === 0) return [0, 100000];
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const padding = (max - min) * 0.15;
    return [Math.max(0, Math.floor(min - padding)), Math.ceil(max + padding)];
  }, [visible]);

  if (!data.length) return null;

  const handleBrushChange = ({ startIndex, endIndex }) => {
    if (startIndex == null || endIndex == null) return;
    setWindowStart(startIndex);
    setWindowEnd(endIndex);
  };

  return (
    <div className="card">
      <div className="card-title">Plan vs Actual (계획 vs 평가금)</div>
      <div className="chart-container">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
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
            <Line type="monotone" dataKey="planned" stroke="#FF8400" strokeWidth={2} strokeDasharray="6 3" dot={false} connectNulls name="계획" />
            <Line type="monotone" dataKey="total" stroke="#4CAF50" strokeWidth={2} dot={false} connectNulls name="평가금(Total)" />
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
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
