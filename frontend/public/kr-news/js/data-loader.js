/* ───── data-loader.js — 데이터 fetch/캐시 ───── */

let themesData = null;
let _themeTreeCache = null;

async function loadThemes() {
  try {
    const res = await fetch('data/themes/themes.json');
    if (!res.ok) throw new Error('themes.json HTTP ' + res.status);
    return await res.json();
  } catch (e) { return null; }
}


// v6 (묶음 3): kiwoom index 캐시 — 404 소음 제거
let _kiwoomIndexCache = null;
let _kiwoomIndexPromise = null;

async function loadKiwoomIndex() {
  if (_kiwoomIndexCache) return _kiwoomIndexCache;
  if (_kiwoomIndexPromise) return _kiwoomIndexPromise;
  _kiwoomIndexPromise = (async () => {
    try {
      const res = await fetch('data/kiwoom/index.json');
      if (!res.ok) throw new Error('kiwoom/index.json HTTP ' + res.status);
      const d = await res.json();
      _kiwoomIndexCache = d;
      return d;
    } catch (e) {
      return null;
    } finally {
      _kiwoomIndexPromise = null;
    }
  })();
  return _kiwoomIndexPromise;
}

// DSN-frontend §3.6.2.2 (2026-05-28 대표 직접 발화) — 오늘 view + 장 시작 후 어제 데이터 fallback 차단.
// 대표 verbatim: "9시부터 종목검색 결과가 있을 때까지 어제걸 보여주는게 과연 맞는걸까? 무슨 이점이 있지?"
//                "없으면 없다고 알려주는게 더 신뢰도나 활용면에서 좋자않나?"
// 본 helper — date === today (KST) + 09:00 이후 일 때 true.
// PRE_MARKET (09:00 미만)은 renderPreMarketEmpty의 사용자 opt-in 토글 path가 별도로 처리하므로 본 guard 대상 아님.
// 과거 viewDate (date < today)는 정상적으로 해당일 데이터 표시 (fallback 자체가 부적절).
// timezone: 브라우저 로컬 가정 (KST 사용자 기준). 5/27 freshness 라벨 _computeFreshnessLabel과 동일 가정.
function _isTodayPastOpen(date) {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  const todayKst = `${y}-${m}-${d}`;
  if (date !== todayKst) return false;
  return now.getHours() >= 9; // KST 장 시작 시각
}

async function loadKiwoomDate(date) {
  const dateHash = date.replace(/-/g, '');
  // v6: index 선행 조회하여 존재하지 않는 날짜는 fetch 자체를 건너뛴다 (404 소음 제거).
  const idx = await loadKiwoomIndex();
  const idxDates = idx && Array.isArray(idx.dates) ? idx.dates : null;
  const dateExists = idxDates ? idxDates.includes(date) : true; // index 없으면 기존 동작 유지
  if (dateExists) {
    try {
      const res = await fetch(`data/kiwoom/${date}.json?v=${dateHash}`);
      if (res.ok) return await res.json();
    } catch (e) { /* fall through */ }
  }
  // 폴백 1: stock-*.json에서 종목 리스트 추출 (당일)
  try {
    const fb = await fetch(`data/interpreted/stock-${date}.json?v=${dateHash}`);
    if (fb.ok) {
      const d = await fb.json();
      if (d.stocks && d.stocks.length > 0) {
        return { daily_top: d.stocks.map(s => ({
          ticker: s.code, name: s.name, rank: s.rank,
          max_trade_amount: s.trade_amount, max_change_pct: s.change_pct
        })) };
      }
    }
  } catch (e) { /* ignore */ }
  // 폴백 2: index의 가장 최근 날짜로 kiwoom 데이터 폴백 (오늘 파이프라인 수집 전)
  // DSN-frontend §3.6.2.2 (2026-05-28) — 오늘 view + 09:00 이후 시 본 fallback 차단.
  //   기존 동작 (어제 데이터 표시) → 사용자 매매 판단 misread risk.
  //   휴장일/과거 viewDate에 한해 fallback 유지 (해당 날짜에 데이터 부재 시 가장 가까운 데이터 보충).
  if (!dateExists && idxDates && idxDates.length > 0 && !_isTodayPastOpen(date)) {
    const latest = [...idxDates].sort().pop();
    if (latest && latest !== date) {
      try {
        const latestHash = latest.replace(/-/g, '');
        const res = await fetch(`data/kiwoom/${latest}.json?v=${latestHash}`);
        if (res.ok) {
          const d = await res.json();
          d._fallback_date = latest;
          return d;
        }
      } catch (e) { /* ignore */ }
    }
  }
  return null;
}

