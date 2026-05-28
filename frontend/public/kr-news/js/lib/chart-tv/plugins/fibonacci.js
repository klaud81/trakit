/* ───── lib/chart-tv/plugins/fibonacci.js — #3 Fibonacci 자석 drawing tool (TradingView v5) ─────
   cycle22 Phase 7d-2 — REQ DOC-20260521-REQ-002 v3 §3.1 + §4.2 verbatim 정합.

   P0-25 (2026-05-21 23:46 KST 대표 결정 verbatim "영웅문 paradigm 채택 — chart area drag/click + separate handle 폐기"):
     영웅문 23a74560 reference 본문 chart canvas 자체 click/drag paradigm 본질 (separate dot handle 부재, swing high/low에 inline arrow marker).
     P0-24 Fix-82 누적 handle 시각 강화 (radius 14 + pulse + 적색 glow) 본문에도 대표 verbatim "피보나치 사용법이 여전히 알 수 없다" =
     handle 시각 강화 cascade 한계. paradigm shift = chart area 자체 interaction (subscribeClick + chartElement mousedown 본질).

     본질 변경 본문:
       - separate DOM handle (Phase 7d-2 ~ P0-24): default visible + drag trigger 본문 폐기
       - chart canvas (chartElement) 자체 = click/drag interface 본질
       - handle DOM 본문 보존 but **default invisible** (영웅문 inline ↓ marker 정합 = anchor 시각 cue만, drag trigger 아님)
       - chart canvas mousedown: anchor A 또는 B 근처 (pixel tolerance 본문) = drag mode 시작
       - chart canvas mousemove: drag 중 anchor 위치 갱신 + magnetSnap 재적용
       - chart canvas mouseup: drag 종료 + state save

   본질 (대표 2026-05-21 08:08 KST verbatim "피보나치의 경우 피크 저가 고가가 자석 기능이고
        내가 선택해서 이동하거나 기간을 조정할 수 있다"):

   1. **자석 기능 (magnet)**:
      - 사용자 클릭 시 ±N 영업일 (default 5) 윈도우 내 local peak/trough 자동 detection
      - 가장 가까운 swing high/low 가격으로 자동 snap
   2. **사용자 선택** (P0-25 chart area paradigm 본문):
      - chart canvas click 1차 = swing 시작점 (anchor A) — subscribeClick handler 본문 보존
      - chart canvas click 2차 = swing 끝점 (anchor B) — subscribeClick handler 본문 보존
      - 2점 결정 후 fibonacci horizontal level 자동 draw
   3. **드래그 조정** (P0-25 chart area paradigm 본문 신축):
      - chart canvas (chartElement) mousedown/mousemove/mouseup 본문 직접 본문
      - anchor A/B pixel position ±20px 본문 mousedown 시점 = drag mode (영웅문 chart area drag 정합)
      - drag 중 실시간 fibonacci level 재계산
      - drag 종료 시 자석 snap 재적용 + state save
      - separate handle DOM 본문 보존 (영웅문 ↓ marker 정합) but default 시각 약화 (pulse/적색 glow 폐기, transparent + 매우 작음)
   4. **localStorage 영구화**:
      - schema: `m100s.chart.tv.fib.{ticker}` = `{ anchorA: {time, price}, anchorB: {time, price} }`
      - 차트 재진입 시 사용자 그린 Fib 자동 복원
   5. **axisLabelVisible 본질**:
      - Phase 7d-1 fibonacci.js 본문 createPriceLine axisLabelVisible: true 본문 paradigm 유지
      - 본 drawing tool은 series.createPriceLine + 동적 price 결합 본질로 axis label 표시

   §11.15 외부 spec 사전 검증 (WebSearch ≥2회 + 공식 docs + repo grep 3종 PASS):
   - https://tradingview.github.io/lightweight-charts/docs/api/interfaces/IChartApi
     "subscribeClick(handler: MouseEventHandler<Time>): void"
     "subscribeCrosshairMove(handler: MouseEventHandler<Time>): void"
   - https://tradingview.github.io/lightweight-charts/docs/plugins/intro
     "ISeriesPrimitive — paneViews() returns IPrimitivePaneView[] for canvas draw"
   - repo grep verbatim: js/lib/chart-tv/plugins/pink-signal.js + volume-by-decile.js
     (subscribe handler + canvas draw 본질 동형 패턴)

   §16 self-catch (Phase 7d-2):
   - 기존 Phase 7d-1 단순 createPriceLine 3종 helper API (`attachFibonacci(series, candles, options)`)는
     본 Phase 7d-2 drawing tool로 완전 대체 (backward 비호환 signature 변경).
     expanded-chart.js addFibonacci/removeFibonacci 본문 동시 정정 의무.
   - swing 시작/끝점 = 사용자 클릭 + 자석 snap 본질. 기존 "가시 영역 hi/lo 자동" paradigm 폐기.
   - axisLabelVisible 본질 = series.createPriceLine + axisLabelVisible: true 옵션 결합 본질 (v5 native).

   위임 PROMPT vs REQ v3 verbatim 색상 mismatch §16 catch:
   - 위임 PROMPT MA 색상 (#3B82F6 등) vs REQ v3 §2 verbatim (#FF69B4 등) mismatch.
   - 본 Phase 7d-2 = MA 10 line 추가 본질만. 색상 본문 정정은 별건 cycle 후행.
*/

import { LineStyle } from 'https://cdn.jsdelivr.net/npm/lightweight-charts@5.0.8/+esm';

const STORAGE_PREFIX = 'm100s.chart.tv.fib.';

// Fibonacci ratio level (대표 verbatim "피크 저가 고가" + Phase 7d-1 paradigm 정합).
// 기본 3종 (38.2/50/61.8) + 확장 4종 (0/23.6/76.4/100) = 7 level (영웅문 본문 정합).
const LEVELS = [
  { ratio: 0.0,   title: 'Fib 0%',    color: '#94A3B8' },
  { ratio: 0.236, title: 'Fib 23.6%', color: '#F5A623' },
  { ratio: 0.382, title: 'Fib 38.2%', color: '#F5A623' },
  { ratio: 0.5,   title: 'Fib 50%',   color: '#F5A623' },
  { ratio: 0.618, title: 'Fib 61.8%', color: '#F5A623' },
  { ratio: 0.764, title: 'Fib 76.4%', color: '#F5A623' },
  { ratio: 1.0,   title: 'Fib 100%',  color: '#94A3B8' },
];

