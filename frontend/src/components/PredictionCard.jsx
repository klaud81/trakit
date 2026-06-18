import { useEffect, useState } from 'react';
import { fetchApi } from '../utils/api';
import { fmtUSD } from '../utils/format';

const REG_EMOJI = { '상승흐름': '📈', '하락흐름': '📉', '중립': '➡️' };

// 상승=빨강(--sell), 하락=파랑(--buy) — 프로젝트 색상 컨벤션
const dirColor = (d) => (d === '상승' ? 'var(--sell)' : 'var(--buy)');

function pctLabel(v) {
  if (v == null) return '—';
  return `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`;
}

export default function PredictionCard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = async (refresh = 0) => {
    refresh ? setRefreshing(true) : setLoading(true);
    const res = await fetchApi(`/prediction${refresh ? '?refresh=1' : ''}`);
    if (res) setData(res);
    setRefreshing(false);
    setLoading(false);
  };

  useEffect(() => { load(0); }, []);

  if (loading) return null;
  const pred = data?.prediction;
  if (!pred) return null;

  const sc = data?.scorecard || {};
  const pc = pred.ref_close;
  const relPct = (p) => (pc ? (p - pc) / pc * 100 : 0);
  // 밴드 내 기준종가 위치 (밴드폭 대비)
  const range = pred.band_high - pred.band_low;
  const refPos = range > 0 ? Math.max(2, Math.min(98, (pc - pred.band_low) / range * 100)) : 50;

  return (
    <div className="card">
      <div className="card-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>🔮 오늘의 TQQQ 예측</span>
        <button
          onClick={() => load(1)}
          title="새 예측 발행 (뉴스 재수집)"
          disabled={refreshing}
          style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '15px', color: 'var(--text-muted)', opacity: refreshing ? 0.4 : 1 }}
        >↻</button>
      </div>

      {/* 흐름 · 방향 */}
      <div style={{ display: 'flex', gap: '20px', alignItems: 'baseline', flexWrap: 'wrap' }}>
        <div>
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>흐름 </span>
          <span style={{ fontWeight: 700 }}>{REG_EMOJI[pred.regime] || ''} {pred.regime}</span>
        </div>
        <div>
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>방향 </span>
          <span style={{ fontWeight: 800, fontSize: '18px', color: dirColor(pred.direction) }}>{pred.direction}</span>
        </div>
        {pred.inflection && (
          <span style={{ fontSize: '12px', color: 'var(--primary)' }}>⚡ 변곡: {pred.inflection}</span>
        )}
      </div>

      {/* 밴드 시각화 */}
      <div className="band-visual" style={{ marginTop: '12px' }}>
        <div className="band-row">
          <span className="band-label" style={{ color: 'var(--buy)' }}>{pctLabel(relPct(pred.band_low))}</span>
          <div className="band-bar" style={{ position: 'relative' }}>
            <div className="band-fill" style={{ width: '100%', background: 'linear-gradient(90deg, rgba(21,101,192,0.22), rgba(229,57,53,0.22))' }}>
              {fmtUSD(pred.band_low)} ~ {fmtUSD(pred.band_high)}
            </div>
            {/* 기준종가 마커 */}
            <div title={`기준종가 ${fmtUSD(pc)}`} style={{ position: 'absolute', top: 0, bottom: 0, left: `${refPos}%`, width: '2px', background: 'var(--text)' }} />
          </div>
          <span className="band-label" style={{ color: 'var(--sell)' }}>{pctLabel(relPct(pred.band_high))}</span>
        </div>
      </div>
      <div style={{ fontSize: '11px', color: 'var(--text-muted)', textAlign: 'center', marginTop: '4px' }}>
        기준종가 {fmtUSD(pc)} · 뉴스 bias {pred.nasdaq_bias >= 0 ? '+' : ''}{(pred.nasdaq_bias ?? 0).toFixed(2)} · {pred.model}
      </div>

      {/* 근거 */}
      {pred.reasons?.length > 0 && (
        <div style={{ marginTop: '10px', fontSize: '12px' }}>
          {pred.reasons.slice(0, 3).map((r, i) => (
            <div key={i} style={{ color: 'var(--text-muted)', padding: '1px 0' }}>
              • {r.factor} <span style={{ opacity: 0.7 }}>({r.score >= 0 ? '+' : ''}{r.score})</span>
            </div>
          ))}
        </div>
      )}

      {/* 누적 성적 */}
      {sc.n > 0 && (
        <div style={{ marginTop: '10px', paddingTop: '8px', borderTop: '1px solid var(--border)', display: 'flex', gap: '14px', flexWrap: 'wrap', fontSize: '12px' }}>
          <Stat label={`방향(${sc.n}일)`} val={`${Math.round(sc.direction_hit * 100)}%`} />
          <Stat label="흐름" val={`${Math.round(sc.regime_hit * 100)}%`} />
          <Stat label="밴드커버" val={`${Math.round(sc.band_cover * 100)}%`} />
          <Stat label="폭편향" val={`${sc.band_bias >= 0 ? '+' : ''}${sc.band_bias}%p`} />
          <Stat label="변곡recall" val={sc.reversal_recall == null ? '—' : `${Math.round(sc.reversal_recall * 100)}%`} />
        </div>
      )}
    </div>
  );
}

function Stat({ label, val }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ color: 'var(--text-muted)', fontSize: '10px' }}>{label}</div>
      <div style={{ fontWeight: 700 }}>{val}</div>
    </div>
  );
}
