import { useState, useEffect, useCallback } from 'react';
import { fetchApi } from './utils/api';
import { demoHistory } from './utils/demoData';
import Header from './components/Header';
import PortfolioCard from './components/PortfolioCard';
import BandCard from './components/BandCard';
import TradeTable from './components/TradeTable';
import SignalPanel from './components/SignalPanel';
import ProgressCard from './components/ProgressCard';
import EquityChart from './components/EquityChart';
import ValueLineChart from './components/ValueLineChart';

/** 기준 단수 = ROUND(pool / 13 / (min_band / shares) / 2) */
function calcUnitSize(shares, minBand, pool) {
  if (shares <= 0 || minBand <= 0) return 10;
  const buyPrice = minBand / shares;
  return Math.max(1, Math.round(pool / 13 / buyPrice / 2));
}

/** 매수 포인트 계산 — pool이 초기값의 1/2 이하가 되면 중단 */
function calcBuyPoints(shares, minBand, pool, unit) {
  const pts = [];
  let rem = pool, s = shares;
  const halfPool = pool / 2;
  while (rem > halfPool) {
    const price = +(minBand / s).toFixed(2);
    const cost = +(price * unit).toFixed(2);
    if (rem < cost) break;
    rem = +(rem - cost).toFixed(2);
    s += unit;
    pts.push({ action: 'BUY', shares_after: s, price, amount: cost, pool_after: rem });
  }
  return pts;
}

/** 매도 포인트 계산 — 매수 횟수와 동일하게 반복 */
function calcSellPoints(shares, maxBand, pool, unit = 10, maxPts = 10) {
  const pts = [];
  let cur = pool, s = shares;
  for (let i = 0; i < maxPts; i++) {
    const price = +(maxBand / s).toFixed(2);
    const proceeds = +(price * unit).toFixed(2);
    cur = +(cur + proceeds).toFixed(2);
    s -= unit;
    if (s <= 0) break;
    pts.push({ action: 'SELL', shares_after: s, price, amount: proceeds, pool_after: cur });
  }
  return pts;
}