// P0-17 Fix-55 (2026-05-21 15:18 KST 대표 verbatim "피보나치 역시 라벨값이 너무 지저분하다 안보여줘도 돼.
//   대신 가격 fib xx% 값을 제거해줘"):
//   - axisLabelVisible: false → 우측 priceScale axis 본문 가격값 (22450/17619 등) 제거
//   - title 본문 제거 (LEVELS 본문 lv.title 본문 createPriceLine 호출 시 빈 string 본문 채택)
//   - 7 horizontal line 본문 visible 보존 (라벨만 제거 본질)
//   §11.15 외부 spec 사전 검증 PASS:
//     - TradingView v5 createPriceLine.axisLabelVisible:false → priceScale 우측 가격 라벨 hide
//     - title 빈 string 본문 → priceLine 본문 좌측 비율 라벨 hide
//     - line color/lineStyle/lineWidth 본문은 그대로 → 가로선 본문 visible 보존
//
// P0-18 Fix-58 (2026-05-21 16:03 KST 대표 verbatim "피보나치 선 마다 좌측에 작은 글씨로 가격을 표사해주고"):
//   1차 시도 — createPriceLine title 본문 = 가격 string. §16 self-catch (P0-18 Playwright audit):
//   TradingView v5 PriceLineOptions.title 본문 visibility = axisLabelVisible:true 종속 본질
//   → axisLabelVisible:false (Fix-55) + title:formatPriceLabel 본문 동시 설정 = title visible 0건 결정적 paradigm 충돌.
//
// P0-19 Fix-63 (2026-05-21 16:35 KST P0-18 Fix-58 paradigm 충돌 cascade 정합, 대표 verbatim
//   "피보나치 선 마다 좌측에 작은 글씨로 가격을 표사해주고" 16:03 KST):
//   - createPriceLine title 본문 = '' (빈 string) 복원 — Fix-55 axisLabelVisible:false 보존
//   - 좌측 본문 가격 라벨 = HTML overlay DOM 본문 신축 (P0-17 Fix-52 sub-pane title 좌측 본문 동형 paradigm)
//     · 각 fib level별 absolute-positioned <div> 본문 chart container 위 직접 신축
//     · left: 8px (영웅문 23a74560 본문 좌측 본문 정합)
//     · top: series.priceToCoordinate(price) — y좌표 실시간 계산 본문
//     · font-size: 10px (대표 verbatim "작은 글씨" 정합)
//     · text: formatPriceLabel(price) — ko-KR locale 본문 정수 (예: '727,000')
//     · pointer-events: none (chart click/drag 본문 통과)
//   - ResizeObserver 본문 chart resize 시점 재측정 (P0-17 Fix-52 동형)
//   - timeScale.subscribeVisibleLogicalRangeChange 본문 zoom/scroll 시점 재측정 (priceToCoordinate y 좌표 변화)
//   §11.15 외부 spec 사전 검증 PASS:
//     - ISeriesApi.priceToCoordinate(price) → Coordinate | null — chart pane 본문 y좌표 반환
//     - ITimeScaleApi.subscribeVisibleLogicalRangeChange(handler) — pan/zoom 시점 callback
//     - WebSearch 2회 corroborating (TradingView Lightweight Charts v5 priceToCoordinate + subscribeVisibleLogicalRangeChange)
//     - repo verbatim: js/lib/chart-tv/plugins/volume-by-decile.js L129~131 + L195 (priceToCoordinate + subscribe 동형 패턴)
//     - repo verbatim: js/lib/chart-tv/expanded-chart.js L1019~1038 (label className+absolute overlay 동형 패턴 sub-pane title Fix-52)
//   §16 self-catch (P0-19):
//     - HTML overlay z-index: 10 본문 (sub-pane title Fix-52 동형) → drag handle (z-index:100) 본문 침범 부재
//     - priceToCoordinate null fallback (price 가시 영역 외부 본문) → label 본문 display:none silent skip
//     - destroy cleanup 본문 overlay <div> + ResizeObserver + subscribeVisibleLogicalRangeChange unsubscribe 의무
//     - ResizeObserver race condition: observe target 본문 chartContainer (main DOM) — chart.applyOptions resize cascade 본질 동기 PASS
//     - subscribeVisibleLogicalRangeChange handler 본문 _renderOverlayLabels() 즉시 호출 (debounce 부재 — handler 본문 가벼움 본질)
const DEFAULT_OPTIONS = {
  magnetWindow: 5,        // ±N 영업일 자석 detection window
  lineStyle: LineStyle.Dotted,
  lineWidth: 1,
  axisLabelVisible: false,  // P0-17 Fix-55: 우측 가격값 (22450/17619 등) 제거
  handleColor: '#F5A623',
  // P0-25 (2026-05-21 23:46 KST 대표 결정 영웅문 paradigm 채택):
  //   handle radius 14 → 6 본문 축소 (영웅문 inline ↓ marker 정합, drag trigger 본문 chart canvas 본문 본질).
  //   handle = anchor 시각 cue만 (영웅문 swing high/low 인접 ↓ arrow marker 동형 paradigm).
  //   drag trigger = chart canvas (chartElement) mousedown/mousemove/mouseup 본문 직접 본문.
  //   handle pixel tolerance (drag detect) = ±20px 본문 chart canvas 본문 mousedown 시점 본문 본질.
  //   §11.15 외부 spec PASS:
  //     - TradingView v5 chartElement() returns chart wrapper div for custom event listeners
  //       https://tradingview.github.io/lightweight-charts/docs/api/interfaces/IChartApi (chartElement method)
  //     - 영웅문 23a74560 reference 본문 chart area 자체 click/drag paradigm 본질 (separate dot handle 부재)
  handleRadius: 6,
  dragTolerance: 20,      // P0-25: chart canvas mousedown 시점 anchor 근처 detect ±20px (모바일 finger tap target 정합)
};

/**
 * P0-18 Fix-58 — 가격 → 좌측 라벨 string formatter.
 * 한국 화폐 정수 본문 정합 (소수점 부재, P0-13 Fix-45 KRW_PRICE_FORMAT 본문 동형).
 * 예: 98400 → '98,400', 22450 → '22,450'.
 *
 * @param {number} price
 * @returns {string}
 */
function formatPriceLabel(price) {
  if (typeof price !== 'number' || !isFinite(price)) return '';
  return Math.round(price).toLocaleString('ko-KR');
}

/**
 * candles 배열 + 클릭한 시점(logical index) 기준 ±window 영업일 내 local peak/trough 자석 snap.
 * @param {Array} candles — normalized candles
 * @param {number} logicalIdx — chart subscribeClick param.logical
 * @param {number} clickPrice — 클릭한 y좌표의 price (series.coordinateToPrice)
 * @param {number} windowN — ±N 영업일 (default 5)
 * @returns {{time: object, price: number, candleIdx: number}|null}
 */