async function loadCalendarIndex() {
  try {
    const res = await fetch('data/calendar/index.json');
    if (!res.ok) return null;
    return await res.json();
  } catch (e) { return null; }
}

async function loadHolidayData() {
  try {
    const res = await fetch('data/holidays.json');
    if (!res.ok) return null;
    return await res.json();
  } catch (e) { return null; }
}

async function loadCalDayData(date) {
  if (calDayCache[date]) return calDayCache[date];
  // kiwoom + stock-daily를 병렬 fetch
  const dateHash = date.replace(/-/g, '');
  const [kiwoom, stockDailyDirect] = await Promise.all([
    loadKiwoomDate(date),
    fetch(`data/interpreted/${calCategory}-${date}.json?v=${dateHash}`).then(r => r.ok ? r.json() : null).catch(() => null)
  ]);
  let stockDailyData = stockDailyDirect;
  // REQ-055 P0 — 당일 stock JSON이 stocks=[] 빈 데이터인 경우도 fallback 대상.
  //   배포 직후/장 시작 전 build_daily.py가 빈 stocks=[] 파일을 생성하면 truthy로 평가되어
  //   fallback이 동작하지 않고 카드/sparkline/themes_chip이 모두 비어 보이는 결함 (4/28 07:50 KST 사례).
  //   stocks가 1건이라도 있어야 해석으로 인정. macro_events/generated_at만 있는 빈 파일은 무시.
  const _hasStockEntries = (sd) => !!(sd && Array.isArray(sd.stocks) && sd.stocks.length > 0);
  // 당일 데이터 없거나 stocks 비었으면 최근 7일 이내 이전 날짜 fallback (병렬)
  // 단, 휴장일/주말은 fallback 자체를 비활성화 (옵션 A: 휴장 안내만 표시)
  // DSN-frontend §3.6.2.2 (2026-05-28) — 오늘 view + 09:00 이후 시 본 fallback 차단.
  //   기존 동작 (어제 stock-daily 데이터 표시) → 사용자 매매 판단 misread risk.
  //   renderer.js empty-state path가 시간대별 메시지 ("데이터 수집 중" / "수집 이상")로 정직하게 고지.
  if (!_hasStockEntries(stockDailyData) && !isMarketClosed(date) && !_isTodayPastOpen(date)) {
    // REQ-055 P0 — toISOString()는 KST→UTC 변환되어 하루 전 날짜를 반환하는 버그.
    //   `new Date('2026-04-28T00:00:00')` (KST 자정) → UTC `2026-04-27T15:00:00Z`
    //   → `setDate(-1)` 후 toISOString() → '2026-04-26' (4/27 건너뜀, 4/24가 첫 PASS로 잡힘 사례).
    //   날짜 산술은 로컬 시간 기준 getFullYear/getMonth/getDate 사용.
    const _localYmd = (dt) => {
      const y = dt.getFullYear();
      const m = String(dt.getMonth() + 1).padStart(2, '0');
      const d = String(dt.getDate()).padStart(2, '0');
      return `${y}-${m}-${d}`;
    };
    const d = new Date(date + 'T00:00:00');
    const fallbackFetches = [];
    for (let i = 1; i <= 7; i++) {
      const prev = new Date(d);
      prev.setDate(prev.getDate() - i);
      const prevStr = _localYmd(prev);
      const prevHash = prevStr.replace(/-/g, '');
      fallbackFetches.push(
        fetch(`data/interpreted/${calCategory}-${prevStr}.json?v=${prevHash}`)
          .then(r => r.ok ? r.json().then(j => _hasStockEntries(j) ? { date: prevStr, data: j } : null) : null)
          .catch(() => null)
      );
    }
    const results = (await Promise.all(fallbackFetches)).filter(Boolean);
    if (results.length > 0) {
      // 가장 최근 날짜 우선 (i=1부터 순서대로 fetch했지만 Promise.all 순서 보장 — 첫 entry가 가장 가까운 과거)
      stockDailyData = results[0].data;
      stockDailyData._fallback_date = results[0].date;
    }
  }
  // 종목명 → 해석 stock 객체 병합 맵
  const interpretedByName = new Map();
  let macroEvents = [];
  // Phase 1 뉴스 파이프라인 산출물 (stock-YYYY-MM-DD.json) — DB 종목 마스터 + 이시카와/토구사 해석
  try {
    if (stockDailyData) {
      const stockDaily = stockDailyData;
      for (const st of (stockDaily.stocks || [])) {
        if (!st.name) continue;
        // 기존 해석이 있으면 themes/theme_paths만 병합 (cafe에 테마 없을 수 있음)
        if (interpretedByName.has(st.name)) {
          const existing = interpretedByName.get(st.name);
          const stThemes = (st.themes || []).map(t => typeof t === 'string' ? { name: t } : t);
          if (stThemes.length > 0 && (!existing.themes || existing.themes.length === 0)) {
            existing.themes = stThemes;
          }
          if ((st.theme_paths || []).length > 0 && (!existing.theme_paths || existing.theme_paths.length === 0)) {
            existing.theme_paths = st.theme_paths;
          }
          continue;
        }
        {
          // stock-*.json 형식 → 기존 렌더러 호환 변환
          // 가비지 뉴스 필터: VI발동, 신고가, 단순 등락률 로봇 기사 제거
          const garbageRe = /[+-]?\d[\d.]*%\s*(VI\s*발동|\d+주\s*신[고저]가|상한가|하한가)|거래량\s*(폭발|급증|돌파)/;
          const newsItems = (st.news || [])
            .filter(n => !(n.newzy_verdict || '').startsWith('반대'))  // 이시카와 판정 컬럼 (legacy: newzy_verdict)
            .filter(n => !garbageRe.test(n.title || ''));
          const topNews = newsItems[0];
          const pp = st.prev_pick;
          const industryLabel = st.industry ? `업종: ${st.industry}` : '';
          const sectorLabel = st.sector ? (() => {
            // 괄호 밖의 첫 콤마에서만 자르기 (괄호 안 콤마는 무시)
            let depth = 0, cutIdx = -1;
            for (let i = 0; i < st.sector.length; i++) {
              if (st.sector[i] === '(') depth++;
              else if (st.sector[i] === ')') depth--;
              else if (st.sector[i] === ',' && depth === 0) { cutIdx = i; break; }
            }
            return cutIdx >= 0 ? st.sector.slice(0, cutIdx).trim() : st.sector.trim();
          })() : '';
          // causal_chain이 있는 뉴스를 우선 탐색 (첫 번째 뉴스에 없을 수 있음)
          const chainNews = newsItems.find(n => n.causal_chain) || null;
          const causalText = chainNews ? chainNews.causal_chain : '';
          const diffParts = [
            causalText,
            !causalText && industryLabel ? industryLabel : '',
            !causalText && sectorLabel ? `주요제품: ${sectorLabel}` : '',
          ].filter(Boolean);
          // 테마: theme_paths 우선, 없으면 themes, 없으면 industry 폴백
          const trimIndustry = (s) => s.replace(/\s*(제조업|업)$/, '').replace(/기타\s*/, '');
          let themes = (st.themes || []).map(t => typeof t === 'string' ? { name: t } : t);
          const themePaths = st.theme_paths || [];
          // industry 폴백 제거 (산업분류 ≠ 테마, 대표 결정)

          interpretedByName.set(st.name, {
            name: st.name,
            themes,
            theme_paths: themePaths,
            causal_chain: causalText ? [causalText] : (st.causal_chain ? [st.causal_chain] : []),
            differentiator: diffParts.join(' · ') || st.causal_chain || '',
            macro_event: topNews?.macro_event || null,
            news_digest: newsItems.map(n => ({ url: n.url, inferred_title: n.title, source: n.source })),
            industry: st.industry,
            sector: st.sector,
            fallback: st.fallback,
            fallback_date: st.fallback_date,
            pick_count: st.pick_count,
            prev_pick: pp,
            disclosures: st.disclosures || [],
            credit_risk: !!st.credit_risk,
            credit_reason: st.credit_reason || null,
            close_price: st.close_price || null,
            open_price: st.open_price || null,
            high_price: st.high_price || null,
            low_price: st.low_price || null,
            change_pct: st.change_pct ?? null,
            trade_amount: st.trade_amount ?? null,
            rank: st.rank ?? null,
            code: st.code || null,
            // REQ-055 P0 — fallback 시점에도 분봉 데이터는 해당 날짜의 정합 자료이므로 null화 금지.
            //   기존 로직은 fallback 데이터의 분봉을 일괄 null 처리해 sparkline이 회색으로만 표시되어
            //   "차트 안 그려짐" 결함을 유발 (4/28 사례). 데이터 안내 chip이 이미 fallback_date를 명시하므로 혼동 없음.
            intraday: st.intraday || null,
            status_badges: st.status_badges || [],
            range_240d: st.range_240d || null,
            // REQ-pm320-ux-cycle #3 P0 fix (FLR-20260429-FLR-002) — 20영업일 일봉 OHLC 패스스루.
            // build_daily.py가 stocks[N].daily_20 부착하지만 본 패스스루 누락 시 renderer.js
            // it.interp.daily_20 undefined → cal-candles20-empty 100% 회색 박스. 모바일은 sparkline
            // display:none이라 매매 직결 정보 100% 손실.
            daily_20: st.daily_20 || null,
            // REQ-048 — 강세 배지 데이터 패스스루 (build_daily.py REQ-039 entry 루트 → interp 합성).
            // 이 필드 누락이 라이브 화면 강세 배지 미노출의 진짜 본질 (대표 발화 02:45 KST).
            bullish_today: !!st.bullish_today,
            bullish_streak: st.bullish_streak ?? 0,
            // P0-23 Fix-79 (2026-05-21 19:38 KST 대표 verbatim
            //   "제주반도체 일봉캔들 영웅문을 보면 강세 날짜가 상당히 많다. 그런데 오늘 하루만 강세로 표시가 된다"):
            //   - P0-21 backend rollout (commit c263408 / merge d0ab219) bullish_dates list[str] emit 라이브 visible PASS
            //     (curl data/interpreted/stock-2026-05-21.json 본문 080220 제주반도체 → bullish_dates: 4건 ['2026-04-24','2026-05-14','2026-05-18','2026-05-21'])
            //   - P0-18 Fix-61 backward derive (streak=N → daily_20 마지막 N건) 본질 폐기 → SoT (backend) 직접 사용
            //   - 영웅문 본문 정합 본질: 강세 발생 모든 영업일 (날짜 array) 본문 분홍 vertical line visible
            //   §11.15 외부 spec 사전 검증 PASS:
            //     - build_daily.py L2509-2609 _prefetch_bullish_info 본문 verbatim grep (bullish_dates list[str] 본질)
            //     - build_daily.py L3188 entry["bullish_dates"] = bullish_dates verbatim grep
            //     - curl 라이브 evidence (제주반도체 4건 visible)
            bullish_dates: Array.isArray(st.bullish_dates) ? st.bullish_dates : null,
          });
        }
      }
      // 매크로 이벤트 보충
      if (Array.isArray(stockDaily.macro_events) && macroEvents.length === 0) {
        macroEvents = stockDaily.macro_events;
      }
      // fallback 날짜 표시를 위해 안내 이벤트 삽입
      if (stockDailyData._fallback_date) {
        macroEvents.unshift({
          keyword: '데이터 안내',
          summary: `최신 분석 데이터 준비 중 — ${stockDailyData._fallback_date} 기준 데이터를 표시합니다.`,
          source_count: 0
        });
      }
    }
  } catch (e) { console.warn('stock-daily merge:', e); }

  // data_source: stock JSON에 포함된 소스 태그 (kiwoom / kiwoom_ranking)
  const dataSource = (stockDailyData && stockDailyData.data_source) || 'kiwoom';
  // REQ-033 — 마지막 업데이트 시각 (build_daily.py generated_at). SPEC-001 §I.4.
  const generatedAt = (stockDailyData && stockDailyData.generated_at) || '';
  // Q-CYCLE20-P2 (2026-05-20) — kiwoom raw 마지막 폴링 시각 (SPEC-001 §I.4 확장).
  //   장중 stale 데이터 가시화. kiwoom 폴백 path(stocks 합성 객체)는 last_snapshot_at 없음 →
  //   자연 미표시 (FLR-AGT-002 거짓 충실성 차단).
  const lastSnapshotAt = (kiwoom && typeof kiwoom.last_snapshot_at === 'string') ? kiwoom.last_snapshot_at : '';
  const result = {
    kiwoom,
    cafePosts: [],
    narratives: [],
    interpretedByName,
    macroEvents,
    dataSource,
    generatedAt,
    lastSnapshotAt
  };
  calDayCache[date] = result;
  _persistCache();

  // 전일 전파는 비동기 (초기 렌더 차단 안 함)
  setTimeout(() => _propagatePrevDay(date, result), 50);

  return result;
}

