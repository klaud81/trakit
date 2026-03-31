import { fmtUSD, fmtPct } from '../utils/format';

export default function BandCard({ portfolio }) {
  if (!portfolio) return null;
  const { valuation, min_band, max_band, target_value } = portfolio;
  const range = max_band - min_band;
  const currentPct = range > 0 ? (valuation - min_band) / range * 100 : 50;

  return (
    <div className="card">
      <div className="card-title">Rebalancing Band</div>
      <div className="band-visual">
        <div className="band-row">
          <span className="band-label" style={{ color: 'var(--sell)' }}>MAX</span>
          <div className="band-bar">
            <div className="band-fill" style={{ width: '100%', background: 'rgba(211,47,47,0.2)' }}>SELL zone</div>
          </div>
          <span className="band-value" style={{ color: 'var(--sell)' }}>{fmtUSD(max_band)}</span>
        </div>
        <div className="band-row">
          <span className="band-label" style={{ color: 'var(--primary)' }}>NOW</span>
          <div className="band-bar">
            <div
              className="band-fill"
              style={{
                width: `${Math.max(5, Math.min(95, currentPct))}%`,
                background: 'linear-gradient(90deg, var(--buy), var(--primary))',
              }}
            >
              {fmtUSD(valuation)}
            </div>
          </div>
          <span className="band-value">{fmtPct(currentPct.toFixed(1))}</span>
        </div>
        <div className="band-row">
          <span className="band-label" style={{ color: 'var(--buy)' }}>MIN</span>
          <div className="band-bar">
            <div className="band-fill" style={{ width: '100%', background: 'rgba(21,101,192,0.2)' }}>BUY zone</div>
          </div>
          <span className="band-value" style={{ color: 'var(--buy)' }}>{fmtUSD(min_band)}</span>
        </div>
      </div>
      <div style={{ marginTop: '12px', fontSize: '12px', color: 'var(--text-muted)', textAlign: 'center' }}>
        Target(V): {fmtUSD(target_value)} · G={portfolio.growth_stage}
      </div>
    </div>
  );
}