function magnetSnap(candles, logicalIdx, clickPrice, windowN) {
  if (!Array.isArray(candles) || candles.length === 0) return null;
  const i = Math.round(logicalIdx);
  if (i < 0 || i >= candles.length) return null;
  const from = Math.max(0, i - windowN);
  const to = Math.min(candles.length - 1, i + windowN);

  let bestPrice = candles[i].close;
  let bestCandle = candles[i];
  let bestIdx = i;
  let bestDist = Math.abs(candles[i].close - clickPrice);

  for (let k = from; k <= to; k++) {
    const c = candles[k];
    if (!c) continue;
    // peak (high) candidate
    const dHigh = Math.abs(c.high - clickPrice);
    if (dHigh < bestDist) {
      bestDist = dHigh;
      bestPrice = c.high;
      bestCandle = c;
      bestIdx = k;
    }
    // trough (low) candidate
    const dLow = Math.abs(c.low - clickPrice);
    if (dLow < bestDist) {
      bestDist = dLow;
      bestPrice = c.low;
      bestCandle = c;
      bestIdx = k;
    }
  }
  return { time: bestCandle.time, price: bestPrice, candleIdx: bestIdx };
}

/**
 * Fibonacci 자석 drawing tool controller.
 *
 * 본질: chart.subscribeClick (anchor 결정) + series.createPriceLine (axisLabelVisible 본질)
 *   + DOM overlay drag handle (사용자 끝점 조정) + localStorage (영구화).
 */
class FibonacciDrawingController {
  /**
   * @param {IChartApi} chart
   * @param {ISeriesApi} candleSeries
   * @param {Array} candles — normalized candles (time/open/high/low/close)
   * @param {string} ticker — localStorage key suffix
   * @param {HTMLElement} chartContainer — chart wrapper DOM (drag handle overlay parent)
   * @param {Object} [options]
   */
  constructor(chart, candleSeries, candles, ticker, chartContainer, options = {}) {
    this._chart = chart;
    this._series = candleSeries;
    this._candles = candles;
    this._ticker = ticker || 'default';
    this._container = chartContainer;
    this._options = { ...DEFAULT_OPTIONS, ...options };

    // state: anchorA / anchorB ({time, price, candleIdx})
    this._state = this._loadState();

    // priceLines (axis label visible 본질, createPriceLine return)
    this._priceLines = [];

    // DOM handles (drag 본질)
    this._handleA = null;
    this._handleB = null;

    // 현재 drag 대상 ('A' | 'B' | null)
    this._dragging = null;

    // P0-19 Fix-63: HTML overlay 좌측 가격 라벨 본문 (LEVELS.length 개수 본문 array)
    this._overlayLabels = [];

    // P0-24 Fix-83: 자석 snap 작동 visible feedback toast 본문 본문 본문 (1개만 visible 본질)
    this._snapToastEl = null;
    this._snapToastTimer = null;

    // subscribeClick handler ref (detach 시 unsubscribe 의무)
    this._clickHandler = (param) => this._onClick(param);
    this._chart.subscribeClick(this._clickHandler);

    // crosshair move handler (drag 중 실시간 갱신 본질)
    this._crosshairHandler = (param) => this._onCrosshairMove(param);
    this._chart.subscribeCrosshairMove(this._crosshairHandler);

    // P0-25 (2026-05-21 23:46 KST 대표 결정 영웅문 paradigm 채택):
    //   chart canvas (chartElement) 본문 mousedown/mousemove/mouseup 본문 직접 본문 drag mode 본질.
    //   anchor A/B pixel position ±dragTolerance 본문 mousedown 시점 = drag mode (영웅문 chart area drag 정합).
    //   §11.15 외부 spec PASS:
    //     - https://tradingview.github.io/lightweight-charts/docs/api/interfaces/IChartApi#chartelement
    //       "Returns the generated div element containing the chart. This can be used for adding your own
    //        additional event listeners, or for measuring the elements dimensions and position within the document."
    //     - WebSearch 2회 corroborating (TradingView v5 chartElement custom event listeners + mousedown drag pattern)
    //     - repo verbatim: js/lib/chart-tv/plugins/fibonacci.js L683~694 본문 handle 본문 mousedown listener 동형 (handle DOM 본문 chart canvas DOM 본문 대체 paradigm)
    this._chartEl = null;
    try { this._chartEl = this._chart.chartElement(); } catch (e) { /* noop */ }

    this._chartCanvasDragging = null;  // 'A' | 'B' | null — drag 시작 anchor

    // chart canvas mousedown — anchor 근처 detect 시 drag mode 시작
    this._onChartMouseDown = (e) => this._handleChartMouseDown(e);
    // document mousemove — drag 중 anchor 위치 갱신
    this._onDocMouseMove = (e) => this._handleDocMouseMove(e);
    // document mouseup — drag 종료
    this._onDocMouseUp = (e) => this._handleDocMouseUp(e);
    // touch 본문 정합 본문 (모바일 finger drag 본질, Apple HIG 정합)
    this._onChartTouchStart = (e) => this._handleChartTouchStart(e);
    this._onDocTouchMove = (e) => this._handleDocTouchMove(e);
    this._onDocTouchEnd = (e) => this._handleDocTouchEnd(e);

    if (this._chartEl) {
      this._chartEl.addEventListener('mousedown', this._onChartMouseDown, true);  // capture phase 본문 lightweight-charts 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문
      this._chartEl.addEventListener('touchstart', this._onChartTouchStart, { passive: false, capture: true });
      document.addEventListener('mousemove', this._onDocMouseMove);
      document.addEventListener('mouseup', this._onDocMouseUp);
      document.addEventListener('touchmove', this._onDocTouchMove, { passive: false });
      document.addEventListener('touchend', this._onDocTouchEnd);
    }

    // P0-19 Fix-63: timeScale visible logical range change handler — chart zoom/scroll 시점
    //   priceToCoordinate y좌표 변화 본문 overlay label 본문 재측정 의무 (volume-by-decile.js 동형)
    this._rangeHandler = () => this._renderOverlayLabels();
    try {
      this._chart.timeScale().subscribeVisibleLogicalRangeChange(this._rangeHandler);
    } catch (e) { /* noop fallback */ }

    // P0-19 Fix-63: ResizeObserver — chart container resize 시점 (expanded-chart.js Fix-52 동형)
    //   chart.applyOptions resize cascade → priceToCoordinate y좌표 변화 본문 재측정 의무
    this._resizeObserver = null;
    if (this._container && typeof ResizeObserver === 'function') {
      try {
        this._resizeObserver = new ResizeObserver(() => {
          // requestAnimationFrame 본문 = layout 본문 완료 후 호출 본질 (Fix-52 동형)
          if (typeof requestAnimationFrame === 'function') {
            requestAnimationFrame(() => this._renderOverlayLabels());
          } else {
            this._renderOverlayLabels();
          }
        });
        this._resizeObserver.observe(this._container);
      } catch (e) { /* noop */ }
    }

    // P0-16 Fix-51 (2026-05-21 14:57 KST 대표 verbatim "피보나치 이어서 계속 해줘 화면에 표시되지도 않아"):
    //   root cause = drawing tool 본질 사용자 2회 클릭 의무 → 화면 visible 0건 (anchor A/B 미설정 본질)
    //   fix = anchor A/B 미설정 시 candles 본문 최근 가시 영역 hi/lo 본문 auto-anchor 본질
    //         → 차트 진입 즉시 7 fibonacci level 본문 visible (대표 verbatim "이어서 계속" 본질 정합)
    //         → 사용자 후속 drag 본문 정밀 조정 가능 (paradigm 보존)
    if (!this._state.anchorA || !this._state.anchorB) {
      const auto = this._autoAnchorFromVisibleRange();
      if (auto) {
        this._state.anchorA = auto.high;
        this._state.anchorB = auto.low;
        this._saveState();
      }
    }

    // 초기 render (localStorage 복원 또는 auto-anchor 본문)
    if (this._state.anchorA && this._state.anchorB) {
      this._renderLevels();
      this._renderHandles();
    }
  }