export default function App() {
  const [portfolio, setPortfolio] = useState(null);
  const [signal, setSignal] = useState(null);
  const [price, setPrice] = useState(null);
  const [tradePoints, setTradePoints] = useState(null);
  const [history, setHistory] = useState(null);
  const [remaining, setRemaining] = useState(null);
  const [loading, setLoading] = useState(true);
  const [priceRefreshing, setPriceRefreshing] = useState(false);
  const [error, setError] = useState(null);

  // 주차 네비게이션
  const [allWeeks, setAllWeeks] = useState([]);
  const [weekIdx, setWeekIdx] = useState(-1);

  /** API에서 데이터 로딩 */
  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [portfolioData, signalData, priceData, tradeData, histData, remainData] = await Promise.all([
        fetchApi('/portfolio'),
        fetchApi('/signals'),
        fetchApi('/price'),
        fetchApi('/trade-points'),
        fetchApi('/portfolio/history'),
        fetchApi('/remaining'),
      ]);

      // 모든 API가 null이면 (백엔드 미실행) 데모 데이터 사용
      if (!portfolioData && !histData) {
        throw new Error('API 응답 없음');
      }

      setPortfolio(portfolioData);
      setSignal(signalData);
      setPrice(priceData);
      setTradePoints(tradeData);

      // week_num을 숫자로 변환 (ReferenceLine 매칭용)
      const normalized = histData?.map((w) => ({ ...w, week_num: Number(w.week_num) || w.week_num }));
      setHistory(normalized);
      setRemaining(remainData);

      if (normalized && normalized.length > 0) {
        setAllWeeks(normalized);
        setWeekIdx(normalized.length - 1);
      }
      setError(null);
    } catch (e) {
      setError('API 연결 실패. 백엔드가 실행 중인지 확인하세요.');
      loadDemoData();
    }
    setLoading(false);
  }, []);

  /** 데모 데이터 로딩 (백엔드 없을 때) */
  const loadDemoData = () => {
    setAllWeeks(demoHistory);
    setWeekIdx(demoHistory.length - 1);
    const last = demoHistory[demoHistory.length - 1];

    setPortfolio({
      week_num: last.week_num, date_range: last.date_range, price: last.price,
      shares: last.shares, avg_cost: 39.03, valuation: last.valuation,
      pool: last.pool, target_value: last.target_value,
      min_band: last.min_band, max_band: last.max_band,
      growth_stage: last.g, total_value: last.total, goal_progress: 5.97,
    });
    setSignal({
      signal_type: 'HOLD', confidence: 0.7,
      current_valuation: last.valuation, target_value: last.target_value,
      min_band: last.min_band, max_band: last.max_band,
      distance_to_buy: last.valuation - last.min_band,
      distance_to_sell: last.max_band - last.valuation,
      recommendation: '홀드: 밴드 내 18% 위치. 현재 상태 유지하세요.',
    });
    // 데모 매수/매도 포인트 계산 (기준 단수 자동 계산)
    const demoUnit = calcUnitSize(last.shares, last.min_band, last.pool);
    const buyRows = calcBuyPoints(last.shares, last.min_band, last.pool, demoUnit);
    const sellRows = calcSellPoints(last.shares, last.max_band, last.pool, demoUnit, buyRows.length);
    setTradePoints({
      buy_table: { header: { band: last.min_band, shares: last.shares, pool: last.pool }, rows: buyRows },
      sell_table: { header: { band: last.max_band, shares: last.shares, pool: last.pool }, rows: sellRows },
      unit_size: demoUnit,
      count: buyRows.length,
    });
    setRemaining({ current_week: 258, goal_week: 560, remaining_weeks: 302, remaining_cycles: 151 });
    setHistory(demoHistory);
  };

  /** 주차 네비게이션 */
  const navigateWeek = async (newIdx) => {
    if (newIdx < 0 || newIdx >= allWeeks.length) return;
    setWeekIdx(newIdx);

    const week = allWeeks[newIdx];
    const isLastWeek = newIdx === allWeeks.length - 1;
    const liveP = isLastWeek && price && price.price > 0 ? price.price : null;
    const usedPrice = liveP || week.price;
    const valuation = liveP ? liveP * week.shares : (week.valuation || week.price * week.shares);
    const pool = week.pool || 0;
    const total = valuation + pool;
    const goalPct = (total / (1_000_000_000 / 1400)) * 100;

    setPortfolio((prev) => ({
      ...prev,
      week_num: week.week_num, date_range: week.date_range || '',
      price: usedPrice, shares: week.shares, valuation, pool,
      target_value: week.target_value || prev?.target_value,
      min_band: week.min_band || prev?.min_band,
      max_band: week.max_band || prev?.max_band,
      growth_stage: week.g || prev?.growth_stage,
      total_value: total, goal_progress: Math.round(goalPct * 100) / 100,
    }));

    // 시그널 재계산
    const minB = week.min_band || 0;
    const maxB = week.max_band || 0;
    let st = 'HOLD';
    if (valuation < minB) st = 'BUY';
    else if (valuation > maxB) st = 'SELL';

    const bandRange = maxB - minB;
    const pos = bandRange > 0 ? ((valuation - minB) / bandRange * 100).toFixed(0) : 50;
    const rec =
      st === 'BUY' ? '매수 추천: 평가금이 최소밴드 아래입니다. 적극 매수 구간.' :
      st === 'SELL' ? '매도 추천: 평가금이 최대밴드 위입니다. 일부 매도 고려.' :
      `홀드: 밴드 내 ${pos}% 위치. 현재 상태 유지하세요.`;

    setSignal({
      signal_type: st, confidence: 0.7, current_valuation: valuation,
      target_value: week.target_value || 0, min_band: minB, max_band: maxB,
      distance_to_buy: valuation - minB, distance_to_sell: maxB - valuation,
      recommendation: rec,
    });

    // 매수/매도 포인트: API 호출, 실패 시 로컬 계산 fallback
    const shares = week.shares || 0;
    const apiResult = await fetchApi(
      `/trade-points/calc?shares=${shares}&min_band=${minB}&max_band=${maxB}&pool=${pool}`
    );
    if (apiResult) {
      setTradePoints(apiResult);
    } else {
      const unit = calcUnitSize(shares, minB, pool);
      const buyRows = calcBuyPoints(shares, minB, pool, unit);
      const sellRows = calcSellPoints(shares, maxB, pool, unit, buyRows.length);
      setTradePoints({
        buy_table: { header: { band: minB, shares, pool }, rows: buyRows },
        sell_table: { header: { band: maxB, shares, pool }, rows: sellRows },
        unit_size: unit,
        count: buyRows.length,
      });
    }
  };

  /** 실시간 가격 자동 갱신 (30초) */
  useEffect(() => {
    const refreshPrice = async () => {
      setPriceRefreshing(true);
      const p = await fetchApi('/price');
      if (p && p.price > 0) setPrice(p);
      setPriceRefreshing(false);
    };
    const interval = setInterval(refreshPrice, 30_000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  if (loading) {
    return (
      <div className="loading">
        <div className="spinner" />
        <div>데이터 로딩 중...</div>
      </div>
    );
  }

  return (
    <div>
      <Header
        portfolio={portfolio}
        weekIdx={weekIdx} totalWeeks={allWeeks.length}
        onPrevWeek={() => navigateWeek(weekIdx - 1)}
        onNextWeek={() => navigateWeek(weekIdx + 1)}
      />
      <div className="main">
        {error && (
          <div style={{ padding: '12px 16px', background: 'rgba(255,132,0,0.15)', borderRadius: '8px', fontSize: '13px', color: 'var(--primary)' }}>
            {error} — 데모 데이터로 표시합니다.
          </div>
        )}
        <div className="grid-2">
          <PortfolioCard portfolio={portfolio} signal={signal} />
          <BandCard portfolio={portfolio} />
        </div>
        <SignalPanel signal={signal} price={portfolio?.price} livePrice={price} priceRefreshing={priceRefreshing} tradePoints={tradePoints} />
        <EquityChart history={history} currentWeek={allWeeks[weekIdx]?.week_num} />
        <ValueLineChart history={history} currentWeek={allWeeks[weekIdx]?.week_num} />
        <div className="grid-2">
          <TradeTable title="매수 포인트 (BUY)" table={tradePoints?.buy_table} type="buy" unitSize={tradePoints?.unit_size} />
          <TradeTable title="매도 포인트 (SELL)" table={tradePoints?.sell_table} type="sell" unitSize={tradePoints?.unit_size} />
        </div>
        <ProgressCard portfolio={portfolio} remaining={remaining} />
        <div className="sponsor-card">
          <span style={{ fontSize: '28px' }}>☕</span>
          <div className="sponsor-card-text">
            <span style={{ fontWeight: 700, fontSize: '28px' }}>후원하기</span>
            <span style={{ color: 'var(--text-muted)', fontSize: '28px' }}>우리은행 1005204834806 · (주)스노우볼</span>
          </div>
          <button className="sponsor-card-copy" onClick={(e) => {
            const text = '1005204834806';
            if (navigator.clipboard) {
              navigator.clipboard.writeText(text);
            } else {
              const ta = document.createElement('textarea');
              ta.value = text;
              document.body.appendChild(ta);
              ta.select();
              document.execCommand('copy');
              document.body.removeChild(ta);
            }
            e.target.textContent = '복사됨!';
            setTimeout(() => { e.target.textContent = '복사'; }, 2000);
          }}>
            복사
          </button>
        </div>
      </div>
    </div>
  );
}