// 전일 해석 전파 — 별도 비동기 함수 (렌더 이후 백그라운드)
async function _propagatePrevDay(date, result) {
  try {
    const interpretedByName = result.interpretedByName;
    const prevPickDates = new Set();
    for (const [name, curr] of interpretedByName) {
      if (curr.prev_pick && curr.prev_pick.date) {
        const chain = curr.causal_chain || [];
        if (chain.length === 0) prevPickDates.add(curr.prev_pick.date);
      }
    }
    for (const prevDate of prevPickDates) {
      // 전일 해석 전파: 캐시 우선, 없으면 stock JSON만 직접 fetch (재귀 방지)
      let prevData = calDayCache[prevDate];
      if (!prevData) {
        const prevHash = prevDate.replace(/-/g, '');
        const prevStock = await fetch(`data/interpreted/${calCategory}-${prevDate}.json?v=${prevHash}`).then(r => r.ok ? r.json() : null).catch(() => null);
        if (prevStock) {
          const prevMap = new Map();
          for (const st of (prevStock.stocks || [])) {
            if (!st.name) continue;
            const chainNews = (st.news || []).find(n => n.causal_chain) || null;
            prevMap.set(st.name, {
              causal_chain: chainNews ? [chainNews.causal_chain] : [],
              differentiator: chainNews ? chainNews.causal_chain : '',
              macro_event: (st.news || [])[0]?.macro_event || null,
              news_digest: (st.news || []).map(n => ({ url: n.url, inferred_title: n.title, source: n.source })),
            });
          }
          prevData = { interpretedByName: prevMap };
        }
      }
      if (!prevData || !prevData.interpretedByName) continue;
      for (const [name, prevInterp] of prevData.interpretedByName) {
        if (!interpretedByName.has(name)) continue;
        const curr = interpretedByName.get(name);
        if ((curr.causal_chain || []).length > 0) continue;
        if ((prevInterp.causal_chain || []).length > 0) {
          // curr를 base로 두고, prev에서 분석성 필드만 보충 (당일 가격/공시/분봉/신용 등 보존)
          const merged = Object.assign({}, curr, {
            causal_chain: prevInterp.causal_chain,
            differentiator: prevInterp.differentiator || curr.differentiator,
            macro_event: prevInterp.macro_event || curr.macro_event,
            news_digest: prevInterp.news_digest || curr.news_digest,
          });
          interpretedByName.set(name, merged);
        }
      }
    }
    // 전파 완료 후 캐시 업데이트
    _persistCache();
  } catch (e) { console.warn('prev-day propagation:', e); }
}