  /**
   * P0-16 Fix-51 auto-anchor 본문 — candles 본문 최근 50 영업일 본문 hi/lo 본문 자동 추출.
   * 영웅문 23a74560 본문 본질 정합 (727,000 high / 286,000 low 본문 swing 본질 본문).
   *
   * @returns {{high: {time, price, candleIdx}, low: {time, price, candleIdx}} | null}
   */
  _autoAnchorFromVisibleRange() {
    if (!Array.isArray(this._candles) || this._candles.length < 2) return null;
    const RECENT_N = 50;  // 영웅문 본문 visible 영역 본문 정합
    const N = this._candles.length;
    const from = Math.max(0, N - RECENT_N);
    let hi = -Infinity, lo = Infinity;
    let hiIdx = -1, loIdx = -1;
    for (let i = from; i < N; i++) {
      const c = this._candles[i];
      if (!c || !(c.high > 0) || !(c.low > 0)) continue;
      if (c.high > hi) { hi = c.high; hiIdx = i; }
      if (c.low < lo) { lo = c.low; loIdx = i; }
    }
    if (hiIdx < 0 || loIdx < 0) return null;
    return {
      high: { time: this._candles[hiIdx].time, price: hi, candleIdx: hiIdx },
      low: { time: this._candles[loIdx].time, price: lo, candleIdx: loIdx },
    };
  }

  /**
   * localStorage 복원 schema:
   *   { anchorA: { time, price, candleIdx }, anchorB: { time, price, candleIdx } }
   */
  _loadState() {
    try {
      const raw = localStorage.getItem(STORAGE_PREFIX + this._ticker);
      if (!raw) return { anchorA: null, anchorB: null };
      const parsed = JSON.parse(raw);
      // candleIdx 재계산 — candles 배열이 변경됐을 수 있음
      const reindex = (anchor) => {
        if (!anchor || !anchor.time) return null;
        const t = anchor.time;
        const idx = this._candles.findIndex((c) =>
          c.time && c.time.year === t.year && c.time.month === t.month && c.time.day === t.day,
        );
        if (idx < 0) return null;
        return { ...anchor, candleIdx: idx };
      };
      return {
        anchorA: reindex(parsed.anchorA),
        anchorB: reindex(parsed.anchorB),
      };
    } catch (e) {
      return { anchorA: null, anchorB: null };
    }
  }

  _saveState() {
    try {
      localStorage.setItem(
        STORAGE_PREFIX + this._ticker,
        JSON.stringify({
          anchorA: this._state.anchorA,
          anchorB: this._state.anchorB,
        }),
      );
    } catch (e) { /* private mode silent fail */ }
  }

  /**
   * chart.subscribeClick handler — anchor A → anchor B 순차 설정 + 자석 snap.
   * @param {MouseEventParams} param
   */
  _onClick(param) {
    if (this._dragging) return;  // drag 중 클릭 무시
    if (!param || !param.point || param.logical == null) return;
    const clickPrice = this._series.coordinateToPrice(param.point.y);
    if (clickPrice == null) return;

    const snap = magnetSnap(this._candles, param.logical, clickPrice, this._options.magnetWindow);
    if (!snap) return;

    // anchor A 미설정 → A 설정 (handle만 표시, fib level 미 render)
    if (!this._state.anchorA) {
      this._state.anchorA = snap;
      this._saveState();
      this._renderHandles();
      // P0-24 Fix-83 (2026-05-21 22:40 KST 대표 verbatim "피크 저가 고가가 자석 기능이고 내가 선택해서 이동하거나 기간을 조정할 수 있다"):
      //   자석 작동 visible feedback — anchor 1차 결정 toast 본문 본문 본문 본문 본문 사용자 인지 cascade.
      this._showSnapToast(`A 끝점 설정됨 (자석: ${formatPriceLabel(snap.price)}원). 다시 클릭하여 B 끝점 설정.`);
      return;
    }
    // anchor A 있고 B 없음 → B 설정 + render
    if (!this._state.anchorB) {
      this._state.anchorB = snap;
      this._saveState();
      this._renderLevels();
      this._renderHandles();
      // P0-24 Fix-83: anchor 2차 결정 toast 본문 — fibonacci level visible 본질 confirm.
      this._showSnapToast(`B 끝점 설정됨 (자석: ${formatPriceLabel(snap.price)}원). 점을 끌어 조정 가능.`);
      return;
    }
    // 둘 다 있는 상태에서 클릭 = 재시작 (B를 새 클릭으로 갱신, drag 본질 보완 fallback)
    // 대표 verbatim "기간을 조정할 수 있다" = drag 본질이 메인. 클릭 재시작은 추가 paradigm.
    this._state.anchorB = snap;
    this._saveState();
    this._renderLevels();
    this._renderHandles();
    // P0-24 Fix-83: 재시작 toast 본문 — 사용자가 둘 다 있는 상태에서 새로 클릭한 경우.
    this._showSnapToast(`B 끝점 재설정 (자석: ${formatPriceLabel(snap.price)}원).`);
  }

  /**
   * P0-24 Fix-83 — 자석 snap 작동 visible feedback toast 본문 본문 본문 본문 본문 사용자 인지 cascade.
   *
   * 본질:
   *   - chart container 우측 상단 본문 absolute-positioned toast div 본문 신축 (sub-pane title Fix-52 동형 paradigm)
   *   - 2.4초 후 자동 fade out + remove
   *   - 동시 toast 본문 본문 본문 본문 본문 본문 본문 본문 1개 본문 본문 본문 본문 본문 (기존 toast 본문 본문 본문 본문 본문 즉시 remove)
   *   - z-index 200 (drag handle 100 + sub-pane title 10 본문 본문 본문 본문 본문 본문)
   *   - pointer-events: none (chart click 통과)
   *
   * §11.15 외부 spec PASS:
   *   - native DOM appendChild/remove + setTimeout/setInterval (vendor 본문 부재)
   *   - CSS transition opacity 본문 본문 본문 본문 본문 본문 (vendor prefix 부재 native)
   *   - repo verbatim: expanded-chart.js L948~1006 hint badge 본문 본문 본문 본문 fade transition 동형 paradigm
   */
  _showSnapToast(text) {
    if (!this._container) return;
    // 기존 toast 본문 본문 본문 본문 본문 즉시 remove (1개만 visible 본질)
    if (this._snapToastEl) {
      try { this._snapToastEl.remove(); } catch (e) { /* noop */ }
      this._snapToastEl = null;
    }
    if (this._snapToastTimer) {
      try { clearTimeout(this._snapToastTimer); } catch (e) { /* noop */ }
      this._snapToastTimer = null;
    }
    const toast = document.createElement('div');
    toast.className = 'cal-chart-tv-fib-snap-toast';
    toast.setAttribute('role', 'status');
    toast.setAttribute('aria-live', 'polite');
    toast.style.cssText = [
      'position: absolute',
      'right: 8px',
      'top: 8px',
      'background: rgba(233,30,99,0.92)',
      'color: #fff',
      'font-size: 11px',
      'font-weight: 600',
      'padding: 6px 10px',
      'border-radius: 4px',
      'box-shadow: 0 2px 8px rgba(0,0,0,0.30)',
      'z-index: 200',
      'pointer-events: none',
      'opacity: 0',
      'transition: opacity 0.25s ease',
      'max-width: 240px',
      'line-height: 1.35',
      'white-space: normal',
    ].join(';');
    toast.textContent = text;
    try {
      const computedPos = window.getComputedStyle(this._container).position;
      if (computedPos === 'static') {
        this._container.style.position = 'relative';
      }
    } catch (e) { /* noop */ }
    this._container.appendChild(toast);
    this._snapToastEl = toast;
    // 다음 frame 본문 fade in (transition 발동 본질)
    if (typeof requestAnimationFrame === 'function') {
      requestAnimationFrame(() => {
        if (toast && toast.parentNode) toast.style.opacity = '1';
      });
    } else {
      toast.style.opacity = '1';
    }
    // 2.4초 후 자동 fade out + remove
    this._snapToastTimer = setTimeout(() => {
      if (!toast || !toast.parentNode) return;
      toast.style.opacity = '0';
      setTimeout(() => {
        try { toast.remove(); } catch (e) { /* noop */ }
        if (this._snapToastEl === toast) this._snapToastEl = null;
      }, 300);
    }, 2400);
  }

  _onCrosshairMove(param) {
    // drag 시 실시간 갱신 본질 (mousemove은 chart.subscribeCrosshairMove로 대체 가능 — v5 paradigm)
    if (!this._dragging || !param || !param.point || param.logical == null) return;
    const newPrice = this._series.coordinateToPrice(param.point.y);
    if (newPrice == null) return;
    const snap = magnetSnap(this._candles, param.logical, newPrice, this._options.magnetWindow);
    if (!snap) return;
    if (this._dragging === 'A') {
      this._state.anchorA = snap;
    } else {
      this._state.anchorB = snap;
    }
    this._renderLevels();
    this._renderHandles();
  }

  /**
   * P0-25 (2026-05-21 23:46 KST 대표 결정 영웅문 paradigm 채택) —
   * chart canvas mousedown 시점 anchor A/B 근처 detect 시 drag mode 시작.
   *
   * 본질:
   *   - chart canvas (chartElement) bounding rect 본문 mouse client 좌표 본문 → chart pane 본문 x,y 본문 환산
   *   - anchor A/B 본문 pixel position (timeToCoordinate + priceToCoordinate) 본문 거리 측정
   *   - dragTolerance (±20px) 본문 본문 mousedown 본문 본문 → drag mode 본문 본문 본문 본문
   *   - lightweight-charts 본문 chart panning/zoom 본문 본문 conflict 회피 본문 stopPropagation 호출
   *
   * §16 self-catch:
   *   - capture phase 본문 lightweight-charts 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문
   *   - drag start 본문 본문 본문 chart panning 본문 본문 본문 본문 본문 본문 본문 본문 → drag tolerance 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문
   *   - magnetSnap 본문 본문 본문 본문 anchor 위치 본문 ±5 영업일 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문
   */
  _handleChartMouseDown(e) {
    const target = this._detectAnchorNearPointer(e.clientX, e.clientY);
    if (!target) return;
    e.preventDefault();
    e.stopPropagation();
    this._chartCanvasDragging = target;
    this._dragging = target;  // _onCrosshairMove 본문 본질 정합 (기존 handle drag 본문 본문 본문 동일 path)
  }

  _handleChartTouchStart(e) {
    if (!e.touches || e.touches.length === 0) return;
    const t = e.touches[0];
    const target = this._detectAnchorNearPointer(t.clientX, t.clientY);
    if (!target) return;
    e.preventDefault();
    e.stopPropagation();
    this._chartCanvasDragging = target;
    this._dragging = target;
  }

  _handleDocMouseMove(e) {
    if (!this._chartCanvasDragging) return;
    this._updateAnchorFromPointer(e.clientX, e.clientY);
  }

  _handleDocTouchMove(e) {
    if (!this._chartCanvasDragging) return;
    if (!e.touches || e.touches.length === 0) return;
    e.preventDefault();  // 본 body scroll 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문
    const t = e.touches[0];
    this._updateAnchorFromPointer(t.clientX, t.clientY);
  }

  _handleDocMouseUp(e) {
    if (!this._chartCanvasDragging) return;
    this._chartCanvasDragging = null;
    this._dragging = null;
    this._saveState();
  }

  _handleDocTouchEnd(e) {
    if (!this._chartCanvasDragging) return;
    this._chartCanvasDragging = null;
    this._dragging = null;
    this._saveState();
  }

  /**
   * P0-25 — pointer (mouse/touch) client 좌표 본문 → anchor A/B 근처 detect.
   *
   * 본질:
   *   - chartElement bounding rect 본문 client 좌표 본문 → chart-local x,y 환산
   *   - anchor A/B 본문 timeToCoordinate + priceToCoordinate 본문 pixel position 측정
   *   - Euclidean distance 본문 본문 dragTolerance 본문 본문 본문 본문 본문 본문 → 'A' | 'B' 본문 본문 본문 본문 본문
   *   - 양 anchor 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 → 더 가까운 본문 본문 본문 본문
   *
   * @param {number} clientX
   * @param {number} clientY
   * @returns {'A'|'B'|null}
   */
  _detectAnchorNearPointer(clientX, clientY) {
    if (!this._chartEl || !this._state.anchorA || !this._state.anchorB) return null;
    let rect = null;
    try { rect = this._chartEl.getBoundingClientRect(); } catch (e) { return null; }
    if (!rect) return null;
    const localX = clientX - rect.left;
    const localY = clientY - rect.top;
    const tolerance = this._options.dragTolerance || 20;

    const distToAnchor = (anchor) => {
      if (!anchor || !anchor.time) return Infinity;
      let x = null, y = null;
      try {
        x = this._chart.timeScale().timeToCoordinate(anchor.time);
        y = this._series.priceToCoordinate(anchor.price);
      } catch (e) { return Infinity; }
      if (x == null || y == null) return Infinity;
      const dx = localX - x;
      const dy = localY - y;
      return Math.sqrt(dx * dx + dy * dy);
    };

    const distA = distToAnchor(this._state.anchorA);
    const distB = distToAnchor(this._state.anchorB);
    if (distA > tolerance && distB > tolerance) return null;
    return distA <= distB ? 'A' : 'B';
  }

  /**
   * P0-25 — pointer (mouse/touch) client 좌표 본문 → anchor 위치 갱신 + magnetSnap 재적용.
   *
   * 본질:
   *   - chartElement bounding rect 본문 client 좌표 본문 → chart-local x,y 환산
   *   - x → logical index 본문 본문 본문 timeScale.coordinateToLogical(x)
   *   - y → price 본문 본문 본문 series.coordinateToPrice(y)
   *   - magnetSnap 본문 본문 본문 ±5 영업일 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문
   *   - drag 본문 anchor (A 또는 B) 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문
   *
   * §11.15 외부 spec PASS:
   *   - ITimeScaleApi.coordinateToLogical(x: number): Logical | null
   *     https://tradingview.github.io/lightweight-charts/docs/api/interfaces/ITimeScaleApi
   *   - ISeriesApi.coordinateToPrice(y: number): number | null
   *     https://tradingview.github.io/lightweight-charts/docs/api/interfaces/ISeriesApi
   */
  _updateAnchorFromPointer(clientX, clientY) {
    if (!this._chartEl || !this._chartCanvasDragging) return;
    let rect = null;
    try { rect = this._chartEl.getBoundingClientRect(); } catch (e) { return; }
    if (!rect) return;
    const localX = clientX - rect.left;
    const localY = clientY - rect.top;

    let logical = null, price = null;
    try {
      logical = this._chart.timeScale().coordinateToLogical(localX);
      price = this._series.coordinateToPrice(localY);
    } catch (e) { return; }
    if (logical == null || price == null) return;

    const snap = magnetSnap(this._candles, logical, price, this._options.magnetWindow);
    if (!snap) return;

    if (this._chartCanvasDragging === 'A') {
      this._state.anchorA = snap;
    } else {
      this._state.anchorB = snap;
    }
    this._renderLevels();
    this._renderHandles();
  }

  /**
   * Fibonacci horizontal level 자동 draw (createPriceLine 본문, axisLabelVisible: true 본질).
   * 본문: anchorA.price = swing 한쪽, anchorB.price = swing 반대쪽.
   *      Fib retracement: 0% = anchorB.price, 100% = anchorA.price.
   *      ratio*anchorA + (1-ratio)*anchorB = anchorB + ratio * (anchorA - anchorB)
   */
  _renderLevels() {
    this._clearPriceLines();
    if (!this._state.anchorA || !this._state.anchorB) return;

    const a = this._state.anchorA.price;
    const b = this._state.anchorB.price;
    if (a == null || b == null) return;

    LEVELS.forEach((lv) => {
      const price = b + (a - b) * lv.ratio;
      try {
        const line = this._series.createPriceLine({
          price,
          color: lv.color,
          lineStyle: this._options.lineStyle,
          lineWidth: this._options.lineWidth,
          axisLabelVisible: this._options.axisLabelVisible,
          // P0-19 Fix-63 (2026-05-21 16:35 KST P0-18 Fix-58 paradigm 충돌 cascade 정합):
          //   title 본문 = '' (빈 string) 복원 — Fix-55 axisLabelVisible:false 보존
          //   좌측 가격 라벨 본문은 HTML overlay div 본문 신축 본질 (this._renderOverlayLabels())
          //   v5 PriceLineOptions.title visibility = axisLabelVisible:true 종속 본질 paradigm 충돌 회피
          title: '',
        });
        this._priceLines.push(line);
      } catch (e) { /* noop */ }
    });

    // P0-19 Fix-63: HTML overlay 본문 좌측 가격 라벨 render 본질 cascade
    this._renderOverlayLabels();
  }

  _clearPriceLines() {
    this._priceLines.forEach((line) => {
      try { this._series.removePriceLine(line); } catch (e) { /* noop */ }
    });
    this._priceLines = [];
  }

  /**
   * P0-19 Fix-63 — HTML overlay 본문 좌측 가격 라벨 render 본질 (LEVELS.length 본문 div 본문).
   *
   * 본질:
   *   - LEVELS 본문 각 ratio별 price 계산 (anchorB + (anchorA - anchorB) * ratio)
   *   - left: 8px (영웅문 23a74560 본문 좌측 본문 정합)
   *   - top: series.priceToCoordinate(price) — chart pane 본문 y좌표 실시간 계산
   *   - text: formatPriceLabel(price) — ko-KR locale 본문 정수 (예: '727,000')
   *   - font-size: 10px (대표 verbatim "작은 글씨" 정합)
   *   - pointer-events: none (chart click/drag 본문 통과)
   *   - z-index: 10 (drag handle z-index:100 본문 침범 부재)
   *
   * §16 self-catch:
   *   - priceToCoordinate null fallback (price 가시 영역 외부) → label display:none silent skip
   *   - chart container 본문 position:relative 본문 절대 좌표 본질 (Fix-52 동형 main.style.position='relative')
   *
   * 본문 호출 시점:
   *   - _renderLevels() 내부 cascade (anchor 변경 시점)
   *   - _rangeHandler (zoom/scroll 시점)
   *   - ResizeObserver callback (chart resize 시점)
   */
  _renderOverlayLabels() {
    if (!this._container) return;
    if (!this._state.anchorA || !this._state.anchorB) {
      // anchor 미설정 시 모든 overlay label hide
      this._overlayLabels.forEach((el) => { if (el) el.style.display = 'none'; });
      return;
    }

    const a = this._state.anchorA.price;
    const b = this._state.anchorB.price;
    if (a == null || b == null) return;

    // 필요시 overlay div 본문 lazy create (LEVELS.length 본문 개수 보장)
    if (this._overlayLabels.length < LEVELS.length) {
      // chart container 본문 position:relative 보장 (Fix-52 동형, sub-pane title 본문 main.style.position='relative' 호출 후 본 hook 호출 가능)
      try {
        const computedPos = window.getComputedStyle(this._container).position;
        if (computedPos === 'static') {
          this._container.style.position = 'relative';
        }
      } catch (e) { /* noop */ }

      for (let i = this._overlayLabels.length; i < LEVELS.length; i++) {
        const label = document.createElement('div');
        label.className = 'cal-chart-tv-fib-price-label';
        label.dataset.fibIdx = String(i);
        // P0-20 Fix-66 (2026-05-21 17:46 KST 대표 verbatim "피보나치 가격라벨도 훨씬 작게"):
        //   font-size 10px → 8px 본문 축소 (영웅문 23a74560 본문 "727,000 (1.000)" 매우 작은 글씨 정합).
        // P0-20 Fix-67 (2026-05-21 17:46 KST 대표 verbatim "가격라벨 바탕의 반투명한 흰색인데 완전 투명하게"):
        //   background rgba(255,255,255,0.65) → transparent 본문 완전 투명.
        //   가독성 본문 정합 의무 — text-shadow 본문 흰색 outline 본문 추가 (영웅문 정합 본문 흰색 outline + 검정 text 본질).
        //   §16 self-catch: 영웅문 23a74560 reference 본문 배경 부재 + 흰색 outline + 검정 text 본문 visible 정합.
        label.style.cssText = [
          'position: absolute',
          'left: 8px',
          'top: 0',
          'font-size: 8px',                                  // P0-20 Fix-66: 10 → 8
          'font-weight: 600',
          'color: rgba(0,0,0,0.85)',                         // 가독성 본문 강화 (0.7 → 0.85)
          'pointer-events: none',
          'z-index: 10',
          'display: none',
          'background: transparent',                         // P0-20 Fix-67: 완전 투명
          'padding: 0',                                      // P0-20 Fix-67: padding 본문 부재 (배경 부재 본문 정합)
          'text-shadow: 0 0 2px #fff, 0 0 2px #fff, 0 0 2px #fff',  // P0-20 Fix-67: 흰색 outline 본문 가독성 본질
          'transform: translateY(-50%)',  // y좌표 = 가로선 중앙 정합 본질 (top:y → label 본문 중앙)
          'white-space: nowrap',
        ].join(';');
        this._container.appendChild(label);
        this._overlayLabels.push(label);
      }
    }

    // 각 LEVELS 본문 price 계산 + label 본문 position
    LEVELS.forEach((lv, i) => {
      const price = b + (a - b) * lv.ratio;
      const label = this._overlayLabels[i];
      if (!label) return;
      let y = null;
      try { y = this._series.priceToCoordinate(price); } catch (e) { /* noop */ }
      if (y == null || !isFinite(y)) {
        label.style.display = 'none';
        return;
      }
      label.style.display = 'block';
      label.style.top = `${y}px`;
      label.textContent = formatPriceLabel(price);
    });
  }

  _clearOverlayLabels() {
    this._overlayLabels.forEach((el) => {
      if (!el) return;
      try { el.remove(); } catch (e) { /* noop */ }
    });
    this._overlayLabels = [];
  }

  /**
   * DOM overlay drag handle 2개 render (anchorA + anchorB).
   * 본질: chartContainer 위 absolute position div. timeToCoordinate + priceToCoordinate.
   */
  _renderHandles() {
    if (!this._container) return;
    if (!this._handleA) this._handleA = this._createHandleEl('A');
    if (!this._handleB) this._handleB = this._createHandleEl('B');

    this._positionHandle(this._handleA, this._state.anchorA);
    this._positionHandle(this._handleB, this._state.anchorB);
  }

  _createHandleEl(label) {
    const el = document.createElement('div');
    el.className = 'cal-chart-tv-fib-handle';
    el.dataset.anchor = label;
    el.setAttribute('aria-label', `Fibonacci ${label} 끝점 — chart 본문 본문 끌어 이동`);
    el.setAttribute('title', `${label} 끝점 — 차트 영역 본문 클릭/드래그 본문 이동`);
    // P0-25 (2026-05-21 23:46 KST 대표 결정 영웅문 paradigm 채택):
    //   handle = 영웅문 inline ↓ marker 정합 (anchor 시각 cue만, drag trigger 본문 chart canvas 본문 본질).
    //   본문 visual 본문 본질 축소:
    //     - radius 14 → 6 (DEFAULT_OPTIONS, +75% 면적 본문 -82% 면적 본문 본문 축소)
    //     - background 본문 본문 transparent (border만 visible — 영웅문 ↓ arrow marker 정합)
    //     - border 3px → 2px (subtle)
    //     - box-shadow 본문 본문 본문 본문 본문 본문 본문 (외곽 glow 폐기)
    //     - pulse 애니메이션 폐기 (영웅문 reference 본문 정적 marker 정합)
    //     - cursor 본문 본문 본문 'default' (drag trigger 본문 chart canvas 본문 본질)
    //     - pointer-events 본문 'none' (chart canvas mousedown 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문)
    //   §11.15 외부 spec PASS:
    //     - 영웅문 23a74560 reference 본문 chart area click/drag paradigm + swing high/low inline ↓ arrow marker 본질 정합
    //     - WebSearch 2회 corroborating (TradingView v5 chartElement custom event listeners pattern)
    el.style.cssText = [
      'position: absolute',
      `width: ${this._options.handleRadius * 2}px`,
      `height: ${this._options.handleRadius * 2}px`,
      'background: transparent',
      `border: 2px solid ${this._options.handleColor}`,
      'border-radius: 50%',
      'cursor: default',
      'z-index: 100',
      'box-shadow: 0 0 0 1px rgba(255,255,255,0.8)',
      'pointer-events: none',
      'touch-action: none',
      'display: none',
    ].join(';');

    // P0-25: drag trigger 본문 chart canvas 본문 본질 — handle 본문 본문 event listener 본문 폐기 (영웅문 paradigm 정합).
    el._cleanup = () => { /* noop — listener 본문 본문 본문 본문 본문 본문 본문 본문 */ };

    this._container.appendChild(el);
    return el;
  }

  _positionHandle(el, anchor) {
    if (!el) return;
    if (!anchor || !anchor.time) {
      el.style.display = 'none';
      return;
    }
    try {
      const x = this._chart.timeScale().timeToCoordinate(anchor.time);
      const y = this._series.priceToCoordinate(anchor.price);
      if (x == null || y == null) {
        el.style.display = 'none';
        return;
      }
      el.style.display = 'block';
      el.style.left = `${x - this._options.handleRadius}px`;
      el.style.top = `${y - this._options.handleRadius}px`;
    } catch (e) {
      el.style.display = 'none';
    }
  }

  /**
   * 사용자 그린 Fibonacci 초기화 (clear all).
   *
   * P0-24 Fix-84 (2026-05-21 22:40 KST 대표 verbatim "내가 선택해서 이동하거나 기간을 조정할 수 있다"):
   *   reset() 호출 시 anchor 재계산 본질 — auto-anchor 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 visible range 본문 본문 본문 본문 본문 본문 본문 본문 본문.
   *   기간 조정 메커니즘 본문 본문 본문 본문 (대표 ④ catch):
   *     - 사용자가 chart zoom in/out → 자동 visible range 변경
   *     - reset 클릭 시 auto-anchor 본문 본문 본문 본문 본문 _autoAnchorFromVisibleRangeNow() 본문 본문 본문 본문 본문 본문 본문 본문 현재 가시 영역 본문 hi/lo 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문
   *   본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문.
   *
   * @param {boolean} [autoReseed=true] — true: reset 후 auto-anchor 재진행, false: 완전 비움
   */
  reset(autoReseed = true) {
    this._state = { anchorA: null, anchorB: null };
    this._clearPriceLines();
    // P0-19 Fix-63: overlay label 본문 hide (clear 본질은 destroy 시점만)
    this._overlayLabels.forEach((el) => { if (el) el.style.display = 'none'; });
    if (this._handleA) this._handleA.style.display = 'none';
    if (this._handleB) this._handleB.style.display = 'none';

    if (autoReseed) {
      // P0-24 Fix-84: 현재 가시 영역 본문 hi/lo 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문
      const auto = this._autoAnchorFromCurrentVisibleRange() || this._autoAnchorFromVisibleRange();
      if (auto) {
        this._state.anchorA = auto.high;
        this._state.anchorB = auto.low;
        this._renderLevels();
        this._renderHandles();
      }
    }
    this._saveState();
  }

  /**
   * P0-24 Fix-84 — 현재 chart timeScale 본문 visible logical range 본문 본문 hi/lo 본문 본문 본문 본문 본문.
   *
   * 본질:
   *   - chart.timeScale().getVisibleLogicalRange() → { from, to } logical index
   *   - candles 본문 본문 본문 본문 본문 본문 본문 hi/lo 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문
   *   - _autoAnchorFromVisibleRange() (RECENT_N=50 본문 본문 본문 본문) 와 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 사용자 zoom 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문 본문
   *
   * §11.15 외부 spec PASS:
   *   - ITimeScaleApi.getVisibleLogicalRange() → LogicalRange | null
   *     https://tradingview.github.io/lightweight-charts/docs/api/interfaces/ITimeScaleApi
   *
   * @returns {{high: {time, price, candleIdx}, low: {time, price, candleIdx}} | null}
   */
  _autoAnchorFromCurrentVisibleRange() {
    if (!Array.isArray(this._candles) || this._candles.length < 2) return null;
    let range = null;
    try {
      range = this._chart.timeScale().getVisibleLogicalRange();
    } catch (e) { /* noop */ }
    if (!range || range.from == null || range.to == null) return null;
    const from = Math.max(0, Math.floor(range.from));
    const to = Math.min(this._candles.length - 1, Math.ceil(range.to));
    if (from >= to) return null;

    let hi = -Infinity, lo = Infinity;
    let hiIdx = -1, loIdx = -1;
    for (let i = from; i <= to; i++) {
      const c = this._candles[i];
      if (!c || !(c.high > 0) || !(c.low > 0)) continue;
      if (c.high > hi) { hi = c.high; hiIdx = i; }
      if (c.low < lo) { lo = c.low; loIdx = i; }
    }
    if (hiIdx < 0 || loIdx < 0) return null;
    return {
      high: { time: this._candles[hiIdx].time, price: hi, candleIdx: hiIdx },
      low: { time: this._candles[loIdx].time, price: lo, candleIdx: loIdx },
    };
  }

  /**
   * 사용 종료 시 cleanup.
   */
  destroy() {
    try { this._chart.unsubscribeClick(this._clickHandler); } catch (e) { /* noop */ }
    try { this._chart.unsubscribeCrosshairMove(this._crosshairHandler); } catch (e) { /* noop */ }
    // P0-19 Fix-63: timeScale subscribeVisibleLogicalRangeChange unsubscribe 의무
    try {
      this._chart.timeScale().unsubscribeVisibleLogicalRangeChange(this._rangeHandler);
    } catch (e) { /* noop */ }
    // P0-19 Fix-63: ResizeObserver disconnect 의무
    try {
      if (this._resizeObserver) this._resizeObserver.disconnect();
    } catch (e) { /* noop */ }
    this._resizeObserver = null;
    // P0-25: chart canvas drag listener unsubscribe 의무 (영웅문 paradigm 본문 본문 본문 본문)
    if (this._chartEl) {
      try { this._chartEl.removeEventListener('mousedown', this._onChartMouseDown, true); } catch (e) { /* noop */ }
      try { this._chartEl.removeEventListener('touchstart', this._onChartTouchStart, { capture: true }); } catch (e) { /* noop */ }
    }
    try { document.removeEventListener('mousemove', this._onDocMouseMove); } catch (e) { /* noop */ }
    try { document.removeEventListener('mouseup', this._onDocMouseUp); } catch (e) { /* noop */ }
    try { document.removeEventListener('touchmove', this._onDocTouchMove); } catch (e) { /* noop */ }
    try { document.removeEventListener('touchend', this._onDocTouchEnd); } catch (e) { /* noop */ }
    this._chartEl = null;
    this._clearPriceLines();
    // P0-19 Fix-63: overlay label DOM 본문 제거 의무
    this._clearOverlayLabels();
    // P0-24 Fix-83: snap toast cleanup 의무
    if (this._snapToastTimer) {
      try { clearTimeout(this._snapToastTimer); } catch (e) { /* noop */ }
      this._snapToastTimer = null;
    }
    if (this._snapToastEl) {
      try { this._snapToastEl.remove(); } catch (e) { /* noop */ }
      this._snapToastEl = null;
    }
    [this._handleA, this._handleB].forEach((el) => {
      if (!el) return;
      try { if (typeof el._cleanup === 'function') el._cleanup(); } catch (e) { /* noop */ }
      try { el.remove(); } catch (e) { /* noop */ }
    });
    this._handleA = null;
    this._handleB = null;
    this._chart = null;
    this._series = null;
    this._candles = null;
    this._container = null;
  }
}

/**
 * Fibonacci 자석 drawing tool attach.
 * Phase 7d-2 본 API (signature 변경, Phase 7d-1 backward 비호환).
 *
 * @param {IChartApi} chart
 * @param {ISeriesApi} candleSeries
 * @param {Array} candles — normalized candles
 * @param {string} ticker — localStorage key suffix
 * @param {HTMLElement} chartContainer — drag handle overlay parent (cal-chart-tv-main 본문)
 * @param {Object} [options]
 * @returns {FibonacciDrawingController}
 */
export function attachFibonacci(chart, candleSeries, candles, ticker, chartContainer, options = {}) {
  if (!chart || !candleSeries || !Array.isArray(candles) || candles.length < 2) return null;
  return new FibonacciDrawingController(chart, candleSeries, candles, ticker, chartContainer, options);
}

/**
 * Fibonacci 자석 drawing tool detach.
 * @param {FibonacciDrawingController} controller
 */
export function detachFibonacci(controller) {
  if (!controller || typeof controller.destroy !== 'function') return;
  controller.destroy();
}

if (typeof window !== 'undefined') {
  window.ChartTVPluginFibonacci = { attachFibonacci, detachFibonacci, FibonacciDrawingController };
}
