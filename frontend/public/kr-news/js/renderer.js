/* ───── renderer.js — 카드/차트/테마 렌더링 + 초기화 ───── */

// REQ-033 — 마지막 업데이트 시각 포맷 (SPEC-001 §I.4).
// build_daily.py의 generated_at은 naive ISO ("2026-04-27T22:59:43.768243") — timezone 미명시.
// new Date() 파싱 시 브라우저 timezone 의존성 회피하기 위해 substring 직접 추출 (KST 가정 명시).
// 형식 불일치 시 빈 문자열 반환 (FLR-AGT-002 정합 — 거짓 표시 차단).
function _formatGeneratedAt(generatedAt) {
  if (!generatedAt || typeof generatedAt !== 'string') return '';
  const m = generatedAt.match(/^\d{4}-\d{2}-\d{2}T(\d{2}):(\d{2})/);
  if (!m) return '';
  return `${m[1]}:${m[2]} KST`;
}

// 신선도 라벨 (2026-05-27 대표 직접 발화) — 차단(blackout) 없이 stale 여부만 산출.
// 대표 verbatim: "폴링 오류 화면(장중 데이터 갱신 중)이 존재하는 것 자체가 잘못."
//   기존 `_computeMarketHardGuard`(종목 카드/차트 차단)를 제거하고, 항상 마지막 데이터를 렌더하되
//   헤더에 정직한 신선도 라벨(점 • + "HH:MM 기준" + is-stale)만 표시한다 (FLR-20260527-TEC-001 정합).
// stale 조건: KST 장중 09:00~15:30 + 오늘 view + (now - last_snapshot_at) > 30분.
//   그 외(장 시작 전/장 마감 후/휴장/과거 viewDate/30분 이내) = stale:false.
// 반환: { stale: boolean }  (차단 정보 없음 — 단순 신선도 플래그)
function _computeFreshnessLabel(generatedAt, lastSnapshotAt, viewDate, nowMs) {
  // KST = UTC+9. nowMs(UTC) 에 9시간 가산 후 UTC 메서드로 읽으면 브라우저 timezone과 무관하게 KST 시각 확보.
  const kstMs = nowMs + 9 * 60 * 60 * 1000;
  const kstNow = new Date(kstMs);
  const yyyy = kstNow.getUTCFullYear();
  const mm = String(kstNow.getUTCMonth() + 1).padStart(2, '0');
  const dd = String(kstNow.getUTCDate()).padStart(2, '0');
  const todayKst = `${yyyy}-${mm}-${dd}`;
  const hourKst = kstNow.getUTCHours();
  const minKst = kstNow.getUTCMinutes();
  const totalMin = hourKst * 60 + minKst;
  const isToday = (viewDate === todayKst);
  const isMarketOpen = (totalMin >= 9 * 60 && totalMin < 15 * 60 + 30);
  // 장중 + 오늘 view 일 때만 신선도 판정 (그 외는 stale 개념 무의미 → false)
  if (!isToday || !isMarketOpen) {
    return { stale: false };
  }
  // (now - last_snapshot_at) > 30분 → stale
  if (lastSnapshotAt && typeof lastSnapshotAt === 'string') {
    const parsed = Date.parse(lastSnapshotAt);
    if (!isNaN(parsed)) {
      const minutesAgo = Math.floor((nowMs - parsed) / 60000);
      if (minutesAgo > 30) return { stale: true };
    }
  }
  return { stale: false };
}

// buildSparkline → js/lib/sparkline.js (REQ-001 §3 Phase 1 분리)
// buildCandles20 → js/lib/mini-candle.js (REQ-001 §3 Phase 1 분리)

function deriveDate(post) {
  if (post.post_date) return post.post_date;
  if (post.fetched_at) return post.fetched_at.slice(0, 10);
  return '날짜 미상';
}

function renderNewsCard(card) {
  const j = card.judgment || '중립';
  // 강도 — % 숫자 대신 카테고리. 구버전 호환: confidence가 있으면 임계값으로 변환
  let strength = card.strength;
  if (!strength && card.confidence != null) {
    if (card.confidence >= 0.75) strength = '강';
    else if (card.confidence >= 0.5) strength = '중';
    else strength = '약';
  }
  const strengthHtml = strength ? `<span class="judgment-strength">·${strength}</span>` : '';
  return `
    <div class="news-card">
      <div class="news-judgment ${j}">${j}${strengthHtml}</div>
      <div class="news-content">
        <div class="news-summary">${escapeHtml(card.summary || '(요약 없음)')}</div>
        ${card.reasoning ? `<div class="news-reasoning">${escapeHtml(card.reasoning)}</div>` : ''}
      </div>
    </div>
  `;
}

// DSN-001 §16.1.4 (v7.2): rules_version 배너 — localStorage에 최종 확인 버전 저장, 불일치 시 1회 안내.
// data.rules_version이 없으면 배너 자체 미생성 (graceful degradation).
function _buildRulesVersionBanner(rulesVersion) {
  if (!rulesVersion || typeof rulesVersion !== 'string') return '';
  const LS_KEY = 'lastSeenRulesVersion';
  let lastSeen = '';
  try { lastSeen = localStorage.getItem(LS_KEY) || ''; } catch (e) { return ''; }
  if (lastSeen === rulesVersion) return ''; // 최신 확인 완료
  // 배너 1회 표시. 사용자 X 클릭 시 해당 버전을 최신으로 저장.
  const safeVer = String(rulesVersion).replace(/[^0-9a-zA-Z]/g, '').slice(0, 16);
  return `<div class="cal-rules-version-banner" role="status" aria-live="polite" data-version="${safeVer}">
    <span class="cal-rules-version-icon" aria-hidden="true">ℹ️</span>
    <span class="cal-rules-version-msg">규정 데이터가 갱신되었습니다. 최신 기준으로 보시려면 새로고침을 권장합니다.</span>
    <button type="button" class="cal-rules-version-close" aria-label="배너 닫기" data-rules-ver="${safeVer}">&times;</button>
  </div>`;
}
// 배너 X 클릭 핸들러 — event delegation (document-level)
if (typeof document !== 'undefined' && !window.__rulesVerBannerBound) {
  document.addEventListener('click', (e) => {
    const btn = e.target && e.target.closest && e.target.closest('.cal-rules-version-close');
    if (!btn) return;
    const v = btn.getAttribute('data-rules-ver') || '';
    try { localStorage.setItem('lastSeenRulesVersion', v); } catch (err) {}
    const banner = btn.closest('.cal-rules-version-banner');
    if (banner) banner.remove();
  });
  window.__rulesVerBannerBound = true;
}

/* ───── DSN-20260425-DSN-004 v9.1 §J.1 — KOREA_HOLIDAYS 글로벌 주입 ─────
   utils.js getNextTradingDay()의 안전망 데이터 소스. build_daily.py 산출 next_trading_day_for_predicted 신뢰가 원칙.
   estimated 등급 시 console.warn (FLR-20260423-FLR-002 verified 절차).
*/
if (typeof window !== 'undefined' && !window.__koreaHolidaysLoading && !window.KOREA_HOLIDAYS) {
  window.__koreaHolidaysLoading = true;
  fetch('data/holidays.json')
    .then(r => r.ok ? r.json() : null)
    .then(j => { if (j) window.KOREA_HOLIDAYS = j; })
    .catch(() => {})
    .finally(() => { window.__koreaHolidaysLoading = false; });
}

// design-news-time-state-v1 — PRE_MARKET 빈 상태 (Option A).
// 거래일 09:00 미만 시 카드 list 미렌더 + 시계 아이콘 + 카운트다운 + 보조 토글 (전일 데이터 보기).
// stale 라벨 자연 봉쇄 (catch 2): PRE_MARKET 진입 시 데이터 자체가 안 보이므로 라벨 노출 0.
// 사용자 명시 토글 시에만 카드 list 렌더 + data-stale="true" attribute 부착.
function _formatCountdownToOpen(now) {
  const _now = now || new Date();
  const target = new Date(_now.getFullYear(), _now.getMonth(), _now.getDate(), 9, 0, 0, 0);
  let diff = Math.max(0, target.getTime() - _now.getTime());
  const totalSec = Math.floor(diff / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

let _preMarketTimer = null;
let _preMarketVisHandler = null;

function _stopPreMarketTimer() {
  if (_preMarketTimer) { clearInterval(_preMarketTimer); _preMarketTimer = null; }
  if (_preMarketVisHandler) {
    document.removeEventListener('visibilitychange', _preMarketVisHandler);
    _preMarketVisHandler = null;
  }
}

// PRE_MARKET (장 시작 전, 09:00 이전 + 오늘 view) 빈 상태 — 당일 표출 데이터가 아직 없는 정상 상태.
// 2026-05-27 대표 발화로 장중 stale 차단(staleInfo) 경로 제거 → PRE_MARKET 단일 모드만 남김.
function renderPreMarketEmpty(container, date, prevDate, prevData) {
  _stopPreMarketTimer();
  const prevLabel = prevDate ? formatKoDate(prevDate) : '';
  const inner = container || document.getElementById('cal-content');
  if (!inner) return;
  const titleText = '장 시작 전';
  const subText = '09:00에 신규 데이터가 표출됩니다';
  const metaText = '장 시작 전';
  const liveText = _formatCountdownToOpen();
  inner.innerHTML = `
    <div class="cal-content-head" role="button" tabindex="0" aria-label="달력으로 이동" data-scroll-to-cal="1">
      <div class="cal-content-date">${formatKoDate(date)}</div>
      <div class="cal-content-meta">${metaText}</div>
    </div>
    <div class="cal-pre-market-empty" role="status" aria-live="polite">
      <svg class="cal-pre-market-icon" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="9"></circle>
        <polyline points="12 7 12 12 15 14"></polyline>
      </svg>
      <div class="cal-pre-market-title">${escapeHtml(titleText)}</div>
      <div class="cal-pre-market-sub">${escapeHtml(subText)}</div>
      <div class="cal-pre-market-countdown" data-cd="1">${escapeHtml(liveText)}</div>
      ${prevDate ? `<button type="button" class="cal-pre-market-toggle" data-pre-toggle="1" aria-expanded="false">전일(${prevLabel}) 데이터 보기 ▾</button>` : ''}
      <div class="cal-pre-market-prev" data-pre-prev hidden></div>
    </div>
  `;
  // 카운트다운 1초 단위 + Page Visibility API
  {
    const cdEl = inner.querySelector('[data-cd]');
    const tick = () => {
      if (!cdEl || !document.body.contains(cdEl)) { _stopPreMarketTimer(); return; }
      cdEl.textContent = _formatCountdownToOpen();
      // 09:00 도달 시 자동 OPEN 전환 (한 번만)
      const nowH = new Date();
      if (nowH.getHours() >= 9 && getMarketState() !== 'PRE_MARKET') {
        _stopPreMarketTimer();
        // _refreshDataAsync 동등 — calendar.js의 onCalCellClick으로 재렌더
        try { onCalCellClick(date, false); } catch (_) {}
      }
    };
    _preMarketTimer = setInterval(tick, 1000);
    _preMarketVisHandler = () => {
      if (document.hidden) {
        if (_preMarketTimer) { clearInterval(_preMarketTimer); _preMarketTimer = null; }
      } else if (!_preMarketTimer) {
        tick();
        _preMarketTimer = setInterval(tick, 1000);
      }
    };
    document.addEventListener('visibilitychange', _preMarketVisHandler);
  }

  // 보조 토글 — 전일 데이터 표출 (data-stale="true")
  const toggleBtn = inner.querySelector('[data-pre-toggle]');
  const prevBox = inner.querySelector('[data-pre-prev]');
  if (toggleBtn && prevBox && prevDate) {
    toggleBtn.addEventListener('click', async () => {
      const expanded = toggleBtn.getAttribute('aria-expanded') === 'true';
      if (expanded) {
        toggleBtn.setAttribute('aria-expanded', 'false');
        toggleBtn.textContent = `전일(${prevLabel}) 데이터 보기 ▾`;
        prevBox.hidden = true;
        prevBox.innerHTML = '';
      } else {
        toggleBtn.setAttribute('aria-expanded', 'true');
        toggleBtn.textContent = `전일(${prevLabel}) 데이터 접기 ▴`;
        prevBox.hidden = false;
        prevBox.setAttribute('data-stale', 'true');
        const data = prevData || (typeof loadCalDayData === 'function' ? await loadCalDayData(prevDate) : null);
        if (data) {
          // 임시 컨테이너에 prevDate로 렌더 후 prevBox로 이전 (재진입 방지)
          const tmp = document.createElement('div');
          tmp.id = 'cal-content-tmp-prev';
          // renderCalExpandContent는 cal-content를 hardcoded read하므로 일시 swap
          const origInner = document.getElementById('cal-content');
          const origId = origInner ? origInner.id : null;
          if (origInner) origInner.id = '_cal-content-saved';
          tmp.id = 'cal-content';
          document.body.appendChild(tmp);
          try {
            // PRE_MARKET 재진입 회피 — 전일은 항상 hasAny path 또는 closed/empty path
            renderCalExpandContent(prevDate, data);
            prevBox.innerHTML = tmp.innerHTML;
          } catch (e) { prevBox.textContent = '전일 데이터 로드 실패'; }
          tmp.remove();
          if (origInner && origId) origInner.id = origId;
        } else {
          prevBox.textContent = '전일 데이터 없음';
        }
      }
    });
  }
}

function renderCalExpandContent(date, data) {
  // design-news-time-state-v1 (catch 1) — 시점 분기 PRE_MARKET 빈 상태.
  // 본 함수 진입점에서 getMarketState로 분기. 거래일 09:00 미만 시 카드 list 미렌더.
  // 09:00 이후 OPEN/POST_MARKET 또는 비거래일 HOLIDAY는 기존 로직 유지.
  // 대표 발화 (2026-05-27): "폴링 오류 화면(장중 데이터 갱신 중)이 존재하는 것 자체가 잘못."
  //   장중 stale 데이터 차단(blackout) 제거 — stale/지연 무관 항상 마지막 데이터를 렌더하고,
  //   신선도는 헤더 freshness 라벨(점 + "HH:MM 기준")로만 정직하게 표시한다 (FLR-20260527-TEC-001 정합).
  //   PRE_MARKET (09:00 이전 + 오늘 view) 만 빈 상태 유지 — 표출할 당일 데이터가 아직 없는 정상 상태.
  try {
    const state = (typeof getMarketState === 'function') ? getMarketState(date) : null;
    const _now = new Date();
    const _todayIso = `${_now.getFullYear()}-${String(_now.getMonth()+1).padStart(2,'0')}-${String(_now.getDate()).padStart(2,'0')}`;
    if (state === 'PRE_MARKET' && date === _todayIso) {
      // 전일 거래일 = date 하루씩 뒤로 가며 첫 비휴장일
      let prev = null;
      const dt = new Date(date + 'T00:00:00');
      for (let i = 0; i < 10; i++) {
        dt.setDate(dt.getDate() - 1);
        const iso = `${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,'0')}-${String(dt.getDate()).padStart(2,'0')}`;
        if (typeof isMarketClosed === 'function' && !isMarketClosed(iso)) { prev = iso; break; }
      }
      const inner = document.getElementById('cal-content');
      renderPreMarketEmpty(inner, date, prev, null);
      return;
    } else {
      // 다른 시점 진입 시 PRE_MARKET 타이머 정리
      _stopPreMarketTimer();
    }
  } catch (_) { /* getMarketState 미정의 시 graceful */ }

  const inner = document.getElementById('cal-content');
  // Q-20260514-058 Fix F-A Plan B (대표 결정 04:08 KST) — chain 순서 역전.
  // 종래: daily_top (하루 누적 max_trade_amount, snapshot stale data 포함) → latest_stocks (최신 snapshot, SSOT)
  // 본질: kiwoom.daily_top는 first_seen=00:22 1회 잡힌 stale 종목까지 포함 (예: 010170 대한광통신 2026-05-13 #1 +4.11%/2.1조 = 키움 HTS 미정합).
  // 키움 HTS 조건검색 SSOT = latest_stocks (snapshot_count 최종 21:33 기준 25종). 키움 HTS와 정합.
  // daily_top는 폴백 유지 (latest_stocks 누락 시).
  const _baseStocks = data.kiwoom ? (data.kiwoom.latest_stocks || data.kiwoom.daily_top || []) : [];
  // REQ-082 Phase 2 §본질 fix (FLR-20260429-FLR-001 §본질) — REQ-080 §1 union 정책을 frontend에서도 적용.
  // build_daily.py union(line 2351-2410)이 interpreted JSON `stocks`에 상한가 종목을 추가하지만,
  // 종래 renderer는 raw kiwoom.daily_top만 사용 → union 결과 무시 → 4/29 6건 카드 미렌더 (qa-2 FAIL 6건).
  // design-lead 옵션 C: 정렬 SSOT(daily_top) 보존 + 상한가 union 종목만 list 끝에 append.
  // data.stocks는 data-loader가 interpretedByName Map만 노출하므로 Map iterate로 적응.
  const _interpByName = data.interpretedByName || new Map();
  const _baseTickers = new Set(_baseStocks.map(s => s.ticker || s.code).filter(Boolean));
  const _limitUpAdded = [];
  for (const [_name, _interp] of _interpByName) {
    const _ticker = _interp.code || '';
    if (!_ticker || _baseTickers.has(_ticker)) continue;
    const _hasLimitUp = (_interp.status_badges || []).some(b => b.label === '상한가');
    if (!_hasLimitUp) continue;
    // kiwoom dict 호환 형태로 합성 (build_daily.py:2378 _added_lu와 동일 시그니처)
    _limitUpAdded.push({
      ticker: _ticker,
      name: _name,
      last_price: _interp.close_price ?? null,
      max_trade_amount: _interp.trade_amount ?? null,
      trade_amount: _interp.trade_amount ?? null,
      max_change_pct: _interp.change_pct ?? null,
      change_pct: _interp.change_pct ?? null,
      _source_union: 'limit_up',
    });
  }
  const kiwoomStocks = _limitUpAdded.length > 0 ? [..._baseStocks, ..._limitUpAdded] : _baseStocks;
  const hasInterpretedStocks = data.interpretedByName && data.interpretedByName.size > 0;
  const hasAny = kiwoomStocks.length > 0 || hasInterpretedStocks;

  if (!hasAny) {
    const closed = isMarketClosed(date);
    let emptyMsg;
    if (closed) {
      const nextDate = getNextTradingDate(date);
      const nextLabel = nextDate ? formatKoDate(nextDate) : '';
      emptyMsg = `
        <div style="text-align:center;padding:32px 0;">
          <div style="font-size:15px;font-weight:700;color:var(--tx2);margin-bottom:6px;">오늘은 장이 쉽니다</div>
          <div style="font-size:12px;color:var(--dm);">${nextLabel ? '다음 거래일 ' + escapeHtml(nextLabel) : ''}</div>
        </div>`;
    } else {
      // DSN-frontend §3.6.2.2 (2026-05-28 대표 직접 발화) — 오늘 view + 09:00+ 데이터 없음 시간대별 정직 고지.
      // 대표 verbatim: "9시부터 종목검색 결과가 있을 때까지 어제걸 보여주는게 과연 맞는걸까? 무슨 이점이 있지?"
      //                "없으면 없다고 알려주는게 더 신뢰도나 활용면에서 좋자않나?"
      // 기존: yesterday data fallback (data-loader.js) → "수집된 데이터가 없습니다" 1줄.
      // 신규: data-loader.js fallback 차단 + 시간대별 sub-message로 사용자 즉시 인지.
      //   - 09:00~11:00 KST: 장 시작 직후 수집 진행 중 (정상 상황)
      //   - 11:00 KST 이후: 파이프라인 이상 또는 새로고침 권장
      //   - 그 외 (과거 날짜 등): 기존 메시지 유지
      const now = new Date();
      const todayIso = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
      const isToday = (date === todayIso);
      const hour = now.getHours();
      let titleText = '수집된 데이터가 없습니다';
      let subText = '';
      if (isToday && hour >= 9 && hour < 11) {
        titleText = '장 시작 직후 데이터 수집 중';
        subText = '잠시 후 자동 갱신됩니다';
      } else if (isToday && hour >= 11 && hour < 16) {
        titleText = '데이터 수집이 지연되고 있습니다';
        subText = '새로고침하거나 잠시 후 다시 확인해 주세요';
      }
      emptyMsg = `<div class="cal-empty">
            <div class="cal-empty-circle"></div>
            <div>${escapeHtml(titleText)}</div>
            ${subText ? `<div class="cal-empty-sub">${escapeHtml(subText)}</div>` : ''}
          </div>`;
    }
    // 휴장일이라도 매크로 이벤트가 있으면 표시
    const closedMacro = (data.macroEvents || []).filter(m => m.summary && m.summary.length >= 10).slice(0, 5);
    const closedMacroHtml = closedMacro.length > 0
      ? `<div class="cal-macro-strip">${closedMacro.map(m => `<span class="cal-macro-chip" title="${escapeHtml(sanitize(m.title || ''))}">${escapeHtml(sanitize(m.summary))}</span>`).join('')}</div>`
      : '';
    const _emptyVerBanner = _buildRulesVersionBanner(data && data.rules_version);
    inner.innerHTML = `
      ${_emptyVerBanner}
      <div class="cal-content-head" role="button" tabindex="0" aria-label="달력으로 이동" data-scroll-to-cal="1">
        <div class="cal-content-date">${formatKoDate(date)}</div>
        <div class="cal-content-meta">${closed ? '휴장' : '데이터 없음'}</div>
      </div>
      ${closedMacroHtml}
      ${emptyMsg}
    `;
    return;
  }

  // 키움 name → {ticker, change_pct} 맵 (특징주 join용)
  const kiwoomByName = new Map();
  for (const s of kiwoomStocks) {
    if (s && s.name) kiwoomByName.set(s.name, s);
  }

  // interpretedByName을 특징주/종목 구성에서 사용하기 위해 먼저 참조
  const interpByName = data.interpretedByName || new Map();

  // 특징주 결정: 거래대금 TOP 또는 stock-*.json 기반
  let featureSource = 'primary';
  let featureItems = []; // { name, pct, themes, ticker, reason }
  if (kiwoomStocks.length > 0) {
    featureSource = 'fallback';
    featureItems = kiwoomStocks.slice(0, 6).map(s => {
      const interp = interpByName.get(s.name);
      // cycle20 P1 — limit-up/down status_badges 우선 (featureItems primary)
      const _featLimit = (interp && Array.isArray(interp.status_badges))
        ? interp.status_badges.find(b => Array.isArray(b.effect_badges)
            && b.effect_badges.some(e => e.effect === 'limit-up' || e.effect === 'limit-down')
            && b.flu_rt != null
            && Math.abs(b.flu_rt) <= 35) // anomaly guard (±35% 초과 = ka10017 source 결함, P3 audit)
        : null;
      const pct = _featLimit ? _featLimit.flu_rt : (interp?.change_pct ?? s.change_pct ?? s.max_change_pct ?? null);
      const themes = (interp?.themes || themesData?.stocks?.[s.ticker]?.themes || []).slice(0, 3);
      return { name: s.name, pct, themes, links: [], ticker: s.ticker, reason: '', interp };
    });
  } else if (interpByName.size > 0) {
    // kiwoom JSON 없음, 카페 없음 → stock-*.json 기반 특징주
    featureSource = 'fallback';
    featureItems = [];
    for (const [name, interp] of interpByName) {
      if (featureItems.length >= 6) break;
      const themes = (interp.themes || []).slice(0, 3).map(t => typeof t === 'string' ? { name: t } : t);
      // cycle20 P1 — limit-up/down status_badges 우선 (featureItems no-kiwoom)
      const _featLimit2 = Array.isArray(interp.status_badges)
        ? interp.status_badges.find(b => Array.isArray(b.effect_badges)
            && b.effect_badges.some(e => e.effect === 'limit-up' || e.effect === 'limit-down')
            && b.flu_rt != null
            && Math.abs(b.flu_rt) <= 35) // anomaly guard (±35% 초과 = ka10017 source 결함, P3 audit)
        : null;
      const _featPct2 = _featLimit2 ? _featLimit2.flu_rt : (interp.change_pct ?? null);
      featureItems.push({ name, pct: _featPct2, themes, links: [], code: interp.code || '', ticker: interp.code || '', reason: '', interp });
    }
  }

  // cycle20 P1 (2026-05-20) — 상한가/하한가 카드 등락률 status_badges 우선 사용 (frontend 빠른 fix)
  // 본질: build_daily.py SoT 결함으로 limit-up 종목의 interp.change_pct가 부정합 (예: 광전자 -1.46% vs 실제 +29.96%).
  //   intraday.base 잘못된 기준 → change_pct 잘못 계산. backend SoT 통일은 별건 P2 후행.
  // frontend가 정합 책임: status_badges[].effect_badges[].effect === 'limit-up'/'limit-down' 있고
  //   status_badges[].flu_rt + cur_prc 정의 시 → 카드 pct/price를 그것으로 override.
  // mismatch 4/9 종목 catch (광전자/마키나락스/성문전자/케이엠제약, 2026-05-20 13:43 KST lead 진단).
  // DSN-arch-frontend §3.6.4 spec 신설.
  const _extractLimitEffect = (interp) => {
    if (!interp || !Array.isArray(interp.status_badges)) return null;
    for (const b of interp.status_badges) {
      if (!Array.isArray(b.effect_badges)) continue;
      const isLimit = b.effect_badges.some(e => e.effect === 'limit-up' || e.effect === 'limit-down');
      if (isLimit && b.flu_rt != null && b.cur_prc != null) {
        // range guard: 한국 증시 상한가/하한가 ±30% 제도적 fact. ±35% 초과 = ka10017 source anomaly (예: 마키나락스 +300%).
        // anomaly 시 status_badges override 무효 → 기존 change_pct fallback 사용. P3 backend audit 별건 trigger.
        if (Math.abs(b.flu_rt) > 35) {
          // eslint-disable-next-line no-console
          console.warn(`[limit-up-mismatch] anomaly flu_rt=${b.flu_rt} for ${interp.code}/${interp.name} — skip override (P3 backend audit)`);
          return null;
        }
        return { flu_rt: b.flu_rt, cur_prc: b.cur_prc };
      }
    }
    return null;
  };
  // cycle20 P1 (2026-05-20) — 카드 좌측 빨간 테두리(.cal-feature-card--lu) 결정용 헬퍼.
  // 본질 fix: 기존 _source_union==='limit_up' 단일 조건 → kiwoom.latest_stocks 內 상한가 종목(녹십자엠에스 등)은 union 미경유 → 테두리 누락.
  // 대표 catch (2026-05-20 15:08 KST): "녹십엠에스는 상한가인데도 카드 좌측 빨간 테두리 없음 (광전자는 있음)".
  // 일관성: status_badges[].effect_badges[].effect === 'limit-up' 검출 시 source 무관 테두리 부여.
  // anomaly guard 동일 적용 (±35% 초과 = ka10017 source 결함이지만 marker는 유지 — 시각 일관성 우선).
  const _hasLimitUpEffect = (interp) => {
    if (!interp || !Array.isArray(interp.status_badges)) return false;
    for (const b of interp.status_badges) {
      if (!Array.isArray(b.effect_badges)) continue;
      if (b.effect_badges.some(e => e.effect === 'limit-up')) return true;
    }
    return false;
  };

  // 오늘의 종목: 거래대금 TOP을 base로, 카페·해석 정보 join
  let todayStocks;
  if (kiwoomStocks.length > 0) {
    todayStocks = kiwoomStocks.map((s, i) => {
      const interp = interpByName.get(s.name);
      // 등락률: cycle20 P1 — limit-up/down status_badges 우선 (build_daily SoT 결함 회피)
      // 그 외 stock JSON 종가 기준 우선 (키움 max_change_pct는 장중 최대라 부정확)
      const _limitEff = _extractLimitEffect(interp);
      const pct = _limitEff ? _limitEff.flu_rt : (interp?.change_pct ?? s.change_pct ?? s.max_change_pct ?? null);
      let themes;
      if (interp && Array.isArray(interp.themes) && interp.themes.length > 0) {
        themes = interp.themes.slice(0, 3).map(t => typeof t === 'string' ? { name: t } : t);
      } else {
        themes = (themesData?.stocks?.[s.ticker]?.themes || []).slice(0, 2);
      }
      // price도 limit-up 시 cur_prc 우선 (candle direction 정합)
      const _priceBase = s.last_price ?? s.price ?? interp?.close_price;
      const price = _limitEff ? _limitEff.cur_prc : _priceBase;
      return { rank: i + 1, name: s.name, ticker: s.ticker, code: s.ticker, pct, amount: s.max_trade_amount ?? s.trade_amount, themes, interp, links: [], open: s.open ?? interp?.open_price, high: s.high ?? interp?.high_price, low: s.low ?? interp?.low_price, price, _source_union: s._source_union };
    });
  } else if (interpByName.size > 0) {
    // kiwoom JSON 없음 → stock-*.json (interpretedByName)에서 종목 구성
    todayStocks = [];
    let idx = 0;
    for (const [name, interp] of interpByName) {
      idx++;
      let themes = [];
      if (Array.isArray(interp.themes) && interp.themes.length > 0) {
        themes = interp.themes.slice(0, 3).map(t => typeof t === 'string' ? { name: t } : t);
      }
      // cycle20 P1 — limit-up/down status_badges 우선 (no-kiwoom 분기)
      const _limitEff = _extractLimitEffect(interp);
      const _pct = _limitEff ? _limitEff.flu_rt : (interp.change_pct ?? null);
      const _price = _limitEff ? _limitEff.cur_prc : (interp.close_price ?? null);
      todayStocks.push({
        rank: interp.rank || idx,
        name,
        code: interp.code || interp.ticker || '',
        ticker: interp.code || interp.ticker || '',
        pct: _pct,
        amount: interp.trade_amount ?? null,
        price: _price,
        open: interp.open_price ?? null,
        high: interp.high_price ?? null,
        low: interp.low_price ?? null,
        themes,
        interp,
        links
      });
    }
    // 거래대금 순 정렬
    todayStocks.sort((a, b) => (b.amount || 0) - (a.amount || 0));
    todayStocks.forEach((s, i) => { s.rank = i + 1; });
  } else {
    todayStocks = [];
  }

  // Phase 2c-1 (2026-05-23) — single-card mode 동적 분기
  // 본질: URL param `?stock={code}` 또는 `?stock={code}&date={date}` 진입 시
  //   todayStocks를 본 종목 1개만 filter → 단독 카드 render.
  // 외부 호출 사이트 (news.html fragment fetch 또는 외부 임베딩) 본 본 본 sparkline/chart-tv/bullish/status_badges
  //   본 본 전체 render 본 본 본 시각 일관성 본 본.
  // backward compat: ?stock= 본 본 본 본 본 본 본 기존 다중 카드 path (kiwoom.latest_stocks 전체).
  // Phase 2c-2 후행: news.html 또는 외부 페이지에서 fetch + innerHTML 임베딩 본 본 spec hint.
  let _isSingleCardMode = false;
  let _singleCardCode = null;
  try {
    if (typeof window !== 'undefined' && window.location) {
      const _urlParams = new URLSearchParams(window.location.search);
      const _qStock = _urlParams.get('stock');
      if (_qStock && /^\d{4,6}$/.test(_qStock)) {
        _singleCardCode = _qStock;
        _isSingleCardMode = true;
      }
    }
  } catch (_) { /* graceful */ }
  if (_isSingleCardMode && _singleCardCode) {
    const _filtered = todayStocks.filter(s => (s.ticker || s.code) === _singleCardCode);
    todayStocks = _filtered;
    // cycle23 (2026-05-23) — original rank 보존. 본질: 다중 카드 mode 본 거래대금 정렬+rank 부여 (line 555-556)
    //   완료 후 filter만 수행 → 본 종목 원래 순위 (예: #5, #12 등) 그대로 유지.
    //   이전: filter 직후 forEach((s, i) => { s.rank = i + 1; }) → 본 종목 rank 무조건 #1로 덮어쓰기 = 사고.
    //   대표 verbatim "단독 카드를 공유할 때 #1이라고 순위가 바뀌는데 원래 숫자를 그대로 보여줄 수 있어?" (2026-05-23 07:24 KST).
    // cycle23 Q-CYCLE23-002 Phase 2c-1-extend — single-card mode 페이지 frame 완전 격리.
    // 본질: body class `single-card-mode` 부여 → CSS `body.single-card-mode header/nav/footer/page-header/cal-side/theme-tree/limit-up-trend/theme-trend/theme-map` hide.
    // 대표 verbatim "정말로 종목카드만 하나 존재" (2026-05-23 02:15 KST) 정합.
    // backward compat: ?stock param 없으면 class 미부여 → 다중 카드 mode 본 페이지 frame 정상 표시.
    try {
      if (typeof document !== 'undefined' && document.body) {
        document.body.classList.add('single-card-mode');
      }
    } catch (_) { /* graceful */ }
  }

  // 메타
  const newsTotal = todayStocks.reduce((acc, i) => acc + (i.links ? i.links.length : 0), 0);
  const interpCount = todayStocks.filter(i => i.interp).length;
  // pick_count >= 2: 카드 chip "연속선정+N" 표시와 동일 정의 (DSN §3.6.3 단일 출처, cycle20 P1).
  // 이전 정의 (prev_pick != null) 은 어제 1회 등장 종목까지 포함 → 헤더 N종 vs 카드 chip 노출 종목수 mismatch.
  const streakCount = todayStocks.filter(i => (i.interp?.pick_count || 0) >= 2).length;
  const streakSuffix = streakCount > 0 ? ` · 연속선정 ${streakCount}종` : '';
  const sourceSuffix = '';
  // REQ-033 — 마지막 업데이트 시각 (SPEC-001 §I.4). build_daily.py generated_at 표시.
  // 시간대 정합 (개발팀 비판): naive ISO("YYYY-MM-DDTHH:MM:SS.fff") 직접 substring 추출 — Date 파싱 시 브라우저 timezone 의존성 회피. KST 가정 명시.
  // 대표 발화 (2026-05-27) — 라벨 "HH:MM 업데이트" → "HH:MM 기준" (live 오인 방지).
  //   stale (장중 30분+ 지연 등) 일 때만 앞에 점(•) + is-stale 클래스 → 정직한 신선도 표시. 차단 없음.
  const generatedAt = data.generatedAt || '';
  const lastSnapshotAt = data.lastSnapshotAt || '';
  // 테스트 hook: window._freshnessNow 설정 시 해당 시각으로 평가 (시뮬레이션용)
  const _nowMs = (typeof window !== 'undefined' && typeof window._freshnessNow === 'number') ? window._freshnessNow : Date.now();
  const _fresh = _computeFreshnessLabel(generatedAt, lastSnapshotAt, date, _nowMs);
  const generatedSuffix = generatedAt
    ? ` · ${_fresh.stale ? '<span class="cal-day-meta__dot" aria-hidden="true">•</span>' : ''}<span class="cal-day-meta__updated${_fresh.stale ? ' is-stale' : ''}">${escapeHtml(_formatGeneratedAt(generatedAt))} 기준</span>`
    : '';
  const metaText = todayStocks.length > 0
    ? `오늘의 종목 : ${todayStocks.length}개${streakSuffix}${sourceSuffix}${generatedSuffix}`
    : '—';

  // (1) 매크로 이벤트 (내러티브 폴백에도 사용)
  const macroEvents = (data.macroEvents || [])
    .filter(m => m.summary && m.summary.length >= 10)
    .slice(0, 5);
  const macroHtml = macroEvents.length > 0
    ? `<div class="cal-macro-strip">${macroEvents.map(m => `<span class="cal-macro-chip" title="${escapeHtml(sanitize(m.title || ''))}">${escapeHtml(sanitize(m.summary))}</span>`).join('')}</div>`
    : '';

  // 내러티브: 카페 제거로 빈 값 (하위 호환용 유지)
  const narrPillsHtml = '';

  const renderFactors = (st) => {
    const ff = st.five_factors || {};
    const ev = st.five_factors_evidence || {};
    const labels = { freshness: '신선', durability: '지속', magnitude: '크기', spreadability: '전파', liquidity: '환급' };
    const entries = Object.entries(ff)
      .map(([k, v]) => ({ k, v, label: labels[k] || k, ev: ev[k] || '' }))
      .sort((a, b) => b.v - a.v)
      .slice(0, 3);
    return entries.map(e => {
      const filled = Math.round(e.v * 5);
      const dots = Array.from({ length: 5 }, (_, i) => `<span class="cal-dot ${i < filled ? 'on' : ''}"></span>`).join('');
      return `<span class="cal-factor" title="${escapeHtml(e.ev)}"><span class="label">${e.label}</span><span class="cal-dots">${dots}</span></span>`;
    }).join('');
  };

  const renderTodayCard = (it) => {
    const pct = it.pct;
    const dir = (pct ?? 0) >= 0 ? 'up' : 'down';           // 등락률 텍스트 색상용 (전일 대비)
    const candleDir = (it.open && it.price) ? (it.price >= it.open ? 'up' : 'down') : dir;  // 캔들/sparkline용 (시가 대비)
    const sign = (pct ?? 0) >= 0 ? '+' : '';
    const pctText = pct != null ? `${sign}${pct.toFixed(2)}%` : '';
    const amountText = it.amount ? fmtTradeAmount(it.amount) : '';
    // Q-20260515-CANDLE-SOURCE-UNIFY: 일봉캔들 OHLC를 daily_20[-1]과 동일 source 통일 (sparkline 정합).
    // it.price (라이브 cur_prc) ≠ daily_20[-1].c (dailybars close) mismatch 시 양봉/음봉 색상 mismatch 발생.
    // 대표 catch 23:34: 일봉캔들 vs sparkline 마지막 색상 mismatch (앤로보틱스 음봉 vs 양봉).
    const d20 = it.interp?.daily_20;
    const lastBar = (Array.isArray(d20) && d20.length > 0) ? d20[d20.length - 1] : null;
    const candleHtml = lastBar
      ? miniCandle(lastBar.o, lastBar.h, lastBar.l, lastBar.c, it.pct)
      : miniCandle(it.open, it.high, it.low, it.price, it.pct);
    // 테마칩: 같은 루트 트리는 합쳐서 중복 노드 제거
    // REQ-P1 #7 (2026-04-29): chip별 data-tooltip = 해당 노드가 속한 path 전체 ("부모 > 자식")
    const tp = it.interp?.theme_paths || [];
    const themesHtml = (() => {
      if (tp.length === 0) return it.themes.slice(0, 3).map(t => `<span class="cal-ind-chip">${escapeHtml(t.name)}</span>`).join('');
      // 같은 루트끼리 그룹핑 → 노드 합집합 (순서 유지)
      const groups = {};
      const groupOrder = [];
      tp.forEach(p => {
        const root = p.path[0];
        if (!groups[root]) { groups[root] = []; groupOrder.push(root); }
        groups[root].push(p.path);
      });
      return groupOrder.map((root, gi) => {
        const paths = groups[root];
        // 모든 경로의 노드를 순서 유지하며 합집합 + 노드별 가장 긴 path 기록
        const seen = new Set();
        const merged = [];
        const nodeFullPath = {}; // node → path 전체 (복수면 가장 긴 것)
        paths.forEach(path => {
          path.forEach(node => {
            if (!seen.has(node)) { seen.add(node); merged.push(node); }
            const cur = nodeFullPath[node];
            if (!cur || path.length > cur.length) nodeFullPath[node] = path;
          });
        });
        const chips = merged.map(s => {
          const fullPath = nodeFullPath[s] || [s];
          const tooltipText = fullPath.join(' > ');
          // 단일 노드(부모-자식 관계 없음)면 tooltip 생략
          const tooltipAttr = fullPath.length > 1 ? ` data-tooltip="${escapeHtml(tooltipText)}"` : '';
          return `<span class="cal-ind-chip"${tooltipAttr}>${escapeHtml(s)}</span>`;
        }).join('');
        return (gi > 0 ? '<span class="cal-theme-sep">│</span>' : '') + chips;
      }).join('');
    })();

    // 해석 있으면 full 카드 확장 (아래 if 블록), 없으면 같은 full 구조 + "뉴스 없음" placeholder (else 블록 하단)
    // 대표 지시 2026-04-22: compact 한 줄 분기 제거 — 카드 간 레이아웃 일관성 유지
    if (it.interp) {
      const st = it.interp;
      const causal = (st.causal_chain || []).slice(0, 3);
      const styledArrow = '<span class="arrow">→</span>';
      const causalHtml = causal.length > 0
        ? `<div class="cal-causal">${causal.map((c, i) => `${escapeHtml(sanitize(c)).replace(/→/g, styledArrow)}${i < causal.length - 1 ? styledArrow : ''}`).join('')}</div>`
        : '';
      // 뉴스 제목은 미표시 (대표 지시: 로봇 제목은 무가치. 인과사슬만 표시)
      const headlineHtml = '';
      // differentiator가 causal_chain과 동일하면 중복 제거
      const causalText = (causal[0] || '').trim();
      const diffRaw = (st.differentiator || st.outlook || '').trim();
      let ishikawaLine = (diffRaw && diffRaw !== causalText) ? diffRaw : '';
      // 뉴스 없는 종목: industry/sector로 fallback
      if (!ishikawaLine && !causalText) {
        const parts = [];
        if (st.industry) parts.push(st.industry);
        if (st.sector) parts.push(st.sector);
        ishikawaLine = parts.join(' · ');
      }
      const ishikawaHtml = ishikawaLine ? `<div class="cal-ishikawa-line">${escapeHtml(sanitize(ishikawaLine))}</div>` : '';
      // 공시 (DART) — 뱃지는 namecell, 목록은 카드 최하단
      // 2026-04-22 대표 정정: status_badges에 이미 표시되는 공시(투자경고 등)는 공시 리스트 itemsHtml에서 제외 (중복 방지)
      // REQ-030 §1 — 헤더 "공시" 배지는 모든 KRX 공시 포함 트리거 (SPEC-001 §III.4):
      //   - stock.disclosures.length > 0 OR status_badges.filter(source='disclosure').length > 0
      //   - 사용자가 헤더에서 공시 존재 인지 → 펼침 동기 제공
      // discListHtml(상세 영역)은 기존대로 STATUS_DISC_CATS 제외 (사유 박스에서 KRX 단계 공시 표시).
      const STATUS_DISC_CATS = ['투자주의', '투자경고', '투자위험', '단기과열', '단기과열예고', '관리종목', '매매거래정지', '상장폐지'];
      const allDiscs = st.disclosures || [];
      const discs = allDiscs.filter(d => !STATUS_DISC_CATS.includes(d.category));
      const krxDiscBadges = (st.status_badges || []).filter(b => b.source === 'disclosure');
      const totalDiscCount = allDiscs.length + (allDiscs.length === 0 ? krxDiscBadges.length : 0);
      let discBadgeHtml = '';
      let discListHtml = '';
      if (totalDiscCount > 0) {
        // REQ-039 표기 통일 — "공시+N" (1건도 +1).
        const discBadgeLabel = `공시+${totalDiscCount}`;
        const cbWarnEarly = allDiscs.some(d => d.is_cb) ? '<span class="cal-disc-cb-warn">CB</span>' : '';
        // REQ-030 §1 — 헤더 공시 배지 (SPEC-001 §III.4). 칩 디자인 (📋 아이콘 CSS ::before).
        discBadgeHtml = `<span class="cal-disclosure-badge" aria-label="공시 ${totalDiscCount}건">${escapeHtml(discBadgeLabel)}</span>${cbWarnEarly}`;
      }
      if (discs.length > 0) {
        const sentSum = discs.reduce((s, d) => s + (d.sentiment || 0), 0);
        const health = sentSum > 0 ? 'positive' : sentSum < 0 ? 'negative' : 'neutral';
        const hasCb = discs.some(d => d.is_cb);
        const cbWarn = hasCb ? '<span class="cal-disc-cb-warn">CB</span>' : '';
        const maxShow = 3;
        const shown = discs.slice(0, maxShow);
        const moreCount = discs.length - maxShow;
        const _DOW = ['일','월','화','수','목','금','토'];
        const formatDateWithDow = (s) => {
          if (!s) return '';
          const m = String(s).match(/^(\d{4})-(\d{2})-(\d{2})/);
          if (!m) return '';
          const dt = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
          return `${m[1]}-${m[2]}-${m[3]}(${_DOW[dt.getUTCDay()]})`;
        };
        const formatPeriodText = (ps, pe) => {
          const a = formatDateWithDow(ps), b = formatDateWithDow(pe);
          if (a && b && a !== b) return `${a} ~ ${b}`;
          if (a && b) return a;
          if (a) return `${a} 부터`;
          if (b) return `~ ${b}`;
          return '';
        };
        const itemsHtml = shown.map(d => {
          const catCls = d.is_cb ? 'cal-disc-cat cb' : 'cal-disc-cat';
          const catLabel = d.category || '기타';
          const periodText = formatPeriodText(d.period_start, d.period_end);
          const periodHtml = periodText
            ? `<span class="cal-disc-period"><span class="cal-disc-period-label">기간</span>${escapeHtml(periodText)}</span>`
            : '';
          // v2.5: 조건 박스 제거 (대표 정정 16:57 KST) — 빨간 뱃지가 같은 정보. title 1줄 클램프.
          return `<a class="cal-disc-item" href="${escapeHtml(d.url || '#')}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(d.title)}"><span class="${catCls}">${escapeHtml(catLabel)}</span><span class="cal-disc-summary">${escapeHtml(d.title)}${periodHtml}</span><svg class="cal-disc-ext" width="10" height="10" viewBox="0 0 10 10"><path d="M3 1h6v6M9 1L4 6" stroke="currentColor" stroke-width="1.2" fill="none"/></svg></a>`;
        }).join('');
        const moreHtml = moreCount > 0 ? `<span class="cal-disc-more">+${moreCount}건 더보기</span>` : '';
        const codeId = it.code || it.name;
        const sectionId = `disc-${escapeHtml(codeId)}`;
        // REQ-030 §1 — discBadgeHtml은 위에서 이미 설정 (모든 KRX 공시 트리거).
        // 여기서는 discListHtml만 설정 (STATUS_DISC_CATS 제외 정합 유지).
        discListHtml = `<div class="cal-disc-section" id="${sectionId}">${itemsHtml}${moreHtml}</div>`;
      }
      // 뉴스 제목 + 링크 (제목 표시)
      const linkSeen = new Set();
      const sourceMap = {'hankyung.com':'한경','mk.co.kr':'매경','edaily.co.kr':'이데일리','biz.chosun.com':'조선비즈','etoday.co.kr':'이투데이','news.naver.com':'네이버','n.news.naver.com':'네이버'};
      const allLinks = [...(st.news_digest || []).map(n => ({ url: n.url, title: n.inferred_title, source: n.source })), ...(it.links || []).map(l => ({ url: l.url, title: '', source: '' }))];
      const uniqueLinks = allLinks.filter(l => { if (!l.url || linkSeen.has(l.url)) return false; linkSeen.add(l.url); return true; }).map(l => {
        const host = (() => { try { return new URL(l.url).hostname.replace(/^www\./, ''); } catch (e) { return ''; } })();
        const src = l.source || sourceMap[host] || host;
        return { url: l.url, src };
      });
      // 소스명 중복 제거 — 같은 소스의 복수 기사는 첫 번째 URL로 대표
      const srcSeen = new Set();
      const dedupedLinks = uniqueLinks.filter(l => { if (srcSeen.has(l.src)) return false; srcSeen.add(l.src); return true; });
      const linksHtml = dedupedLinks.length > 0 ? `<div class="cal-feature-links">${dedupedLinks.map(l => {
        return `<a class="cal-feature-link" href="${escapeHtml(l.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(sanitize(l.src))}</a>`;
      }).join('')}</div>` : '';
      // 연속 선정 메타 (부수적 정보 — 뉴스 요약과 분리)
      const pp = st.prev_pick;
      const pc = st.pick_count;
      // REQ-059 명명 재정정 — "연속선정" (REQ-039 "거래대금"이 맥락 부족 → "연속선정+N"으로 정정).
      const pickMeta = (pp && pc >= 2)
        ? `<div class="cal-pick-meta"><div class="cal-disc-item"><span class="cal-disc-cat streak">연속선정+${pc}</span><span class="cal-disc-summary">전일 순위 #${pp.rank} · ${fmtTradeAmount(pp.trade_amount)} · ${(pp.change_pct||0)>=0?'+':''}${(pp.change_pct||0).toFixed(2)}%</span></div></div>`
        : '';
      // 종목명 우측 거래대금 연속 선정 배지 (헤더): 2+ → "연속선정+N", 1이면 비표시
      const pickBadge = pc != null && pc >= 2
        ? `<span class="cal-streak-badge">연속선정+${pc}</span>`
        : '';
      // REQ-039 — 강세 배지 (헤더, 종목명 우측, pickBadge 옆).
      // REQ-048 본질: data-loader.js가 entry → interp 합성 시 bullish 필드 패스스루 (REQ-048 data-loader 정정).
      // 따라서 st(=it.interp).bullish_today/streak 참조가 올바름. it.bullish_today 폴백도 안전성 확보.
      // streak >= 1 + bullish_today=true 일 때만 노출. streak=1이면 "강세", 2+면 "강세+N".
      const bullishStreak = (st && st.bullish_streak) || it.bullish_streak || 0;
      const bullishToday = !!((st && st.bullish_today) || it.bullish_today);
      const bullishBadge = (bullishToday && bullishStreak >= 1)
        ? `<span class="cal-bullish-badge">${bullishStreak > 1 ? `강세+${bullishStreak}` : '강세'}</span>`
        : '';
      // REQ-020c — cal-credit-badge 폐기. KRX 무관 신용 사유(회사한도초과·ETF 등)는
      // utils.js collectEffectBadges에 creditRiskInfo로 전달 → "신용불가(오늘)" v95 형식 통일.
      // dedup으로 KRX disclosure credit-block과 중복 자연 차단.
      const creditBadgeHtml = '';
      // REQ-021 v9.6 §II + §IV — 신용 사유 박스는 renderCreditBlockReasonBox로 통합 (KRX 단계 + 증권사 사유).
      // 본 위치 별도 출력은 이중 노출 우려로 무력화. dead code 잔존 (회귀 안전성).
      // const creditReasonHtml = (st.credit_risk && st.credit_reason) ? (() => { ... })() : '';
      const creditReasonHtml = '';
      // 종목 상태 뱃지 (투자주의/경고/위험/단기과열)
      // REQ-020 v9.5 §II.3 — 헤더 = 효과 배지 (효과 + 시점). v9.3 통합 라벨(`dsn-v93-header-badge`) 대체.
      // SSOT: build_daily.py status_badges[].effect_badges[] (각 항목 = {effect, when, severity, source_label, source_kind}).
      // utils.js collectEffectBadges = 카드 단위 머지(A1) + 우선순위 정렬(A4) + dedup.
      // A4 우선순위: 거래정지 > 신용불가 > 단일가 / today > today_and_tomorrow > tomorrow (v9.8 — DSN-010 §I).
      // 최대 N=3 노출 + "+N" 표기.
      const _v92HeaderViewDate = date || '';
      const _v92AllBadges = st.status_badges || [];
      // REQ-020c — KRX 무관 신용 사유 합성 effect_badge 통합 (라벨 형식 통일).
      // st = it.interp (라인 296), data-loader.js:198 credit_risk = !!entry.credit_risk.
      const _v95CreditRiskInfo = (st && st.credit_risk)
        ? { credit_risk: true, credit_reason: st.credit_reason || '신용 제한' }
        : null;
      const _v95EffectBadges = (typeof collectEffectBadges === 'function')
        ? collectEffectBadges(_v92AllBadges, _v92HeaderViewDate, _v95CreditRiskInfo)
        : [];
      const _v95VisibleN = 3;  // A4 — 최대 3개 노출
      const _v95Overflow = Math.max(0, _v95EffectBadges.length - _v95VisibleN);
      const _v95Visible = _v95EffectBadges.slice(0, _v95VisibleN);
      const _v95EffectBadgesHtml = _v95Visible.map(eb => {
        const label = (typeof dsnV95FormatEffectBadge === 'function') ? dsnV95FormatEffectBadge(eb) : '';
        const title = (typeof dsnV95EffectBadgeTitle === 'function') ? dsnV95EffectBadgeTitle(eb) : label;
        const cls = `dsn-v95-effect-badge dsn-v95-effect-badge--${eb.effect} dsn-v95-effect-badge--when-${eb.when}`;
        const krxStage = eb.source_label || '';
        return `<span class="${cls}" data-krx-stage="${escapeHtml(krxStage)}" data-effect="${escapeHtml(eb.effect)}" data-when="${escapeHtml(eb.when)}" title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}" role="button" tabindex="0">${escapeHtml(label)}</span>`;
      }).join('');
      // P2 함정 #4 — 가려진 효과 라벨 hover 텍스트 join (cropping bias 보강).
      const _v95MoreTitle = _v95Overflow > 0
        ? _v95EffectBadges.slice(_v95VisibleN)
            .map(eb => (typeof dsnV95FormatEffectBadge === 'function') ? dsnV95FormatEffectBadge(eb) : '')
            .filter(Boolean)
            .join(' / ')
        : '';
      const _v95MoreHtml = _v95Overflow > 0
        ? `<span class="dsn-v95-effect-badge dsn-v95-effect-badge--more" title="${escapeHtml(_v95MoreTitle || _v95Overflow + '건 추가')}" aria-label="${_v95Overflow}건 더 보기">+${_v95Overflow}</span>`
        : '';
      const _v95InnerHtml = _v95EffectBadgesHtml + _v95MoreHtml;
      const statusBadges = _v95InnerHtml
        ? `<span class="dsn-v95-effect-badges">${_v95InnerHtml}</span>`
        : '';
      // v9.2 §III: predicted only 카드 트리거 핀 (disclosure 0 + strict 미충족 predicted ≥1)
      const v92TriggerPinHtml = (typeof renderTriggerPin === 'function')
        ? renderTriggerPin(_v92AllBadges, _v92HeaderViewDate)
        : '';

      // 상태 뱃지 상세 v3 — 표 형태 + 기간 + 인사이트 (대표 정정 18:52 KST)
      // FLR-20260423-002 (P0-1, DSN-001 §15.5 / §17.4): 하드코딩 금지 원칙 단계 적용.
      // SSOT = rules/krx-stage-conditions.json → build_daily.py가 badge.auto_effects[]에 복제.
      // renderer는 badge.auto_effects[] 있으면 그것만 사용. 없으면 아래 _insightsFallback 사용.
      // 데이터 주입(data-dev) 완료 후 후속 PR에서 _insightsFallback 완전 삭제 예정.
      const _insightsFallback = {
        '투자주의': '이상 급등·거래량 급증 등 주의 신호가 포착된 종목입니다. 자동 규제는 없으며, 조건 지속 시 익일 투자경고 예고로 승급될 수 있습니다.',
        '투자경고': '신용거래 금지·위탁증거금 100% 현금·대용증권 불인정이 자동 적용됩니다. 지정 후 10거래일 경과 시 재심사로 해제 또는 투자위험 승급을 결정합니다.',
        '투자위험': '투자경고 효과(신용 금지·현금 증거금·대용 불인정)가 유지되며, 지정 직전 1거래일 매매거래정지가 적용됩니다. 승급 후 10거래일 경과 시 재심사.',
        '단기과열': '단기과열완화제도에 따라 D+2 1거래일 매매거래정지 후 D+3~D+5 3거래일간 30분 단위 단일가매매가 적용됩니다. D+5 자동 해제.',
        '단일가매매': '단기과열종목 지정에 따른 30분 단위 단일가매매 적용 기간입니다. 시장경보 3단계와 무관합니다.',
        '거래정지': '거래 정지 기간 — 정지 사유 해소 후 재개.',
        '관리종목': '관리종목 지정 — 신용거래·대용증권 불가, 미공시법인 추가 제재 가능.',
        '상장폐지': '상장폐지 절차 진행 — 정리매매 후 거래 종료.',
        '단기과열예고': '예고일부터 10거래일 이내 모든 조건 충족 시 단기과열 지정.',
      };
      // auto_effects 우선, 없으면 _insightsFallback 맵에서 label 기반 탐색.
      // auto_effects[]는 togusa JSON 직렬화 배열. 각 item: {id, label, quote, source_article}.
      const _resolveAutoEffects = (b) => {
        if (b && Array.isArray(b.auto_effects) && b.auto_effects.length > 0) {
          return b.auto_effects.map(e => (e && (e.quote || e.label)) || '').filter(Boolean);
        }
        return null; // null = 폴백 경로로 이동 신호
      };
      const _resolveInsightFallback = (label) => {
        for (const k in _insightsFallback) if (label.includes(k)) return _insightsFallback[k];
        return '';
      };
      // legacy API 유지 (v6 블록 호출부 호환). auto_effects 있으면 ul, 없으면 legacy 문구 폴백
      const _resolveInsight = (labelOrBadge) => {
        if (typeof labelOrBadge === 'object' && labelOrBadge !== null) {
          const ae = _resolveAutoEffects(labelOrBadge);
          if (ae) return ae.join(' · ');
          return _resolveInsightFallback(labelOrBadge.label || '');
        }
        return _resolveInsightFallback(labelOrBadge || '');
      };
      // v4: KRX 단계 진행 표 — "현재 X → 익일 Y 진입"
      // 라벨이 "X 예고"면 현재=X 직전 단계, 다음=X.
      // 라벨이 "X" (예고 없음)면 현재=X, 다음=X 다음 단계.
      const _stageNext = {
        '투자주의': '투자경고',
        '투자경고': '투자위험',
        '투자위험': '매매거래 정지',
        '단기과열': '단기과열 (1회 연장)',
      };
      const _stagePrev = {
        '투자경고': '투자주의',
        '투자위험': '투자경고',
        '단기과열': '단기과열 예고',
      };
      // 라벨에서 핵심 단계명 추출 (예: "투자경고 예고" → "투자경고", "[예고]" 제거 등)
      const _extractStage = (label) => {
        const cleaned = (label || '').replace(/[\[\]\(\)]/g, ' ').trim();
        const stages = ['투자주의', '투자경고', '투자위험', '단기과열', '관리종목', '상장폐지', '거래정지'];
        for (const s of stages) if (cleaned.includes(s)) return s;
        return '';
      };
      const _resolveProgress = (b) => {
        const label = b.label || '';
        const stage = _extractStage(label);
        if (!stage) return '';
        // v4: source='predicted'(자체 추정 라벨)는 "예상/근접" 텍스트 — 단계 진행 표시 생략
        // "예상/근접"은 가격 조건만 충족, 거래량 미검증 → 진짜 KRX 단계 진입 보장 X
        if ((b.source === 'predicted') || label.includes('예상') || label.includes('근접')) return '';
        const isNotice = label.includes('예고') || (b.view_date && b.start && b.view_date < b.start && !((b.source === 'predicted') || label.includes('예상') || label.includes('근접')));
        // FLR-011 v6: "현재" = view_date(t, 페이지 날짜). "익일" = t+1 거래일.
        // b.end/b.start는 공시 효력 기간 — "현재" 시점이 아님 (별도 기간 행에 표시).
        // view_date가 없고 b.start가 페이지 날짜보다 미래면 "현재"로 표기 금지 (예고 구간 오노출 차단).
        let curDate = b.view_date || '';
        if (!curDate) {
          if (b.start && (!date || b.start <= date)) {
            curDate = b.start;
          } else {
            // view_date 미주입 + start가 미래/없음 → "현재→다음" 표시 생략
            return '';
          }
        }
        let nextDate = b.next_trading_day || '';
        if (!nextDate) {
          try {
            const d = new Date(curDate + 'T00:00:00');
            d.setDate(d.getDate() + 1);
            nextDate = d.toISOString().slice(0, 10);
          } catch (e) {}
        }
        const dateText = nextDate ? `익일(${nextDate})` : '익일';
        if (isNotice) {
          // 예고 단계: 현재 = 직전 단계 (또는 "예고 상태"), 다음 = stage 본체
          const prev = _stagePrev[stage] || `${stage} 예고`;
          return `현재: ${prev} (${curDate}) → ${dateText} 조건 충족 시 ${stage} 진입`;
        }
        const next = _stageNext[stage];
        if (!next) return '';
        return `현재: ${stage} (${curDate}) → ${dateText} 조건 충족 시 ${next} 진입`;
      };
      // === v8 (DSN-20260425-DSN-002, REQ-010): 시제 분리 정보 위계 ===
      // §3·§4·§5.1·§6.1·§6.2 — 시제 칩 + 5줄 요약 + 🎯 thresholds + 통합 펼침.
      // 복수 배지는 시제 순서(현재 → 예측)로 배치 (§9 시나리오 A).
      const _v8FilteredBadges = (st.status_badges || []).filter(b =>
        b.thresholds || b.regulation || b.start || b.label || (b.single_price === true && (b.label || '').includes('단기과열'))
      );
      const _v8SortedBadges = dsnV8SortBadges(_v8FilteredBadges);
      const _v8AllDiscs = st.disclosures || [];
      const _v8DartByStage = (label) => {
        const stripped = dsnV8StripStageLabel(label || '');
        if (!stripped || _v8AllDiscs.length === 0) return '';
        const m = _v8AllDiscs.find(d => (d.category || '').includes(stripped));
        return (m && m.url) || '';
      };
      const _v8CtxFor = (b) => ({
        currentDate: date || b.view_date || '',
        stockCode: it.code || '',
        dartUrl: _v8DartByStage(b.label),
        stageDefinition: '',  // togusa krx-stage-rules.json 후속 주입
        regulationDetail: '', // togusa krx-stage-rules.json 후속 주입
        // v9.1 strict: getPredictedTenseVariant 인접 검증용 (4/24 027360 단계 도약 케이스 차단)
        allBadges: _v8SortedBadges,
      });
      // REQ-021 v9.6 §III.4 — 단계별 v6/v5 표 통째 무력화. 신용불가 사유 박스(§II)로 대체.
      // dsnV8RenderBlock·sections.push(v6SectionsHtml)·"준비 중" 폴백 등 모두 dead code 잔존 (회귀 1줄 부활 안전성).
      // const v8DetailHtml = _v8SortedBadges.map(b => dsnV8RenderBlock(b, _v8CtxFor(b))).join('');
      const v8DetailHtml = '';

      // === v6/v5.1 legacy 블록 통째 제거 (REQ-082 Phase2 — 2026-04-29) ===
      // statusDetailLegacyHtml + .map() 545줄 통째 폐기 (어디서도 사용 안 됨, FLR-20260429-FLR-001 §10).
      // 상한가 +N chip은 dsn-v95-effect-badges 시스템(utils.js limit-up effect)으로 이전 — 카드 head 영역 라이브 노출.
      // 회귀 시 git history (worktree-req-chip-recovery 이전) 에서 변수 + 545줄 블록 부활 가능.
      // REQ-021 v9.6 §I.1 — 그래프 박스 통째 제거 (이중 가드). utils.js renderStageFlowV9 무력화 정합.
      // 함수 자체는 첫 줄 return '' 보유 — 본 호출부도 명시 빈 문자열로 dead code 회귀 차단.
      const v9StageFlowHtml = '';
      // REQ-021 v9.6 §III.4 — predicted detail-only 영역도 명시 빈 문자열 (renderPredictedDetailOnly 자체도 첫 줄 return ''. 이중 가드)
      const v92PredictedDetailOnlyHtml = '';
      // REQ-021 v9.6 §IV.2 — 신용불가 사유 박스 (KRX 단계 + 증권사 사유 통합). 그래프 박스·v6 표 대체.
      const v96CreditBlockHtml = (typeof renderCreditBlockReasonBox === 'function')
        ? renderCreditBlockReasonBox(_v8SortedBadges, date || '', _v95CreditRiskInfo)
        : '';
      const statusDetailHtml = `${v96CreditBlockHtml}`;
      // causal 있으면 ishikawa는 details, 없으면 summary에 가므로 details 대상 아님
      const hasDetails = !!(statusDetailHtml || discListHtml || creditReasonHtml || (causalHtml && ishikawaHtml) || pickMeta);
      // toggle 요약 v3: period + label 만 (대표 정정 18:52 KST — 임계 정보는 표로 이동)
      const _badgeForSummary = (st.status_badges || []).find(b => b.start) || (st.status_badges || [])[0];
      let summarySnippet;
      if (_badgeForSummary) {
        const ps = _badgeForSummary.start || '';
        const pe = _badgeForSummary.end || '';
        const dateText = ps && pe && ps !== pe ? `${ps}~${pe}` : (ps || pe || '');
        const lbl = _badgeForSummary.label || '';
        summarySnippet = dateText ? `${dateText} ${lbl}`.trim() : lbl;
      } else if ((st.disclosures || []).length > 0) {
        summarySnippet = `공시 ${st.disclosures.length}건`;
      } else {
        summarySnippet = '';
      }
      // REQ-030 §2 — 접기 버튼 칩 디자인 (SPEC-001 §III.5). chevron-only 폐기.
      // 텍스트 "상세 보기" + 화살표 ▾ (CSS .cal-feature-card.expanded 시 회전 + ::after content "접기").
      const truncatedSummary = '';
      // REQ-045 §D — span → div 통일 (inline width:100% 무효 → 데스크탑 흐릿함 원인). chevron 폐기 (텍스트만).
      const chevronHtml = hasDetails
        ? `<div class="cal-detail-toggle" aria-label="상세 보기"><span class="cal-toggle-text">상세 보기</span></div>`
        : '';
      // REQ-064 (2026-04-28): v9.2 §III 트리거 핀 제거 — renderTriggerPin은 빈 문자열 반환 (utils.js).
      // v92TriggerPinHtml은 항상 ''이므로 조건/삽입 모두 무영향. 호출 보존(미래 부활 안전성).
      const badgesRowHtml = (pickBadge || bullishBadge || discBadgeHtml || creditBadgeHtml || statusBadges || v92TriggerPinHtml)
        ? `<div class="cal-feature-badges">${statusBadges}${pickBadge}${bullishBadge}${discBadgeHtml}${creditBadgeHtml}${v92TriggerPinHtml}</div>`
        : '';
      // 테마 칩은 링크 아래 별도 줄
      const sparkHtml = it.interp?.intraday
        ? `<div class="cal-feature-sparkline">${buildSparkline(it.interp.intraday.prices, it.interp.intraday.base ?? it.interp.intraday.open, candleDir)}</div>`
        : '<div class="cal-feature-sparkline cal-spark-empty"></div>';
      // REQ-pm320-ux-cycle #3 — 20영업일 일봉 캔들 (sparkline 우측, 모바일은 CSS로 sparkline 숨김 + candles20만).
      const d20 = it.interp?.daily_20;
      // #4 안전망: daily_20 마지막 봉 일자 < 카드 일자 시 라벨 노출 (design-news-time-state-v1, catch 2)
      // 위치 변경: candles20 내부 absolute → cal-feature-meta sibling으로 이동 (PRE_MARKET 자연 봉쇄 + 11px 가독성).
      // 텍스트 정정: "데이터 05/07" → "5/7 종가 기준" (의미 명료).
      let candles20Html;
      let staleMetaHtml = '';

      // P0-23 Fix-79 (2026-05-21 19:38 KST 대표 verbatim
      //   "제주반도체 일봉캔들 영웅문을 보면 강세 날짜가 상당히 많다. 그런데 오늘 하루만 강세로 표시가 된다"):
      //   분홍 vertical line 본문 SoT (backend) 직접 사용 본질 — P0-21 backend rollout cascade.
      //   - P0-18 Fix-61 backward derive (streak=N → daily_20 마지막 N건) 본질 폐기
      //   - root cause = streak 본문 "연속 강세 N영업일" 본질 (오늘 + N-1일 cap) → 강세 history 단속 영업일 (예: 4/24, 5/14 등 비연속) 부재
      //   - SoT = backend build_daily.py L3188 entry["bullish_dates"] (list[str] YYYY-MM-DD, 30일 range 강세 영업일 모두)
      //   - data-loader.js Fix-79 (L240) bullish_dates pass-through 본문 합성 → it.bullish_dates / it.interp.bullish_dates
      //
      //   §11.15 외부 spec 사전 검증 PASS:
      //     - build_daily.py _prefetch_bullish_info L2509-2609 verbatim grep (30일 range 강세 영업일 list[str])
      //     - build_daily.py L3188 entry["bullish_dates"] = bullish_dates verbatim grep
      //     - 라이브 evidence: curl 본문 제주반도체 080220 → bullish_dates 4건 ['2026-04-24','2026-05-14','2026-05-18','2026-05-21']
      //     - 영웅문 image 797cf4ef direct read evidence: 제주반도체 분홍 vertical line 4건+ visible (4/24, 5/14, 5/18, 5/21)
      //
      //   §16 self-catch:
      //   - bullish_dates 부재 path (old data / IPO 첫날 등) → backward derive 폴백 본문 graceful 유지
      //   - 광전자 (#2) bullish_today=false 본문 → bullish_dates 부재 / 빈 array → 분홍 vertical line 0건 정합
      const _bullishDatesRaw = (Array.isArray(it.bullish_dates) ? it.bullish_dates : null)
        || (it.interp && Array.isArray(it.interp.bullish_dates) ? it.interp.bullish_dates : null);
      let _pinkSignalDates = [];
      if (Array.isArray(_bullishDatesRaw) && _bullishDatesRaw.length > 0) {
        // SoT 직접 사용 — backend 본문 30일 range 모든 강세 영업일 (오름차순, today 마지막)
        _pinkSignalDates = _bullishDatesRaw.filter(d => typeof d === 'string' && d.length === 10);
      } else {
        // 폴백 — bullish_dates 부재 path (old data) backward derive 본문 graceful 유지
        const _bullishToday = !!(it.bullish_today || (it.interp && it.interp.bullish_today));
        const _bullishStreak = (it.bullish_streak || (it.interp && it.interp.bullish_streak)) || 0;
        if (_bullishToday && _bullishStreak >= 1 && Array.isArray(d20) && d20.length >= 1) {
          const _streakN = Math.min(_bullishStreak, d20.length);
          for (let _i = d20.length - _streakN; _i < d20.length; _i++) {
            const _bar = d20[_i];
            if (_bar && _bar.date) _pinkSignalDates.push(_bar.date);
          }
        }
      }

      // Q-20260512-FRESH-LISTING-DATA — 자연 데이터 1건 이상이면 그대로 렌더.
      // 신규 상장(코스모로보틱스 5/11)은 build_daily가 1건 적재 → 자연 노출 (합성 폐기).
      if (Array.isArray(d20) && d20.length >= 1) {
        const lastBarDate = d20[d20.length - 1]?.date;
        const isStale = lastBarDate && date && lastBarDate < date;
        if (isStale) {
          const md = lastBarDate.slice(5).replace('-', '/').replace(/^0/, '');
          staleMetaHtml = `<div class="cal-feature-stale-note" aria-label="가격 데이터 시점">${md} 종가 기준</div>`;
        }
        // cycle22 P1: 미니캔들 클릭 → 확대 차트 expand. data-daily20 = 20영업일 raw (JSON stringified).
        // Phase 3 240일 backend swap 시 data-daily20을 240bar로 교체 가능 (구조 변경 없음).
        const _d20Json = JSON.stringify(d20).replace(/"/g, '&quot;');
        // P0-18 Fix-61: data-pinksignal attribute 본문 신축 (bullish 종목 본문만 visible).
        const _pinkAttr = _pinkSignalDates.length > 0
          ? ` data-pinksignal="${JSON.stringify(_pinkSignalDates).replace(/"/g, '&quot;')}"`
          : '';
        // SPEC §5.6 MAJOR-1 — aria-controls anchor (stable id `chart-{code}` slot 측 정합)
        candles20Html = `<div class="cal-feature-candles20" data-expand-trigger="chart" data-daily20="${_d20Json}"${_pinkAttr} role="button" tabindex="0" aria-label="20영업일 일봉, 클릭 시 확대 차트" aria-expanded="false" aria-controls="chart-${escapeHtml(it.code || '')}">${buildCandles20(d20)}</div>`;
      } else {
        // cycle21 P1 (2026-05-20 15:57 KST) — IPO 첫날 일봉 spec 정합 (장대양봉 → 점상 fix).
        // 본질: build_daily가 IPO 첫날 종목(마키나락스 477850 등)은 daily_20=None 적재 → 미니캔들 빈 영역.
        // 대표 catch 15:08 (cycle20): "마키나락스는 일봉캔들차트가 보이지 않는다" → frontend 폴백 신설.
        // 대표 catch 15:57 (cycle21): "마키나락스 일봉캔들의 경우 점상인데 장대양봉 처럼 보이는 이유가 뭐지".
        // 본질 evidence (WebSearch 2건 corroborating 2026-05-20):
        //   - 서울경제/뉴스핌: 마키나락스 5/20 시초가 60,000원 형성 + 개장 직후 상한가 직행 (공모가 15,000원 ×4 따따블).
        //   - 한국 시장 관습: '점 상한가(쩜상)' = 시초가가 상한가에서 시작 → OHLC 모두 동일.
        // 일봉차트 spec (영웅문 정합):
        //   - 일봉 OHLC = '거래 가격' 기준 (시초가/고가/저가/종가). 공모가(청약 가격)는 일봉 OHLC에 포함 안 됨.
        //   - IPO 첫날 점상: o = h = l = c = 시초가 (60,000) → mini-candle.js L31-32 isFlat 분기 → 회색 horizontal line.
        //   - 공모가 정보(15,000)는 title hover에 정보 가치 보존 (사용자 학습 효과).
        // before (cycle20): o=공모가, c=현재가 → 장대양봉 (잘못된 일봉 semantic).
        // after (cycle21): o=시초가, c=현재가, h/l=시초가·현재가·intraday prices (공모가 제외) → 점상 또는 정상 캔들.
        // 영웅문 spec 가정 (lead 추정 — 직접 캡처 부재): IPO 첫날 시초가 동결 시 점상 표시. 영웅문 캡처 evidence 부재 시 대표 cross-check 의무.
        const _themes = it.interp?.themes || it.themes || [];
        const _isIpoFirst = _themes.some(t => {
          const _tname = typeof t === 'string' ? t : (t && t.name) || '';
          return _tname === '신규상장' || _tname.includes('신규상장');
        });
        const _intra = it.interp?.intraday;
        const _ipoBase = _intra?.base; // 공모가 (title hover 정보 보존용)
        const _ipoOpen = _intra?.open ?? it.interp?.open_price ?? it.open; // 시초가 (일봉 OHLC의 o)
        const _ipoClose = it.interp?.close_price ?? it.price ?? (Array.isArray(_intra?.prices) && _intra.prices.length ? _intra.prices[_intra.prices.length - 1] : null);
        const _intraPricesValid = Array.isArray(_intra?.prices) ? _intra.prices.filter(p => typeof p === 'number' && p > 0) : [];
        if (_isIpoFirst && _ipoClose && _ipoClose > 0) {
          // 1-bar synthesis: 일봉 OHLC = 거래 가격 기준 (공모가 제외).
          // 시초가 fallback: _ipoOpen 부재 시 _ipoClose 사용 (점상 보장).
          const _openPrice = (_ipoOpen && _ipoOpen > 0) ? _ipoOpen : _ipoClose;
          const _allPoints = [_openPrice, _ipoClose, ..._intraPricesValid];
          const _ipoHigh = Math.max(..._allPoints);
          const _ipoLow = Math.min(..._allPoints);
          const _ipoBar = [{
            date: date,
            o: _openPrice,
            h: _ipoHigh,
            l: _ipoLow,
            c: _ipoClose,
          }];
          // title: 공모가 정보 보존 (있을 때만), 일봉 OHLC는 시초가→현재가 명시.
          const _titleParts = [`IPO 첫날 일봉`];
          if (_ipoBase && _ipoBase > 0) _titleParts.push(`공모가 ${_ipoBase.toLocaleString()}원`);
          _titleParts.push(`시초가 ${_openPrice.toLocaleString()}원 → 현재가 ${_ipoClose.toLocaleString()}원`);
          const _title = _titleParts.join(' / ');
          // cycle22 P1: IPO 1-bar 합성도 클릭 trigger 부여. 보조지표 대부분은 데이터 부족 placeholder 표시.
          const _ipoJson = JSON.stringify(_ipoBar).replace(/"/g, '&quot;');
          // SPEC §5.6 MAJOR-1 — aria-controls anchor (stable id `chart-{code}` slot 측 정합)
          candles20Html = `<div class="cal-feature-candles20 cal-candles20-ipo" data-expand-trigger="chart" data-daily20="${_ipoJson}" role="button" tabindex="0" aria-label="IPO 첫날 일봉, 클릭 시 확대 차트" aria-expanded="false" aria-controls="chart-${escapeHtml(it.code || '')}" title="${_title}">${buildCandles20(_ipoBar)}</div>`;
        } else {
          candles20Html = '<div class="cal-feature-candles20 cal-candles20-empty"></div>';
        }
      }

      // 240영업일 가격 레인지 바 (REQ-001 Phase 2 안 B / 레이아웃 v2 — 4행 분해)
      const r240 = it.interp?.range_240d;
      let rangeHtml = '';
      if (r240 && r240.high > 0 && r240.low > 0 && r240.current) {
        const span = r240.high - r240.low;
        const markerLeft = span > 0
          ? Math.max(0, Math.min(100, ((r240.current - r240.low) / span) * 100))
          : 50;
        const lowFillPct = 0;
        const highFillPct = markerLeft;
        const fmtPct = (v) => {
          if (v == null) return '';
          const sign = v > 0 ? '+' : '';
          return `${sign}${v.toFixed(1)}%`;
        };
        // 대표 지시 (2026-04-25 09:31~09:32):
        // - 신고가/신저가 양 끝 갱신 시 텍스트로 표시 ('신고가'/'신저가')
        // - 좌측 신저가 → 파랑(.down), 우측 신고가 → 빨강(.up)
        const isNewLow = r240.low === r240.current;
        const isNewHigh = r240.high === r240.current;
        const lowText = isNewLow ? '신저가' : fmtPct(r240.low_pct);
        const highText = isNewHigh ? '신고가' : fmtPct(r240.high_pct);
        const lowCls = isNewLow ? 'down' : ((r240.low_pct ?? 0) >= 0 ? 'up' : 'down');
        const highCls = isNewHigh ? 'up' : ((r240.high_pct ?? 0) <= 0 ? 'down' : 'up');
        rangeHtml = `<div class="stock-range v2">
          <div class="range-bar">
            <div class="range-fill" style="--low-pct:${lowFillPct}%;--high-pct:${highFillPct}%"></div>
            <div class="range-marker" style="left:${markerLeft}%"></div>
          </div>
          <div class="range-row range-prices">
            <span class="r-low">${r240.low.toLocaleString('ko-KR')}원</span>
            <span class="r-now">${r240.current.toLocaleString('ko-KR')}원</span>
            <span class="r-high">${r240.high.toLocaleString('ko-KR')}원</span>
          </div>
          <div class="range-row range-pcts">
            <span class="r-low ${lowCls}">${lowText}</span>
            <span class="r-now r-now-label">현재가</span>
            <span class="r-high ${highCls}">${highText}</span>
          </div>
          <div class="range-row range-dates">
            <span class="r-low">${escapeHtml(r240.low_date || '')}</span>
            <span class="r-now"></span>
            <span class="r-high">${escapeHtml(r240.high_date || '')}</span>
          </div>
        </div>`;
      }
      // 메타 줄 (등락률 | 거래대금) — 좌측 정렬·파이프 구분·거래대금 골드 (대표 정정 v2.2)
      const metaRow = `<div class="cal-feature-meta">
        <span class="cal-feature-pct ${dir}">${pctText}</span>
        <span class="cal-meta-sep">|</span>
        <span class="cal-trade-amount">${amountText}</span>
      </div>`;
      const _idAttr_full = it.code ? ` id="stock-${escapeHtml(it.code)}"` : '';
      // Q-20260519-CYCLE19-009 + cycle20 P1 (2026-05-20) — LU(상한가) 좌측 accent bar 시각 구분.
      // 기존: _source_union='limit_up' 단일 조건 → kiwoom.latest_stocks 內 상한가(녹십자엠에스 등) 누락.
      // 본질 fix: status_badges effect='limit-up' OR _source_union='limit_up' → source 무관 일관 적용 (대표 catch 15:08).
      const _isLU_full = it._source_union === 'limit_up' || _hasLimitUpEffect(it.interp);
      const _luClass_full = _isLU_full ? ' cal-feature-card--lu' : '';
      const _luAria_full = _isLU_full ? ' aria-label="상한가 종목"' : '';
      return `
        <div class="cal-feature-card v2${_luClass_full}"${_idAttr_full}${_luAria_full} data-stock-code="${escapeHtml(it.code || '')}" data-stock-name="${escapeHtml(it.name || '')}">
          ${renderShareButton(it)}
          <div class="cal-feature-head v2">
            <div class="cal-feature-head-left">
              <div class="cal-trade-rank">#${it.rank}</div>
              <div class="cal-trade-candle">${candleHtml}</div>
              ${sparkHtml}
              ${candles20Html}
            </div>
            <div class="cal-feature-head-right">
              <div class="cal-feature-namecell">
                <span class="cal-feature-name">${escapeHtml(it.name)}</span>
              </div>
              ${metaRow}
              ${staleMetaHtml}
            </div>
          </div>
          ${rangeHtml}
          ${badgesRowHtml}
          <div class="cal-feature-body">
            ${headlineHtml || ishikawaHtml || causalHtml || linksHtml || discListHtml || themesHtml || pickMeta
              ? `<div class="cal-feature-summary">${causalHtml || ishikawaHtml}${themesHtml ? `<div class="cal-theme-row">${themesHtml}</div>` : ''}${linksHtml}${hasDetails ? `<div class="cal-detail-toggle" aria-label="상세 보기"><span class="cal-toggle-text">상세 보기</span></div>` : ''}</div>${hasDetails ? `<div class="cal-feature-details">${statusDetailHtml}${discListHtml}${creditReasonHtml}${causalHtml ? ishikawaHtml : ''}${pickMeta}${(typeof renderMicroDisclaimerIfShared === 'function') ? renderMicroDisclaimerIfShared() : ''}</div>` : ''}`
              : `<div class="cal-feature-news-empty">뉴스 분석 대기 중</div>`}
          </div>
        </div>`;
    }

    // ===== interp 없음: full 카드 구조 유지 + "뉴스 없음" placeholder =====
    // 대표 지시 (B안, 2026-04-22 16:07 KST): 레이아웃 일관성 유지. compact 한 줄 폐지.
    // kiwoom JSON 기반 데이터만 사용 (range_240d/intraday/news 없음 → 해당 영역은 생략 또는 placeholder)
    const compactPC = it.interp?.pick_count;
    // REQ-059 표기 재정정 — "연속선정+N" (REQ-039 "거래대금"이 맥락 부족).
    const compactBadge = compactPC != null && compactPC >= 2
      ? `<span class="cal-streak-badge">연속선정+${compactPC}</span>`
      : '';
    // REQ-048 — no-interp 카드 (와이제이링크 등)에도 강세 배지 노출.
    // it.interp 부재 케이스: it.bullish_today/streak 직접 참조 (entry 루트 패스스루).
    // it.interp 존재 케이스: data-loader 합성된 interp 객체에서 추출.
    const compactBullishStreak = it.interp?.bullish_streak || it.bullish_streak || 0;
    const compactBullishToday = !!(it.interp?.bullish_today || it.bullish_today);
    const compactBullishBadge = (compactBullishToday && compactBullishStreak >= 1)
      ? `<span class="cal-bullish-badge">${compactBullishStreak > 1 ? `강세+${compactBullishStreak}` : '강세'}</span>`
      : '';
    // 테마 칩: interp 없어도 it.themes는 kiwoom merge 단계에서 있을 수 있음
    const simpleThemesHtml = (it.themes && it.themes.length > 0)
      ? `<div class="cal-theme-row">${it.themes.slice(0, 3).map(t => `<span class="cal-ind-chip">${escapeHtml(t.name)}</span>`).join('')}</div>`
      : '';
    // sparkline: intraday 없음 → 빈 영역(full 카드와 정렬 맞춤)
    const emptySparkHtml = '<div class="cal-feature-sparkline cal-spark-empty"></div>';
    // range bar: 데이터 부재 → 생략 (대표 지시: 빈 공간 두지 말 것)
    // 메타 줄 (등락률 | 거래대금)
    const metaRow = `<div class="cal-feature-meta">
      <span class="cal-feature-pct ${dir}">${pctText}</span>
      <span class="cal-meta-sep">|</span>
      <span class="cal-trade-amount">${amountText}</span>
    </div>`;
    // 본문: "관련 뉴스 없음" placeholder — 기존 .cal-feature-news-empty 스타일 재사용
    const emptyBodyHtml = simpleThemesHtml
      ? `${simpleThemesHtml}<div class="cal-feature-news-empty">관련 뉴스 없음</div>`
      : `<div class="cal-feature-news-empty">관련 뉴스 없음</div>`;
    const _idAttr_nointerp = it.code ? ` id="stock-${escapeHtml(it.code)}"` : '';
    // Q-20260519-CYCLE19-009 + cycle20 P1 (2026-05-20) — LU(상한가) 좌측 accent bar (no-interp 분기 정합)
    // status_badges effect 우선 (it.interp 없어도 it.status_badges 패스스루 시 동작), _source_union 폴백.
    const _isLU_nointerp = it._source_union === 'limit_up' || _hasLimitUpEffect(it.interp) || _hasLimitUpEffect(it);
    const _luClass_nointerp = _isLU_nointerp ? ' cal-feature-card--lu' : '';
    const _luAria_nointerp = _isLU_nointerp ? ' aria-label="상한가 종목"' : '';
    return `
      <div class="cal-feature-card v2 no-interp${_luClass_nointerp}"${_idAttr_nointerp}${_luAria_nointerp} data-stock-code="${escapeHtml(it.code || '')}" data-stock-name="${escapeHtml(it.name || '')}">
        ${renderShareButton(it)}
        <div class="cal-feature-head v2">
          <div class="cal-feature-head-left">
            <div class="cal-trade-rank">#${it.rank}</div>
            <div class="cal-trade-candle">${candleHtml}</div>
            ${emptySparkHtml}
          </div>
          <div class="cal-feature-head-right">
            <div class="cal-feature-namecell">
              <span class="cal-feature-name">${escapeHtml(it.name)}</span>
              ${compactBadge}
              ${compactBullishBadge}
            </div>
            ${metaRow}
          </div>
        </div>
        <div class="cal-feature-body">
          ${emptyBodyHtml}
        </div>
      </div>`;
  };

  const rankingBanner = '';
  // Phase 2c-1 (2026-05-23) — single-card mode 본 본 section title / 뉴스요약 / macro / ranking 본 본 hide.
  // 단독 카드 본 본 본 본 본 본 sparkline + chart-tv + bullish lines + status_badges 전체 본 본 본 본 본 본.
  const _sectionTitleHtml = _isSingleCardMode ? '' : '<div class="cal-section-title">오늘의 뉴스요약</div>';
  const _narrPillsHtmlOut = _isSingleCardMode ? '' : narrPillsHtml;
  const _macroHtmlOut = _isSingleCardMode ? '' : macroHtml;
  const _rankingBannerOut = _isSingleCardMode ? '' : rankingBanner;
  const todayHtml = `
    <div class="cal-section${_isSingleCardMode ? ' cal-section--single-card' : ''}">
      ${_sectionTitleHtml}
      ${_narrPillsHtmlOut}
      ${_macroHtmlOut}
      ${_rankingBannerOut}
      ${todayStocks.length > 0 ? `
        <div class="cal-trade-list" style="margin-top:10px;">
          ${todayStocks.map(renderTodayCard).join('')}
        </div>
      ` : `
        ${_isSingleCardMode
          ? `<div class="cal-empty" style="padding:24px 0;">단독 카드 mode — 종목 코드 ${escapeHtml(_singleCardCode || '')} 본 본 데이터 없음</div>`
          : (isMarketClosed(date) ? (() => { const nd = getNextTradingDate(date); const nl = nd ? formatKoDate(nd) : ''; return `<div style="text-align:center;padding:32px 0;"><div style="font-size:15px;font-weight:700;color:var(--tx2);margin-bottom:6px;">오늘은 장이 쉽니다</div><div style="font-size:12px;color:var(--dm);">${nl ? '다음 거래일 ' + escapeHtml(nl) : ''}</div></div>`; })() : '<div class="cal-empty" style="padding:24px 0;">조건검색 데이터 없음 — 장 마감 후 또는 파이프라인 실행 후 업데이트</div>')}
      `}
    </div>
  `;

  const _rulesVersionBanner = _buildRulesVersionBanner(data && data.rules_version);
  // Phase 2c-1 (2026-05-23) — single-card mode 본 본 rules-version banner / cal-content-head 본 본 hide.
  // 외부 임베딩 본 본 본 본 본 본 본 본 본 본 본 본 본 본 본 본 본 본 본 본 본 본 본 본 본 본 본 본 본 본 본 본 본 본 본 단독.
  if (_isSingleCardMode) {
    inner.innerHTML = todayHtml;
  } else {
    inner.innerHTML = `
      ${_rulesVersionBanner}
      <div class="cal-content-head" role="button" tabindex="0" aria-label="달력으로 이동" data-scroll-to-cal="1">
        <div class="cal-content-date">${formatKoDate(date)}</div>
        <div class="cal-content-meta">${metaText}</div>
      </div>
      ${todayHtml}
    `;
  }

  // 접기/펼치기 이벤트 위임 (1회만 등록)
  // REQ-046 — CSS font-size:0 + ::after content trick 폐기 → JS textContent 직접 변경.
  // aria-label 동시 갱신 (스크린리더 정합).
  if (!window._cardCollapseInit) {
    document.addEventListener('click', e => {
      const toggle = e.target.closest('.cal-detail-toggle');
      if (!toggle) return;
      const card = toggle.closest('.cal-feature-card');
      if (!card) return;
      card.classList.toggle('expanded');
      const isExpanded = card.classList.contains('expanded');
      const txt = toggle.querySelector('.cal-toggle-text');
      if (txt) txt.textContent = isExpanded ? '접기' : '상세 보기';
      toggle.setAttribute('aria-label', isExpanded ? '접기' : '상세 보기');
    });
    window._cardCollapseInit = true;
  }

  // REQ-pm320-ux-cycle #1 — cal-content-head 클릭/Enter/Space → #toss-cal scrollIntoView.
  // 모바일에서 카드 list 깊이 스크롤 후 달력 역접근 어려움 해소. 데스크탑은 sticky로 이미 보이지만
  // page top 정렬 시 toss-cal이 시야 중앙으로 회귀하여 다른 날짜 클릭 부담 ↓.
  if (!window._calHeadScrollInit) {
    const scrollToCal = () => {
      const target = document.getElementById('toss-cal');
      if (!target) return;
      const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      const isMobile = window.innerWidth <= 880;
      // sticky nav header 68px(데스크탑) / 76px(모바일 nav 추정) 보정.
      const navOffset = isMobile ? 76 : 84;
      const rect = target.getBoundingClientRect();
      const top = window.pageYOffset + rect.top - navOffset;
      window.scrollTo({ top: Math.max(0, top), behavior: reduce ? 'auto' : 'smooth' });
    };
    document.addEventListener('click', e => {
      const head = e.target.closest('[data-scroll-to-cal]');
      if (!head) return;
      // 헤더 내부 다른 인터랙티브 요소(링크/버튼) bubble 차단 — 현재는 하위 요소 없음, 안전망.
      if (e.target.closest('a, button, input, [role="button"]:not([data-scroll-to-cal])')) return;
      // 시각 펄스 (reduced-motion 시 transform 생략 — CSS @media 처리)
      head.classList.add('cal-content-head--pulse');
      setTimeout(() => head.classList.remove('cal-content-head--pulse'), 200);
      scrollToCal();
    });
    document.addEventListener('keydown', e => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const head = e.target.closest('[data-scroll-to-cal]');
      if (!head) return;
      e.preventDefault();
      head.classList.add('cal-content-head--pulse');
      setTimeout(() => head.classList.remove('cal-content-head--pulse'), 200);
      scrollToCal();
    });
    window._calHeadScrollInit = true;
  }

  // REQ-homepage-news-polish #2 — 섹션 헤더 sticky + 클릭 → 자기 섹션 scrollIntoView.
  // design-lead-2 spec (2026-04-29 17:18 KST): scrollIntoView({behavior:'smooth', block:'start'}).
  // sticky nav 가림은 CSS scroll-margin-top: 132/120px 으로 회피.
  if (!window._sectionHeaderScrollInit) {
    const pulseClassFor = (head) => {
      const cls = head.classList;
      if (cls.contains('theme-trend-header')) return 'theme-trend-header--pulse';
      if (cls.contains('lut-header')) return 'lut-header--pulse';
      if (cls.contains('theme-tree-header')) return 'theme-tree-header--pulse';
      return '';
    };
    const scrollToSection = (head) => {
      const id = head.getAttribute('data-scroll-to-section');
      if (!id) return;
      const target = document.getElementById(id);
      if (!target) return;
      const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      target.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
    };
    const triggerPulse = (head) => {
      const pc = pulseClassFor(head);
      if (!pc) return;
      head.classList.add(pc);
      setTimeout(() => head.classList.remove(pc), 200);
    };
    document.addEventListener('click', e => {
      const head = e.target.closest('[data-scroll-to-section]');
      if (!head) return;
      if (e.target.closest('a, button, input, [role="button"]:not([data-scroll-to-section])')) return;
      triggerPulse(head);
      scrollToSection(head);
    });
    document.addEventListener('keydown', e => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const head = e.target.closest('[data-scroll-to-section]');
      if (!head) return;
      e.preventDefault();
      triggerPulse(head);
      scrollToSection(head);
    });
    window._sectionHeaderScrollInit = true;
  }

  // REQ-020 v9.5 §II.6 — 헤더 효과 배지 click 시 카드 자동 펼침 (v9.3 호환 — 셀렉터만 교체).
  // 함정 P2 #5: legacy `dsn-v93-header-badge` 셀렉터는 DOM 출력 0건 자연 차단 (잔존 CSS는 dead).
  // 함정 #11: 이벤트 버블링 충돌 방어 — stopPropagation 후 명시적 expanded 부착 (toggle 아닌 add).
  // REQ-046 — 헤더 배지 → expanded 추가 시도 토글 텍스트 동기 (CSS trick 폐기 정합).
  const _syncToggleText = (card) => {
    if (!card) return;
    const t = card.querySelector('.cal-detail-toggle');
    if (!t) return;
    const txt = t.querySelector('.cal-toggle-text');
    if (txt) txt.textContent = '접기';
    t.setAttribute('aria-label', '접기');
  };
  if (!window._headerBadgeExpandInit) {
    document.addEventListener('click', e => {
      const badge = e.target.closest('.dsn-v95-effect-badge');
      if (!badge) return;
      // "+N" 더보기 배지는 펼침 트리거 X (후속 toolitp 영역)
      if (badge.classList.contains('dsn-v95-effect-badge--more')) return;
      const card = badge.closest('.cal-feature-card');
      if (!card) return;
      e.stopPropagation();
      card.classList.add('expanded');
      _syncToggleText(card);
    });
    // 키보드 a11y — Enter·Space 키
    document.addEventListener('keydown', e => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const badge = e.target.closest && e.target.closest('.dsn-v95-effect-badge');
      if (!badge) return;
      if (badge.classList.contains('dsn-v95-effect-badge--more')) return;
      const card = badge.closest('.cal-feature-card');
      if (!card) return;
      e.preventDefault();
      e.stopPropagation();
      card.classList.add('expanded');
      _syncToggleText(card);
    });
    window._headerBadgeExpandInit = true;
  }

  // cycle22 P1 (2026-05-20) — 미니캔들 클릭 → 카드 하단 확대 차트 expand (SPEC-001 §5 + DSN §3.6.6).
  // .cal-feature-candles20[data-expand-trigger="chart"] click → 카드에 .chart-expanded class + .cal-feature-chart-expanded 슬롯 lazy fill.
  //
  // Phase 2.2 (2026-05-20) — lazy fetch swap:
  // - 1차 fetch `data/dailybars/{code}.json` (240영업일, Phase 3 emit_dailybars_per_stock.py 산출)
  // - fetch 성공 시 240행 dailyData 채택
  // - fetch 실패 (404 / network / parse err) 시 fallback = data-daily20 raw (20영업일, Phase 2 prototype) — graceful degradation
  // - per-stock JSON 부재 (Phase 3 cron 미배포) = 정상 fallback. 콘솔 warn 없음 (정상 흐름).
  // ChartTV.render — js/lib/chart-tv/expanded-chart.js (Phase 7c, TradingView v5 wrapper). 13종 보조지표 + marker primitive + localStorage 영구화.
  // 본 핸들러 = .cal-feature-card.expanded (기존 상세 보기 accordion)와 별개 — chart-expanded class 분리.
  if (!window._chartExpandInit) {
    // 종목별 fetch 결과 메모이즈 (재클릭 시 재 fetch 회피)
    const _dailybarsCache = new Map();
    async function _fetchDailybars(code) {
      if (!code) return null;
      if (_dailybarsCache.has(code)) return _dailybarsCache.get(code);
      try {
        const url = `data/dailybars/${code}.json`;
        const resp = await fetch(url, { credentials: 'omit' });
        if (!resp.ok) {
          _dailybarsCache.set(code, null);
          return null;
        }
        const payload = await resp.json();
        const rows = Array.isArray(payload && payload.rows) ? payload.rows : null;
        if (!rows || rows.length === 0) {
          _dailybarsCache.set(code, null);
          return null;
        }
        // Phase 3 schema {d,o,h,l,c,v,ta} → expanded-chart.js normalize 입력 schema {date,o,h,l,c,v,tv} 정합
        // build_daily prototype {date,o,h,l,c,v,tv} 와 lazy fetch {d,o,h,l,c,v,ta} 양 호환 — d→date / ta→tv alias.
        const normalized = rows.map(r => ({
          date: r.date || r.d || null,
          o: r.o, h: r.h, l: r.l, c: r.c,
          v: typeof r.v === 'number' ? r.v : 0,
          tv: typeof r.tv === 'number' ? r.tv : (typeof r.ta === 'number' ? r.ta : (r.c || 0) * (r.v || 0)),
        }));
        _dailybarsCache.set(code, normalized);
        return normalized;
      } catch (err) {
        _dailybarsCache.set(code, null);
        return null;
      }
    }

    async function _openChartExpand(trigger, card) {
      const isOpen = card.classList.contains('chart-expanded');
      if (isOpen) {
        card.classList.remove('chart-expanded');
        card.setAttribute('aria-expanded', 'false');
        trigger.setAttribute('aria-expanded', 'false');
        return;
      }
      const ticker = card.getAttribute('data-stock-code') || '';
      // 슬롯 lazy 생성 — SPEC-001 v2 §5.2/§5.3 옵션 B 채택 (Phase 5 design-lead 본질 갱신, cluster v21 99회차 critical FLR-001 catch).
      // `.cal-feature-details`는 `.cal-feature-body` 직접 자식 (card 직접 자식 아님). 따라서 `insertBefore(slot, details)` 호출 시 NotFoundError throw.
      // 옵션 B: `card.appendChild(slot)` 단일 분기 — details/hasDetails 분기 자체 제거.
      // selector `:scope >` 명시 — card 직접 자식만 매칭 (body 내부 잘못된 위치 슬롯 검색 회피).
      // cycle23 layout 정정 (2026-05-22 15:56 KST 대표 verbatim "현대 확대용 차트가 상세보기 버튼 아래쪽에 있는데 종목이름과 미니캔들 로우의 바로 아래로 옮기고 싶다"):
      //   slot 위치 본문 = card 마지막 자식 (body sibling) → cal-feature-head 직후 (rangeHtml 위) insert 본질.
      //   `card.appendChild(slot)` → `card.insertBefore(slot, headEl.nextSibling)` 본질 (head 부재 시 graceful appendChild fallback).
      let slot = card.querySelector(':scope > .cal-feature-chart-expanded');
      if (!slot) {
        slot = document.createElement('div');
        slot.className = 'cal-feature-chart-expanded';
        slot.id = `chart-${ticker}`; // SPEC §5.6 MINOR-1 — stable id (aria-controls anchor)
        slot.setAttribute('aria-live', 'polite');
        const headEl = card.querySelector(':scope > .cal-feature-head');
        if (headEl && headEl.nextSibling) {
          card.insertBefore(slot, headEl.nextSibling); // cycle23 layout — head row 바로 아래
        } else if (headEl) {
          card.appendChild(slot); // head 마지막 자식 케이스 fallback
        } else {
          card.appendChild(slot); // head 부재 graceful fallback (SPEC §5.2 옵션 B 원본 동작)
        }
      }
      let exDividendDates = [];
      try {
        const exd = trigger.getAttribute('data-exdividend');
        if (exd) exDividendDates = JSON.parse(exd);
      } catch (err) { /* noop */ }
      // P0 hotfix (cycle22 라이브 배포 보조지표 누락 catch, 대표 2026-05-21 07:37 KST):
      // pinkSignalDates source = data-pinksignal attribute (별건 cycle 본질, 현 시점 빈 배열 graceful).
      // 본질: ChartTV.render options 누락 본질 (Phase 7c integration mismatch — markers attach 호출 시 옵션 omit) 봉쇄.
      let pinkSignalDates = [];
      try {
        const pink = trigger.getAttribute('data-pinksignal');
        if (pink) pinkSignalDates = JSON.parse(pink);
      } catch (err) { /* noop */ }

      // 1차 prototype fallback (20영업일) — 즉시 render (사용자 perceived latency ↓)
      let prototypeData = [];
      try {
        const stash = trigger.getAttribute('data-daily20');
        if (stash) prototypeData = JSON.parse(stash);
      } catch (err) {
        prototypeData = [];
      }
      // accordion 즉시 open + 1차 render (20일) — 사용자 인지 부담 0 ms 정합 (AC-13 <200ms)
      card.classList.add('chart-expanded');
      card.setAttribute('aria-expanded', 'true');
      trigger.setAttribute('aria-expanded', 'true'); // SPEC §5.1/§5.6 — trigger 동기화
      // Phase 7c — ChartExpanded (자체 SVG, git rm) → ChartTV (TradingView v5 wrapper, ESM module) 교체.
      // contract 정합: window.ChartTV.render(slot, dailyArr, { ticker, exDividendDates, pinkSignalDates, ... })
      // ESM module은 async load이므로 ChartTV global 등록 지연 가능 — graceful fallback "로딩 중" 유지.
      // exDividendDates / pinkSignalDates 본질 = marker primitive layer (SPEC §3.4 v6 + §15 verbatim).
      if (window.ChartTV && typeof window.ChartTV.render === 'function') {
        window.ChartTV.render(slot, prototypeData, { ticker, exDividendDates, pinkSignalDates });
      } else {
        slot.innerHTML = '<div class="cal-chart-empty">차트 모듈 로딩 중...</div>';
      }
      requestAnimationFrame(() => {
        const closeBtn = slot.querySelector('.cal-chart-close');
        if (closeBtn) closeBtn.focus();
      });

      // 2차 lazy fetch 240영업일 → 성공 시 swap. 차트가 닫혀있으면 swap skip (race).
      const lazyData = await _fetchDailybars(ticker);
      if (!lazyData || lazyData.length === 0) return; // fallback 유지
      if (!card.classList.contains('chart-expanded')) return; // 닫힘
      if (window.ChartTV && typeof window.ChartTV.render === 'function') {
        window.ChartTV.render(slot, lazyData, { ticker, exDividendDates, pinkSignalDates });
      }
    }

    document.addEventListener('click', e => {
      const trigger = e.target.closest('[data-expand-trigger="chart"]');
      if (!trigger) return;
      const card = trigger.closest('.cal-feature-card');
      if (!card) return;
      e.stopPropagation();
      _openChartExpand(trigger, card);
    });
    document.addEventListener('keydown', e => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const trigger = e.target.closest('[data-expand-trigger="chart"]');
      if (!trigger) return;
      e.preventDefault();
      trigger.click();
    });
    window._chartExpandInit = true;
  }

  // 공유 버튼 이벤트 위임 (1회만 등록)
  if (!window._cardShareInit) {
    document.addEventListener('click', async e => {
      const btn = e.target.closest('.cal-share-btn');
      if (!btn) return;
      e.stopPropagation();
      e.preventDefault();
      const card = btn.closest('.cal-feature-card');
      if (!card) return;
      const code = card.getAttribute('data-stock-code') || '';
      const name = card.getAttribute('data-stock-name') || '';
      const urlParams = new URLSearchParams(window.location.search);
      const dateParam = urlParams.get('date');
      // date 파라미터 없으면 현재 선택된 날짜(전역) 또는 오늘 사용
      const dateStr = dateParam || (typeof calSelectedDate !== 'undefined' ? calSelectedDate : '');
      // 2026-05-27 (대표 결정, 카톡 미리보기 개선): 공유 URL = OG landing 경로
      //   `news/stock/{date}/{code}.html` (generate_stock_og.py 산출, OG 메타 + 미니캔들 PNG).
      //   기존 `?stock={code}&date={date}` query는 OG 메타 부재 → 카톡 미리보기 안 뜸.
      //   landing HTML이 `?stock={code}&date={date}` single-card mode로 JS redirect (Phase 2c-1 정합).
      //   feedback_share_url_ticker_only.md 정합 — URL 경로엔 code 6자리만 (한글 X). 한글은 OG title만.
      //   fallback: date 없으면 OG landing 경로 불가(날짜 디렉토리 필수) → 기존 query URL 유지.
      const shareUrl = (code && dateStr)
        ? `${window.location.origin}/news/stock/${dateStr}/${code}.html`
        : code
          ? `${window.location.origin}/news.html?stock=${code}`
          : (dateStr
            ? `${window.location.origin}/news.html?date=${dateStr}`
            : `${window.location.origin}/news.html`);
      try {
        if (navigator.share && /Mobi|Android|iPhone|iPad/i.test(navigator.userAgent)) {
          // URL만 공유 — 메신저가 title+text+url을 모두 붙여 중복 생기는 이슈 회피
          await navigator.share({ url: shareUrl });
          return;
        }
      } catch (err) {
        // 사용자 취소(AbortError)는 무시, 그 외엔 폴백
        if (err && err.name === 'AbortError') return;
      }
      // 폴백: 클립보드 복사
      try {
        await navigator.clipboard.writeText(shareUrl);
        showShareToast('링크가 복사되었습니다');
      } catch (err) {
        // 최후 폴백: execCommand
        const ta = document.createElement('textarea');
        ta.value = shareUrl;
        ta.setAttribute('readonly', '');
        ta.style.position = 'absolute';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); showShareToast('링크가 복사되었습니다'); }
        catch { showShareToast('복사 실패 — URL: ' + shareUrl); }
        document.body.removeChild(ta);
      }
    });
    window._cardShareInit = true;
  }

  // P0-3 옵션 A anchor scroll (2026-05-21 09:42 KST 대표 catch):
  //   페이지 진입 시 URL hash `#stock-{ticker}` 감지 → 해당 종목카드 scroll.
  //   본 함수는 카드 렌더 종결 시점 → DOM 본질 보장. swap 분기 (cal-content id 임시 변경) 회피.
  //   1회만 실행 (window._stockHashScrolled flag). popstate/onCalCellClick은 별건 path.
  try {
    const _hashRaw = (window.location.hash || '').replace(/^#/, '');
    const _hashMatch = /^stock-(\d{6})$/.exec(_hashRaw);
    if (_hashMatch && !window._stockHashScrolled) {
      const _ticker = _hashMatch[1];
      const _calContent = document.getElementById('cal-content');
      // swap 분기 회피 — id 임시 변경 시 cal-content 부재 → skip
      if (_calContent) {
        const _target = document.getElementById('stock-' + _ticker);
        if (_target) {
          window._stockHashScrolled = true;
          // sticky 헤더 offset 고려 — block: 'center' 사용 시 자연스러운 가시성
          const _prefersReduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
          // 데이터 로드 완료 직후 layout 안정화 대기 (raf 1프레임)
          requestAnimationFrame(() => {
            try {
              _target.scrollIntoView({ behavior: _prefersReduce ? 'auto' : 'smooth', block: 'center' });
              // 시각 강조 — 기존 .card-highlight (news.css L1591) 본문 재사용 (2s glow)
              _target.classList.add('card-highlight');
              setTimeout(() => _target.classList.remove('card-highlight'), 2400);
            } catch (_) { /* graceful */ }
          });
        }
      }
    }
  } catch (_) { /* graceful — hash 부재/jsdom 미지원 시 */ }
}

// 공유 버튼 HTML 생성 (SVG 아이콘 + 접근성 속성)
function renderShareButton(it) {
  if (!it || !it.code) return ''; // code 없으면 딥링크 불가 → 버튼 자체 미노출
  const label = `${it.name || ''} 카드 공유하기`;
  return `<button type="button" class="cal-share-btn" aria-label="${escapeHtml(label)}" title="이 카드 공유하기">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <circle cx="18" cy="5" r="3"/>
      <circle cx="6" cy="12" r="3"/>
      <circle cx="18" cy="19" r="3"/>
      <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/>
      <line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
    </svg>
  </button>`;
}

// 토스트 알림 (aria-live)
function showShareToast(msg) {
  let toast = document.getElementById('share-toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'share-toast';
    toast.className = 'share-toast';
    toast.setAttribute('role', 'status');
    toast.setAttribute('aria-live', 'polite');
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.classList.remove('show');
  // 리플로우 강제하여 재애니메이션
  void toast.offsetWidth;
  toast.classList.add('show');
  clearTimeout(toast._hideTimer);
  toast._hideTimer = setTimeout(() => toast.classList.remove('show'), 3000);
}

// design-theme-tree-time-state-v1 — PRE_MARKET 시점 분기 (Option A, 종목카드 동형).
// 테마트리 + 거래대금 추이 섹션도 거래일 09:00 미만 시 빈 상태 + 카운트다운 + 전일 토글 표시.
// theme-tree.json date=5/8 + nodes=5/7 misleading 봉쇄. (대표 04:45 catch)
function _findPrevTradingIso(iso) {
  try {
    const dt = new Date(iso + 'T00:00:00');
    for (let i = 0; i < 10; i++) {
      dt.setDate(dt.getDate() - 1);
      const y = dt.getFullYear();
      const m = String(dt.getMonth() + 1).padStart(2, '0');
      const dd = String(dt.getDate()).padStart(2, '0');
      const ps = `${y}-${m}-${dd}`;
      if (typeof isMarketClosed === 'function' && !isMarketClosed(ps)) return ps;
    }
  } catch (_) { /* graceful */ }
  return null;
}

let _themeSectionPreMarketTimer = null;
let _themeSectionPreMarketVisHandler = null;
function _stopThemeSectionPreMarketTimer() {
  if (_themeSectionPreMarketTimer) { clearInterval(_themeSectionPreMarketTimer); _themeSectionPreMarketTimer = null; }
  if (_themeSectionPreMarketVisHandler) {
    document.removeEventListener('visibilitychange', _themeSectionPreMarketVisHandler);
    _themeSectionPreMarketVisHandler = null;
  }
}

// container = 빈 상태 영역 root (theme-tree-container 또는 theme-trend),
// headerHtml = 섹션 헤더 (테마트리 / 거래대금 추이 등 호출자 결정),
// onShowPrev = 전일 토글 시 호출 callback (호출자가 실제 데이터 렌더 책임)
function renderPreMarketThemeSection(container, todayIso, prevIso, headerHtml, onShowPrev) {
  if (!container) return;
  _stopThemeSectionPreMarketTimer();
  const prevLabel = prevIso && typeof formatKoDate === 'function' ? formatKoDate(prevIso) : (prevIso || '');
  container.innerHTML = `
    ${headerHtml || ''}
    <div class="cal-pre-market-empty theme-pre-market-empty" role="status" aria-live="polite">
      <svg class="cal-pre-market-icon" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="9"></circle>
        <polyline points="12 7 12 12 15 14"></polyline>
      </svg>
      <div class="cal-pre-market-title">장 시작 전</div>
      <div class="cal-pre-market-sub">09:00에 신규 데이터가 표출됩니다</div>
      <div class="cal-pre-market-countdown" data-cd-theme="1">${_formatCountdownToOpen()}</div>
      ${prevIso ? `<button type="button" class="cal-pre-market-toggle" data-pre-theme-toggle="1" aria-expanded="false">전일(${prevLabel}) 보기 ▾</button>` : ''}
      <div class="cal-pre-market-prev theme-pre-market-prev" data-pre-theme-prev hidden></div>
    </div>
  `;
  const cdEl = container.querySelector('[data-cd-theme]');
  const tick = () => {
    if (!cdEl || !document.body.contains(cdEl)) { _stopThemeSectionPreMarketTimer(); return; }
    cdEl.textContent = _formatCountdownToOpen();
    const nowH = new Date();
    if (nowH.getHours() >= 9 && (typeof getMarketState !== 'function' || getMarketState() !== 'PRE_MARKET')) {
      _stopThemeSectionPreMarketTimer();
      // 09:00 도달 시 호출자가 알아서 다시 init할 수 있도록 reload-light 시그널만
      try { window.dispatchEvent(new CustomEvent('themeSectionPreMarketEnd')); } catch (_) {}
    }
  };
  _themeSectionPreMarketTimer = setInterval(tick, 1000);
  _themeSectionPreMarketVisHandler = () => {
    if (document.hidden) {
      if (_themeSectionPreMarketTimer) { clearInterval(_themeSectionPreMarketTimer); _themeSectionPreMarketTimer = null; }
    } else if (!_themeSectionPreMarketTimer) {
      tick();
      _themeSectionPreMarketTimer = setInterval(tick, 1000);
    }
  };
  document.addEventListener('visibilitychange', _themeSectionPreMarketVisHandler);

  const toggleBtn = container.querySelector('[data-pre-theme-toggle]');
  const prevBox = container.querySelector('[data-pre-theme-prev]');
  if (toggleBtn && prevBox && prevIso && typeof onShowPrev === 'function') {
    toggleBtn.addEventListener('click', async () => {
      const expanded = toggleBtn.getAttribute('aria-expanded') === 'true';
      if (expanded) {
        toggleBtn.setAttribute('aria-expanded', 'false');
        toggleBtn.textContent = `전일(${prevLabel}) 보기 ▾`;
        prevBox.hidden = true;
        prevBox.innerHTML = '';
      } else {
        toggleBtn.setAttribute('aria-expanded', 'true');
        toggleBtn.textContent = `전일(${prevLabel}) 접기 ▴`;
        prevBox.hidden = false;
        prevBox.setAttribute('data-stale', 'true');
        try { await onShowPrev(prevBox, prevIso); }
        catch (e) { prevBox.textContent = '전일 데이터 로드 실패'; }
      }
    });
  }
}

// ───── 테마 거래대금 트렌드 ─────
async function initThemeTrend() {
  try {
    // 대표 catch (5/8 04:58): 거래대금 추이는 트렌드 차트 — 장 개시 여부/휴장 무관 항상 표시.
    // 종전 a3555362(5/8 04:48) PRE_MARKET 분기는 잘못된 적용 → rollback (대표 정합).
    // PRE_MARKET 분기는 일자별 카드성 데이터(테마트리 initThemeTree)에만 유지.
    const res = await fetch('data/themes/theme-trend.json');
    if (!res.ok) return;
    const data = await res.json();
    const container = document.getElementById('theme-trend');
    if (!container || !data.themes || !data.dates) return;

    // 단계 2 (대표 07:17 명령, design-trend-chart-viewport-legend 07:20 명세):
    // VISIBLE_DAYS 분기 — 모바일 7 / 데스크탑 10. isMobile은 L1390 → 여기로 이전 (FIXED_SLOT/VISIBLE_DAYS 정합 우선 계산).
    // REQ-007 5/4 v190 정합: 880px breakpoint (lut-trend 정합).
    const isMobile = window.innerWidth < 880;
    const VISIBLE_DAYS = isMobile ? 7 : 10;
    const allDates = data.dates;
    if (allDates.length < 1) return;
    // 대표 catch (5/8 04:52): theme-trend window = 최근 20영업일 (limit-up-trend 정합).
    // 종전 slice(-17) 결함 (REQ-006 5/4 v195) → slice(-20) 영구 정정.
    let dates = allDates.slice(-20);
    let dateSet = new Set(dates);

    // 대표 명세 (5/8 07:42 재정정 verbatim): "테마트리 최상위 노드가 다 나와서 윈도우에 보이는 애들만 활성화 나머진 비활성화"
    // = legend = 20일 union root 모두 (~33개) 표시 / polyline도 모두 그리기 / viewport 외 = dim (display:none X).
    // 정렬 = 20영업일 누적 trade_amount desc.
    // 종전 cap 12 폐기 (대표 catch — "레전드가 한참 모자라 보이는데"). polyline ↔ legend 1:1.
    const allRoots = (data.themes || []).map(t => ({ ...t, data: (t.data || []).filter(d => dateSet.has(d.date)) }));
    const cumAmtOf = (t) => (t.data || []).reduce((s, d) => s + ((d.stock_count || 0) > 0 ? (d.trade_amount || 0) : 0), 0);
    const unionRoots = allRoots
      .filter(t => t.data.some(d => (d.stock_count || 0) > 0)) // 20영업일 동안 어느 일자라도 활성
      .map(t => ({ ...t, _cumAmt: cumAmtOf(t) }))
      .sort((a, b) => (b._cumAmt || 0) - (a._cumAmt || 0));
    let themes = unionRoots; // cap 폐기 — viewport 활성/비활성 dim 정책으로 가독성 확보
    const legendThemes = unionRoots; // 20영업일 union 전체 (themes와 동일, 1:1)

    // REQ-006 5/4 v196 — themes[0] (trade_amount desc 1순위, 가장 두드러진 polyline) 기준으로
    // firstDataIdx trim. v195의 themes.some() 조건은 너무 느슨해 ti=2/3가 4/9에 데이터 있으면
    // trim 미발동 → polyline ti=0 첫 점 cx ≠ 32. qa-lead 권고 A 채택. (대표 발화 17:44 KST)
    if (themes.length > 0 && dates.length > 0) {
      const firstTheme = themes[0];
      let firstDataIdx = 0;
      for (let i = 0; i < dates.length; i++) {
        if (firstTheme?.data?.some(d => d.date === dates[i] && d.stock_count > 0)) {
          firstDataIdx = i;
          break;
        }
      }
      if (firstDataIdx > 0) {
        dates = dates.slice(firstDataIdx);
        dateSet = new Set(dates);
        themes = themes.map(t => ({ ...t, data: t.data.filter(d => dateSet.has(d.date)) }));
      }
    }
    // lut renderer가 참조할 SSOT 저장 (race-free: theme이 먼저 fetch+render되면 lut가 사용,
    // 미존재 시 lut가 동일 로직으로 fallback 계산)
    window.__chartDates = dates;
    const needsScroll = dates.length > VISIBLE_DAYS;

    if (themes.length === 0) {
      const now = new Date();
      const todayStr = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
      const closedToday = isMarketClosed(todayStr);
      const nextDate = closedToday ? getNextTradingDate(todayStr) : null;
      const nextLabel = nextDate ? formatKoDate(nextDate) : '';
      const emptyMsg = closedToday
        ? `<div style="text-align:center;padding:32px 0;"><div style="font-size:15px;font-weight:700;color:var(--tx2);margin-bottom:6px;">오늘은 장이 쉽니다</div><div style="font-size:12px;color:var(--dm);">${nextLabel ? '다음 거래일 ' + escapeHtml(nextLabel) : ''}</div></div>`
        : '<div class="cal-empty" style="padding:24px 0;">테마 트렌드 데이터가 없습니다</div>';
      container.innerHTML = `
        <div class="theme-trend-header" role="button" tabindex="0" aria-label="테마 트렌드 섹션으로 이동" data-scroll-to-section="theme-trend">
          <div class="theme-trend-title">테마 트렌드</div>
          <div class="theme-trend-sub">최근 거래대금 흐름</div>
        </div>
        ${emptyMsg}`;
      return;
    }

    // COLORS palette = 36색 (33+ 보장, 5/8 07:42 cap 폐기 정합 — viewport union root ~30~33 모두 1:1).
    // 12색 base palette 확장 — 채도/명도 변주로 인접 hue 충돌 회피. dark theme bg(#0E1116)에서 명도 확보.
    const COLORS = [
      '#C49930','#5B8DEF','#E06B6B','#4BC9A0','#A97BDB','#E8963E','#6BB5E0','#D46BAD','#7B9E3D','#E0886B','#6B8FD4','#B86BD4',
      '#F0C674','#7FB3F0','#F08A8A','#7DD9B5','#C49AE5','#F0AD60','#8FCEEB','#E89AC9','#9BBE5C','#F0A88A','#8FA8E0','#CC8FE0',
      '#A87E1F','#3F6FCF','#C04A4A','#2E9E80','#8855B5','#C77518','#4A95C0','#B5478C','#5C7E1F','#C0664A','#4A6FB0','#9B4AB0'
    ];

    // SVG 치수 — 반응형 (모바일 vs 데스크탑)
    // REQ-007 5/4 v190: isMobile breakpoint 640→880 (CSS @media + lut 정합)
    // 단계 2: isMobile은 L1324 직전으로 이전됨 (VISIBLE_DAYS 분기 우선 계산). 여기서 재선언 불가.
    const yAxisW = isMobile ? 36 : 44;
    const H = isMobile ? 180 : 180; // REQ-003: desktop 160→180 (lut-trend 정합, viewBox 비율 정합)
    const PAD = isMobile
      ? { top: 10, right: 8, bottom: 26 }
      : { top: 12, right: 8, bottom: 28 };
    const plotH = H - PAD.top - PAD.bottom;

    // REQ-003 5/4 v185: SLOT pixel 고정 강제 — lut와 chart layout 100% 동일 보장 (chartW = (N-1)*SLOT + 2*EDGE_PAD)
    // 두 chart 같은 SLOT + 같은 EDGE_PAD + 같은 plotW 식 → 같은 방식 렌더링/표시/동작
    const wrapPadding = isMobile ? 28 : 40;
    const measuredW = container.clientWidth || 720;
    const availableW = Math.max(280, measuredW - wrapPadding - yAxisW);
    const baseW = isMobile ? 320 : availableW;
    const FIXED_SLOT = isMobile ? 53 : 80;
    const chartW = needsScroll ? ((dates.length - 1) * FIXED_SLOT + 2 * 32) : baseW;
    const plotW = chartW - PAD.right;

    // 날짜 인덱스 맵
    const dateIdx = {};
    dates.forEach((d, i) => { dateIdx[d] = i; });

    // Y축 최대값
    let yMax = 0;
    themes.forEach(t => t.data.forEach(d => { if (d.trade_amount > yMax) yMax = d.trade_amount; }));
    yMax = yMax * 1.1; // 10% headroom

    // REQ-003 5/4 v184: chart svg 양 끝 32px padding (yAxis 시각 거리 충분 확보, lut와 정합)
    const CHART_EDGE_PAD = 32;
    const plotInnerW = Math.max(1, chartW - 2 * CHART_EDGE_PAD);
    const slot = plotInnerW / Math.max(dates.length - 1, 1);
    function toX(i) { return CHART_EDGE_PAD + i * slot; }
    function toY(v) { return PAD.top + plotH - (v / yMax) * plotH; }
    function fmtTril(v) { return (v / 1e12).toFixed(1) + '조'; }
    function fmtDate(d) { const m = parseInt(d.slice(5, 7), 10); const day = parseInt(d.slice(8, 10), 10); return `${m}/${day}`; } // REQ-004 5/4 v187: lut fmtMD 정합 (5/4 형식, 04/04 → 4/4)

    // Y축 별도 SVG (고정)
    let yAxisSvg = '<svg class="theme-trend-svg" viewBox="0 0 ' + yAxisW + ' ' + H + '" width="' + yAxisW + '" xmlns="http://www.w3.org/2000/svg">';
    const axisFontSize = isMobile ? 9 : 10; // REQ-002: 데스크탑 7→10 (lut-trend 정합)
    for (let i = 0; i <= 2; i++) {
      const v = (yMax / 2) * i;
      const y = toY(v);
      yAxisSvg += '<text x="' + (yAxisW - 4) + '" y="' + (y + 3) + '" text-anchor="end" fill="#64748B" font-size="' + axisFontSize + '">' + fmtTril(v) + '</text>'; // REQ-003: fill 색 lut-trend 정합 (#8B95A8 → #64748B)
    }
    yAxisSvg += '</svg>';

    // 차트 SVG 빌드
    let svg = '<svg class="theme-trend-svg" viewBox="0 0 ' + chartW + ' ' + H + '" width="' + chartW + '" xmlns="http://www.w3.org/2000/svg">';

    // 가로 눈금선 (3개)
    for (let i = 0; i <= 2; i++) {
      const v = (yMax / 2) * i;
      const y = toY(v);
      svg += '<line x1="0" y1="' + y + '" x2="' + chartW + '" y2="' + y + '" stroke="#E8ECF2" stroke-width="0.5"/>';
    }

    // X축 날짜 라벨 — REQ-007 v177: 첫/마지막 anchor 변경 (chart 가장자리 침범 회피)
    const xFontSize = isMobile ? 9 : 10;
    dates.forEach((d, i) => {
      const anchor = i === 0 ? 'start' : (i === dates.length - 1 ? 'end' : 'middle');
      svg += '<text x="' + toX(i) + '" y="' + (H - 4) + '" text-anchor="' + anchor + '" fill="#64748B" font-size="' + xFontSize + '">' + fmtDate(d) + '</text>';
    });

    // 각 테마 polyline + 투명 히트 서클
    themes.forEach((theme, ti) => {
      const color = COLORS[ti % COLORS.length];
      const points = [];
      const dataMap = {};
      theme.data.forEach(d => { dataMap[d.date] = d; });

      dates.forEach((d, i) => {
        if (dataMap[d]) {
          points.push({ x: toX(i), y: toY(dataMap[d].trade_amount), date: d, amount: dataMap[d].trade_amount });
        }
      });

      if (points.length < 1) return;

      if (points.length === 1) {
        svg += '<circle cx="' + points[0].x + '" cy="' + points[0].y + '" r="3" fill="#FFF" stroke="' + color + '" stroke-width="1.5" data-theme="' + escapeHtml(theme.name) + '" data-amount="' + points[0].amount + '" data-date="' + points[0].date + '" data-theme-idx="' + ti + '" data-color="' + color + '" class="tt-hit tt-dot" style="cursor:pointer"/>';
      } else {
        const polyPts = points.map(p => p.x + ',' + p.y).join(' ');
        const strokeW = isMobile ? 2 : 1.2;
        const dotR = isMobile ? 3.5 : 2;
        const hitR = isMobile ? 16 : 12;
        svg += '<polyline points="' + polyPts + '" fill="none" stroke="' + color + '" stroke-width="' + strokeW + '" stroke-linecap="round" stroke-linejoin="round" opacity="0.8" data-theme-idx="' + ti + '"/>';
        points.forEach(p => {
          svg += '<circle cx="' + p.x + '" cy="' + p.y + '" r="' + hitR + '" fill="transparent" stroke="none" data-theme="' + escapeHtml(theme.name) + '" data-amount="' + p.amount + '" data-date="' + p.date + '" data-theme-idx="' + ti + '" data-color="' + color + '" class="tt-hit" style="cursor:pointer"/>';
          svg += '<circle cx="' + p.x + '" cy="' + p.y + '" r="' + dotR + '" fill="#FFF" stroke="' + color + '" stroke-width="1.5" data-theme-idx="' + ti + '" data-color="' + color + '" class="tt-dot"/>';
        });
      }
    });

    // REQ-005-2026-05-04 v183: cover rect 제거 (자연 mask는 .trend-y-axis absolute z-index:2가 담당)
    svg += '</svg>';

    // 레전드 — 대표 명세 (5/8 07:42 verbatim): 33 root 모두 표시. viewport 활성 = 정상, viewport 외 = dim.
    // legend ↔ polyline 1:1 (themes === legendThemes === unionRoots 전체).
    // viewport-inactive 정책: news.css에서 opacity 0.4 + pointer-events none (display:none X — 33개 가시성 유지).
    let legend = '<div class="theme-trend-legend">';
    legendThemes.forEach((t, idx) => {
      legend += '<span class="theme-trend-legend-item" data-legend-idx="' + idx + '"><span class="swatch" style="background:' + COLORS[idx % COLORS.length] + '"></span>' + escapeHtml(t.name) + '</span>';
    });
    legend += '</div>';

    const dateRange = fmtDate(dates[0]) + ' ~ ' + fmtDate(dates[dates.length - 1]);
    container.innerHTML =
      '<div class="theme-trend-header" role="button" tabindex="0" aria-label="테마별 거래대금 추이 섹션으로 이동" data-scroll-to-section="theme-trend"><div class="theme-trend-title">테마별 거래대금 추이</div><div class="theme-trend-sub">최근 ' + dates.length + '영업일 · ' + dateRange + '</div></div>' +
      '<div class="theme-trend-wrap">' +
        '<div class="trend-y-axis">' + yAxisSvg + '</div>' +
        '<div class="trend-scroll-area">' + svg + '</div>' +
        legend +
        '<div id="trend-detail" class="trend-detail"></div>' +
        '<div class="theme-trend-tooltip" id="tt-trend"></div>' +
      '</div>';

    // -- 횡스크롤 초기화 (대표 catch 5/8: trend-fade-left 흰박스 제거, yaxis-col 자연 mask로 충분) --
    const scrollArea = container.querySelector('.trend-scroll-area');
    if (scrollArea && needsScroll) {
      requestAnimationFrame(() => {
        scrollArea.scrollLeft = scrollArea.scrollWidth;
      });
    }

    // -- 레전드 토글 (단일 선택) --
    let selectedIdx = -1; // -1 = 전체 표시
    const legendItems = container.querySelectorAll('.theme-trend-legend-item');
    const svgEl = scrollArea.querySelector('.theme-trend-svg');

    function applyLegendFilter() {
      const none = selectedIdx === -1;
      // SVG 요소 opacity — 비활성 포인트는 완전 숨김 + 클릭 차단
      // 5/8 fix (qa D7/D8): selectedIdx 활성 polyline 강조 (opacity 1 + stroke-width +0.6) / 비활성 0.15
      svgEl.querySelectorAll('[data-theme-idx]').forEach(el => {
        const idx = parseInt(el.dataset.themeIdx);
        const active = none || idx === selectedIdx;
        const isDot = el.classList.contains('tt-dot');
        const isHit = el.classList.contains('tt-hit');
        const isPolyline = el.tagName === 'polyline';
        if (isDot) {
          // 시각 dot (단일 포인트는 tt-hit+tt-dot 동시): 비활성이면 완전 숨김
          el.style.opacity = active ? '' : '0';
          el.style.pointerEvents = active ? '' : 'none';
          if (!isHit) return; // tt-dot 전용이면 여기서 끝
        }
        if (isHit) {
          // 히트 서클: 비활성이면 이벤트 차단
          el.style.pointerEvents = active ? '' : 'none';
          return;
        }
        // polyline: selectedIdx 단일 선택 시 active = 강조(opacity 1), 비active = 0.15. 전체 표시 시 default 복원
        if (isPolyline) {
          if (none) {
            el.style.opacity = '';
            el.removeAttribute('data-selected');
          } else if (active) {
            el.style.opacity = '1';
            el.setAttribute('data-selected', '1');
          } else {
            el.style.opacity = '0.15';
            el.removeAttribute('data-selected');
          }
          return;
        }
        el.style.opacity = active ? '' : '0.1';
      });
      // 레전드 스타일
      legendItems.forEach(li => {
        const idx = parseInt(li.dataset.legendIdx);
        const active = none || idx === selectedIdx;
        li.classList.toggle('selected', idx === selectedIdx);
        li.classList.toggle('dimmed', !none && !active);
      });
    }

    legendItems.forEach(li => {
      li.addEventListener('click', () => {
        const idx = parseInt(li.dataset.legendIdx);
        // 이미 선택된 테마를 다시 클릭하면 전체 표시로 복귀
        selectedIdx = (selectedIdx === idx) ? -1 : idx;
        applyLegendFilter();
        // 수동 선택 변경 시 viewport 필터 재평가 (수동 우선 정책)
        updateViewportLegend();
      });
    });

    // ─── 단계 2: viewport-aware legend sync (대표 07:17 명령, design 07:20 명세) ───
    // §2 viewport idx = round((scrollLeft - 32) / FIXED_SLOT), §3 rAF debounce, §4 polyline opacity 0.08
    // 잠재 결함: selectedIdx !== -1 (수동 선택) 시 viewport 필터 비활성. 수동 우선 정책 (design 권고).
    function computeViewportRange() {
      if (!scrollArea) return { firstIdx: 0, lastIdx: dates.length - 1 };
      const firstIdx = Math.max(0, Math.round((scrollArea.scrollLeft - 32) / FIXED_SLOT));
      const lastIdx = Math.min(dates.length - 1, firstIdx + VISIBLE_DAYS - 1);
      return { firstIdx, lastIdx };
    }
    const legendContainer = container.querySelector('.theme-trend-legend');
    function updateViewportLegend() {
      // 수동 선택 시 viewport 필터 비활성 — applyLegendFilter가 단일 root만 표시 (수동 우선)
      if (selectedIdx !== -1) {
        // viewport-inactive 클래스만 정리. polyline opacity는 applyLegendFilter가 설정한 값(1/0.15) 보존.
        // 5/8 10:02 fix (대표 catch 회귀): 이전 코드 pl.style.opacity = '' 가 applyLegendFilter inline 값을 덮어써서
        // 강조 효과 무력화 → 모든 polyline SVG attribute opacity=0.8 으로 회귀. 본 라인 제거로 selectedIdx 강조 복원.
        legendItems.forEach(li => li.classList.remove('viewport-inactive'));
        legendContainer && legendContainer.querySelector('.theme-trend-legend-empty-hint')?.remove();
        return;
      }
      const { firstIdx, lastIdx } = computeViewportRange();
      const viewportDates = new Set(dates.slice(firstIdx, lastIdx + 1));
      legendItems.forEach(li => {
        const idx = parseInt(li.dataset.legendIdx);
        const theme = themes[idx];
        // §2 옵션 A: viewport 일자 중 어느 하나라도 stock_count > 0 → 활성
        const isActive = !!(theme && theme.data && theme.data.some(d => viewportDates.has(d.date) && (d.stock_count || 0) > 0));
        li.classList.toggle('viewport-inactive', !isActive);
        // §4 viewport-inactive polyline opacity 0.08 (완전 hide X, 컨텍스트 단서)
        const polyline = svgEl.querySelector(`polyline[data-theme-idx="${idx}"]`);
        if (polyline) polyline.style.opacity = isActive ? '' : '0.08';
        // 단일 dot (points.length === 1) — circle.tt-hit.tt-dot 합쳐진 경우도 흐리게
        const singleDot = svgEl.querySelector(`circle.tt-hit.tt-dot[data-theme-idx="${idx}"]`);
        if (singleDot && !polyline) singleDot.style.opacity = isActive ? '' : '0.08';
      });
      // §3 fallback: viewport 활성 root 0개 시 hint
      if (!legendContainer) return;
      const activeCount = legendContainer.querySelectorAll('.theme-trend-legend-item:not(.viewport-inactive)').length;
      const existingHint = legendContainer.querySelector('.theme-trend-legend-empty-hint');
      if (activeCount === 0) {
        if (!existingHint) {
          const hint = document.createElement('span');
          hint.className = 'theme-trend-legend-empty-hint';
          hint.textContent = '이 기간에 활성 테마 없음 ← 좌측 스크롤';
          legendContainer.appendChild(hint);
        }
      } else if (existingHint) {
        existingHint.remove();
      }
    }
    if (scrollArea && needsScroll) {
      scrollArea.addEventListener('scroll', () => {
        requestAnimationFrame(updateViewportLegend);
      }, { passive: true });
    }
    // 초기 진입 1회 (rAF) — 우측 정렬 후 viewport 평가
    requestAnimationFrame(updateViewportLegend);

    // -- 포인트 클릭 → 종목 테이블 --
    const detailDiv = document.getElementById('trend-detail');
    let activePoint = null; // "theme|date" key

    function fmtAmount(v) {
      if (v == null) return '-';
      if (v >= 1e12) return (v / 1e12).toFixed(1) + '조';
      if (v >= 1e8) return (v / 1e8).toFixed(0) + '억';
      if (v >= 1e4) return Math.round(v / 1e4).toLocaleString() + '만';
      return v.toLocaleString();
    }

    function showStockDetail(themeName, dateStr, themeIdx) {
      const key = themeName + '|' + dateStr;
      // 기존 골드 링 제거 + active 해제 (fill #FFF 복원 — 빈 default)
      svgEl.querySelectorAll('.tt-gold-ring').forEach(el => el.remove());
      svgEl.querySelectorAll('.tt-dot.tt-dot--active').forEach(el => {
        el.classList.remove('tt-dot--active');
        el.setAttribute('fill', '#FFF');
      });
      activePoint = key;
      // 테마 데이터에서 stocks 찾기
      const theme = themes[themeIdx];
      if (!theme) return;
      const dayData = theme.data.find(d => d.date === dateStr);
      // 종목코드/종목명 기준 dedup
      const rawStocks = dayData && dayData.stocks ? dayData.stocks : [];
      const seenStockKey = new Set();
      const stocks = rawStocks.filter(s => {
        const key = s.stock_code || s.code || s.name || '';
        if (!key || seenStockKey.has(key)) return false;
        seenStockKey.add(key);
        return true;
      });
      // 골드 링 추가 + 해당 dot active 클래스 부여 (CSS stroke=#FFF + r 확대)
      const hits = svgEl.querySelectorAll('.tt-hit[data-theme="' + themeName.replace(/"/g, '\\"') + '"][data-date="' + dateStr + '"]');
      hits.forEach(h => {
        const cx = h.getAttribute('cx');
        const cy = h.getAttribute('cy');
        const matchDot = svgEl.querySelector('circle.tt-dot[cx="' + cx + '"][cy="' + cy + '"][data-theme-idx="' + themeIdx + '"]');
        if (matchDot) {
          matchDot.classList.add('tt-dot--active');
          matchDot.setAttribute('fill', h.getAttribute('data-color') || '#C49930');
        }
        const ring = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        ring.setAttribute('cx', cx);
        ring.setAttribute('cy', cy);
        ring.setAttribute('r', '5');
        ring.setAttribute('fill', 'none');
        ring.setAttribute('stroke', h.getAttribute('data-color') || '#C49930');
        ring.setAttribute('stroke-width', '2');
        ring.classList.add('tt-gold-ring');
        svgEl.appendChild(ring);
      });
      // 테이블 렌더
      const chipDate = dateStr.slice(5).replace('-', '/');
      let html = '<div class="trend-detail-chip">' + chipDate + ' &middot; ' + escapeHtml(themeName) + '</div>';
      if (stocks.length === 0) {
        html += '<div style="font-size:12px;color:var(--dm);padding:8px 0;">종목 데이터가 없습니다</div>';
      } else {
        html += '<table class="trend-detail-table"><thead><tr><th class="th-name">종목명</th><th class="th-price">종가</th><th class="th-pct">등락률</th><th class="th-candle"></th><th class="th-amount">거래대금</th></tr></thead><tbody>';
        stocks.forEach(s => {
          const pctClass = s.change_pct > 0 ? '#E03131' : s.change_pct < 0 ? '#1971C2' : 'var(--tx)';
          const pctStr = (s.change_pct > 0 ? '+' : '') + s.change_pct.toFixed(2) + '%';
          // 종목명 (anchor click 폐기 — 대표 결정 2026-04-30, 텍스트만 노출)
          const nameCell = escapeHtml(s.name);
          html += '<tr><td class="td-name">' + nameCell + '</td><td class="td-price">' + (s.price ? s.price.toLocaleString() : '-') + '</td><td class="td-pct" style="color:' + pctClass + ';font-weight:600">' + pctStr + '</td><td class="td-candle">' + miniCandle(s.open_price, s.high_price, s.low_price, s.price, s.change_pct) + '</td><td class="td-amount">' + fmtAmount(s.trade_amount) + '</td></tr>';
        });
        html += '</tbody></table>';
      }
      detailDiv.innerHTML = html;
      // 트랜지션
      detailDiv.classList.remove('open');
      requestAnimationFrame(() => { detailDiv.classList.add('open'); });
    }

    // -- 툴팁 + 클릭 --
    const tooltip = document.getElementById('tt-trend');
    const wrap = container.querySelector('.theme-trend-wrap');

    if (!isMobile) {
      wrap.addEventListener('mousemove', function(e) {
        const hit = e.target.closest('.tt-hit');
        if (!hit) { tooltip.classList.remove('show'); return; }
        // 비활성 테마 포인트는 툴팁 표시 안 함
        const hitIdx = parseInt(hit.dataset.themeIdx);
        if (selectedIdx !== -1 && hitIdx !== selectedIdx) { tooltip.classList.remove('show'); return; }
        const name = hit.dataset.theme;
        const amount = Number(hit.dataset.amount);
        tooltip.textContent = name + ' ' + fmtTril(amount);
        tooltip.classList.add('show');
        const wrapRect = wrap.getBoundingClientRect();
        let left = e.clientX - wrapRect.left + 12;
        const ttWidth = tooltip.offsetWidth || 120;
        if (left + ttWidth > wrapRect.width) left = e.clientX - wrapRect.left - ttWidth - 12;
        tooltip.style.left = left + 'px';
        tooltip.style.top = (e.clientY - wrapRect.top - 28) + 'px';
      });
      wrap.addEventListener('mouseleave', function() { tooltip.classList.remove('show'); });
    }

    wrap.addEventListener('click', function(e) {
      // 정정 #12 (대표 18:30): trend-stock-link anchor 클릭은 wrap handler가 가로채면 안 됨.
      // outside-click logic으로 detail 닫히고 navigation 직전 DOM 변경 → anchor 동작 깨짐.
      if (e.target.closest('.trend-stock-link, a[href]')) return;
      const hit = e.target.closest('.tt-hit');
      if (!hit) {
        // 포인트 외 클릭 → 선택 해제 (fill #FFF 복원)
        svgEl.querySelectorAll('.tt-gold-ring').forEach(el => el.remove());
        svgEl.querySelectorAll('.tt-dot.tt-dot--active').forEach(el => {
          el.classList.remove('tt-dot--active');
          el.setAttribute('fill', '#FFF');
        });
        activePoint = null;
        detailDiv.classList.remove('open');
        detailDiv.innerHTML = '';
        return;
      }
      tooltip.classList.remove('show');
      const themeName = hit.dataset.theme;
      const dateStr = hit.dataset.date;
      const themeIdx = parseInt(hit.dataset.themeIdx);
      // 레전드 필터 활성 시, 비선택 테마 클릭 무시
      if (selectedIdx !== -1 && selectedIdx !== themeIdx) return;
      showStockDetail(themeName, dateStr, themeIdx);
    });

  } catch (e) { console.warn('theme-trend:', e); }
}

// ───── REQ-pm320-ux-cycle #2 — 상한가 종목 추이 (theme-trend 직하) ─────
async function initLimitUpTrend() {
  try {
    const res = await fetch('data/limit-up-trend.json');
    if (!res.ok) return;
    const data = await res.json();
    const container = document.getElementById('limit-up-trend');
    if (!container || !Array.isArray(data.items) || data.items.length === 0) return;

    // 6영업일 윈도우 + 가로 스크롤 (theme-trend SoT 정합)
    const VISIBLE_DAYS = 6;
    // REQ-006 5/4 v195: theme renderer가 trim한 windowDates(window.__chartDates) 우선 사용.
    // 두 차트의 dates[0] 동일 + 첫 dot/line cx 동일(=32) 보장. (대표 발화 17:27 KST)
    let windowDates = Array.isArray(window.__chartDates) && window.__chartDates.length > 0
      ? window.__chartDates.slice()
      : null;
    if (!windowDates) {
      // theme renderer 미동작/지연 시 fallback — 동일 trim 로직 직접 실행
      try {
        const themeRes = await fetch('data/themes/theme-trend.json');
        if (themeRes.ok) {
          const themeData = await themeRes.json();
          if (Array.isArray(themeData.dates) && themeData.dates.length > 0) {
            // 대표 catch (5/8 04:58): theme-trend과 정합 — 20영업일 (종전 17은 잔존 결함)
            let tDates = themeData.dates.slice(-20);
            const tDateSet = new Set(tDates);
            // theme renderer와 동일하게 trade_amount desc 정렬 후 [0] 기준으로 trim (v196)
            const tThemes = (themeData.themes || [])
              .map(t => ({ ...t, data: (t.data || []).filter(d => tDateSet.has(d.date)) }))
              .filter(t => t.data.some(d => d.stock_count > 0))
              .sort((a, b) => {
                const aLast = a.data[a.data.length - 1]?.trade_amount || 0;
                const bLast = b.data[b.data.length - 1]?.trade_amount || 0;
                return bLast - aLast;
              });
            if (tThemes.length > 0) {
              const tFirst = tThemes[0];
              let firstIdx = 0;
              for (let i = 0; i < tDates.length; i++) {
                if (tFirst?.data?.some(d => d.date === tDates[i] && d.stock_count > 0)) {
                  firstIdx = i; break;
                }
              }
              if (firstIdx > 0) tDates = tDates.slice(firstIdx);
            }
            windowDates = tDates;
          }
        }
      } catch (_) { /* fallback below */ }
    }
    if (!windowDates) {
      // theme-trend.json fetch 실패 시 최종 fallback — lut 자체 items
      // 대표 catch (5/8 04:58): theme-trend 정합 — 20영업일
      windowDates = data.items.slice(-20).map(it => it.date);
    }
    const itemMap = new Map(data.items.map(it => [it.date, it]));
    const items = windowDates.map(d => itemMap.get(d) || { date: d, count: 0 });
    const dates = items.map(it => it.date);
    const counts = items.map(it => it.count);
    const maxCount = Math.max(1, ...counts);
    const needsScroll = dates.length > VISIBLE_DAYS;
    // Y-axis ticks (auto-scale 정수)
    const yMax = Math.max(5, Math.ceil(maxCount / 5) * 5);
    const yTicks = [];
    for (let v = 0; v <= yMax; v += Math.max(1, Math.ceil(yMax / 5))) yTicks.push(v);

    // REQ-007 5/4 v190: lut isMobile breakpoint 640→880 (theme + CSS @media 정합)
    const isMobile = window.innerWidth < 880;
    const containerW = container.clientWidth || 800;
    const wrapPadding = isMobile ? 28 : 40;
    const yAxisW = isMobile ? 36 : 44;
    const innerW = Math.max(280, containerW - wrapPadding - yAxisW);
    const baseW = innerW;
    const FIXED_SLOT = isMobile ? 53 : 80;
    const chartW = needsScroll ? ((items.length - 1) * FIXED_SLOT + 2 * 32) : baseW;
    const slot = FIXED_SLOT;
    const H = isMobile ? 140 : 180;
    const padTop = 12, padBottom = 28;
    const plotH = H - padTop - padBottom;
    const yScale = v => padTop + plotH * (1 - v / yMax);

    const fmtMD = (d) => {
      const m = parseInt(d.slice(5, 7), 10);
      const day = parseInt(d.slice(8, 10), 10);
      return `${m}/${day}`;
    };

    // Y axis SVG (sticky)
    let yAxisSvg = '<svg class="lut-svg lut-yaxis" viewBox="0 0 ' + yAxisW + ' ' + H + '" width="' + yAxisW + '" height="' + H + '" xmlns="http://www.w3.org/2000/svg">';
    for (const v of yTicks) {
      const y = yScale(v).toFixed(1);
      yAxisSvg += '<line x1="' + (yAxisW - 4) + '" y1="' + y + '" x2="' + yAxisW + '" y2="' + y + '" stroke="#CBD5E1" stroke-width="0.5"/>';
      yAxisSvg += '<text x="' + (yAxisW - 6) + '" y="' + y + '" font-size="' + (isMobile ? 9 : 10) + '" fill="#64748B" text-anchor="end" dominant-baseline="middle">' + v + '</text>';
    }
    yAxisSvg += '</svg>';

    // Chart SVG (라인+포인트 — design-lead 명세)
    let chartSvg = '<svg class="lut-svg lut-chart" viewBox="0 0 ' + chartW + ' ' + H + '" width="' + chartW + '" height="' + H + '" xmlns="http://www.w3.org/2000/svg">';
    // 영역 그라디언트 정의
    chartSvg += '<defs><linearGradient id="lutAreaGrad" x1="0" y1="0" x2="0" y2="1">';
    chartSvg += '<stop offset="0%" stop-color="#C49930" stop-opacity="0.18"/>';
    chartSvg += '<stop offset="100%" stop-color="#C49930" stop-opacity="0"/>';
    chartSvg += '</linearGradient></defs>';
    // gridlines
    for (const v of yTicks) {
      const y = yScale(v).toFixed(1);
      chartSvg += '<line x1="0" y1="' + y + '" x2="' + chartW + '" y2="' + y + '" stroke="#E5E7EB" stroke-width="0.5" stroke-dasharray="2,3"/>';
    }
    // 좌표 사전 계산 (line, area 공유)
    const baseline = padTop + plotH;
    // REQ-003 5/4 v184: chart svg 양 끝 32px padding (theme 정합)
    const LUT_EDGE_PAD = 32;
    const lutInnerW = Math.max(1, chartW - 2 * LUT_EDGE_PAD);
    const lutSlot = lutInnerW / Math.max(items.length - 1, 1);
    const pts = items.map((it, i) => {
      const cx = LUT_EDGE_PAD + i * lutSlot;
      const cy = yScale(it.count);
      return { cx, cy, it };
    });
    // 영역 path
    if (pts.length >= 2) {
      let areaD = 'M ' + pts[0].cx.toFixed(1) + ' ' + baseline.toFixed(1);
      for (const p of pts) areaD += ' L ' + p.cx.toFixed(1) + ' ' + p.cy.toFixed(1);
      areaD += ' L ' + pts[pts.length - 1].cx.toFixed(1) + ' ' + baseline.toFixed(1) + ' Z';
      chartSvg += '<path class="lut-area" d="' + areaD + '" fill="url(#lutAreaGrad)"/>';
    }
    // 라인 path
    if (pts.length >= 2) {
      let lineD = 'M ' + pts[0].cx.toFixed(1) + ' ' + pts[0].cy.toFixed(1);
      for (let i = 1; i < pts.length; i++) lineD += ' L ' + pts[i].cx.toFixed(1) + ' ' + pts[i].cy.toFixed(1);
      chartSvg += '<path class="lut-line" d="' + lineD + '" stroke="var(--am, #C49930)" stroke-width="2" fill="none" stroke-linejoin="round" stroke-linecap="round"/>';
    }
    // dot + hit-area + label — theme-trend SoT 정합 (r=3.5 mobile / 2 desktop, active 시 fill=color + 골드 링)
    // REQ-006 5/4 v192: lutIsMobile breakpoint 640→880 — theme isMobile + 차트 layout 전체와 정합
    // (640~879 구간에서 theme dot 3.5 / lut dot 2 비대칭 잔존하던 회귀 fix)
    const lutIsMobile = window.innerWidth < 880;
    const lutDotR = lutIsMobile ? 3.5 : 2;
    const lutDotActiveR = lutIsMobile ? 5 : 5; // 골드 링 반경 (theme-trend SoT)
    items.forEach((it, i) => {
      const cx = LUT_EDGE_PAD + i * lutSlot; // REQ-008 v178: edge padding 20
      const cy = yScale(it.count);
      const isZero = it.count === 0;
      const dotCls = isZero ? 'lut-dot lut-dot-zero' : 'lut-dot';
      const stroke = isZero ? '#CBD5E1' : 'var(--am, #C49930)';
      chartSvg += '<rect class="lut-dot-hit" data-date="' + it.date + '" x="' + Math.max(0, cx - lutSlot / 2).toFixed(1) + '" y="0" width="' + lutSlot.toFixed(1) + '" height="' + plotH + '" fill="transparent"/>';
      chartSvg += '<circle class="' + dotCls + '" data-date="' + it.date + '" cx="' + cx.toFixed(1) + '" cy="' + cy.toFixed(1) + '" r="' + lutDotR + '" fill="#FFF" stroke="' + stroke + '" stroke-width="1.5" role="button" tabindex="0" aria-label="' + it.date + ' 상한가 ' + it.count + '건"><title>' + it.date + '\n상한가 ' + it.count + '건</title></circle>';
      // X-axis label — REQ-007 v177: 첫/마지막 anchor 변경 (chart 가장자리 침범 회피)
      const lutAnchor = i === 0 ? 'start' : (i === items.length - 1 ? 'end' : 'middle');
      chartSvg += '<text x="' + cx.toFixed(1) + '" y="' + (baseline + 14) + '" font-size="' + (isMobile ? 9 : 10) + '" fill="#64748B" text-anchor="' + lutAnchor + '">' + fmtMD(it.date) + '</text>';
    });
    // REQ-005-2026-05-04 v183: cover rect 제거 (lut-yaxis-col을 theme-trend 패턴 absolute z-index:2 자연 mask 통일)
    chartSvg += '</svg>';

    const dateRange = dates.length > 1 ? (fmtMD(dates[0]) + '~' + fmtMD(dates[dates.length - 1])) : fmtMD(dates[0]);
    container.innerHTML =
      '<div class="lut-header" role="button" tabindex="0" aria-label="상한가 종목 추이 섹션으로 이동" data-scroll-to-section="limit-up-trend"><div class="lut-title">상한가 종목 추이</div>' +
      '<div class="lut-sub">최근 ' + dates.length + '영업일 · ' + dateRange + ' · 총 ' + (data.total_count || 0) + '건</div></div>' +
      '<div class="lut-wrap">' +
        '<div class="lut-yaxis-col">' + yAxisSvg + '</div>' +
        '<div class="lut-scroll">' + chartSvg + '</div>' +
      '</div>' +
      '<div class="lut-detail" id="lut-detail" hidden></div>';

    // 횡스크롤 초기화 — 최신일자가 우측 끝, 초기 진입 시 우측 정렬 (theme-trend SoT)
    const lutScroll = container.querySelector('.lut-scroll');
    if (lutScroll && needsScroll) {
      requestAnimationFrame(() => {
        lutScroll.scrollLeft = lutScroll.scrollWidth;
      });
    }

    // Inline expand on dot click/keydown
    const detail = container.querySelector('#lut-detail');
    const chartSvgEl = container.querySelector('.lut-chart');
    let activeDate = null;
    const clearActive = () => {
      container.querySelectorAll('.lut-dot.lut-dot--active').forEach(b => {
        b.classList.remove('lut-dot--active');
        b.setAttribute('fill', '#FFF');
      });
      if (chartSvgEl) chartSvgEl.querySelectorAll('.lut-gold-ring').forEach(el => el.remove());
    };
    const closeDetail = () => {
      detail.hidden = true;
      detail.innerHTML = '';
      activeDate = null;
      clearActive();
    };
    const openDetail = (date) => {
      const it = items.find(x => x.date === date);
      if (!it || it.count === 0) return;
      if (activeDate === date) { closeDetail(); return; }
      activeDate = date;
      clearActive();
      const dot = container.querySelector('.lut-dot[data-date="' + date + '"]');
      if (dot && chartSvgEl) {
        dot.classList.add('lut-dot--active');
        // SVG fill attr이 CSS보다 우선이므로 JS로 직접 설정 (active 채움)
        dot.setAttribute('fill', '#C49930');
        // 골드 링 추가 — theme-trend SoT (.tt-gold-ring r=5)
        const cx = dot.getAttribute('cx');
        const cy = dot.getAttribute('cy');
        const ring = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        ring.setAttribute('cx', cx);
        ring.setAttribute('cy', cy);
        ring.setAttribute('r', String(lutDotActiveR));
        ring.setAttribute('fill', 'none');
        ring.setAttribute('stroke', '#C49930');
        ring.setAttribute('stroke-width', '2');
        ring.classList.add('lut-gold-ring');
        chartSvgEl.appendChild(ring);
      }
      const fmtPct = v => v == null ? '' : (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
      const fmtAmt = v => {
        if (v == null) return '';
        const eok = v / 1e8;
        if (eok >= 10000) return (eok / 10000).toFixed(1) + '조';
        if (eok >= 1) return Math.round(eok).toLocaleString() + '억';
        return v.toLocaleString();
      };
      detail.hidden = false;
      // 거래대금 추이 종목 list 완전 복제 — 타이틀 chip + 5컬럼 (종목명+연속칩 | 종가 | 미니캔들 | 등락률 | 거래대금)
      // 타이틀 박스 = .trend-detail-chip (theme-trend SoT) — 황금 pill, 11px 700w, var(--am4) bg
      const chipDate = it.date.slice(5).replace('-', '/');
      let html = '<div class="trend-detail-chip">' + chipDate + ' &middot; 상한가 ' + it.count + '건</div>';
      html += '<table class="trend-detail-table lut-detail-table"><thead><tr><th class="th-name">종목명</th><th class="th-price">종가</th><th class="th-pct">등락률</th><th class="th-candle"></th><th class="th-amount">거래대금</th></tr></thead><tbody>';
      // 거래대금 역순(DESC) 정렬
      const sortedStocks = it.stocks.slice().sort((a, b) => (b.trade_amount || 0) - (a.trade_amount || 0));
      sortedStocks.forEach(s => {
        // "+N" → "연속+N"
        const cc = s.consecutive_count >= 2 ? '<span class="lut-streak">연속+' + s.consecutive_count + '</span>' : '';
        // 종목명 (anchor click 폐기 — 대표 결정 2026-04-30, 텍스트만 노출)
        const nameLink = escapeHtml(s.name || s.code || '');
        const pctClass = s.change_pct > 0 ? '#E03131' : s.change_pct < 0 ? '#1971C2' : 'var(--tx)';
        const candleHtml = miniCandle(s.open_price, s.high_price, s.low_price, s.price, s.change_pct);
        html += '<tr>' +
          '<td class="td-name"><span class="lut-stock-main">' + nameLink + cc + '</span></td>' +
          '<td class="td-price">' + (s.price != null ? s.price.toLocaleString() : '-') + '</td>' +
          '<td class="td-pct" style="color:' + pctClass + ';font-weight:600">' + fmtPct(s.change_pct) + '</td>' +
          '<td class="td-candle">' + candleHtml + '</td>' +
          '<td class="td-amount">' + fmtAmt(s.trade_amount) + '</td>' +
        '</tr>';
      });
      html += '</tbody></table>';
      detail.innerHTML = html;
    };
    container.addEventListener('click', e => {
      const target = e.target.closest('.lut-dot, .lut-dot-hit');
      if (!target) return;
      openDetail(target.getAttribute('data-date'));
    });
    container.addEventListener('keydown', e => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const dot = e.target.closest('.lut-dot');
      if (!dot) return;
      e.preventDefault();
      openDetail(dot.getAttribute('data-date'));
    });
  } catch (e) { console.warn('limit-up-trend:', e); }
}

// ───── 테마 지도 ─────
async function initThemeMap() {
  try {
    const res = await fetch('data/themes/theme-map.json');
    if (!res.ok) return;
    const data = await res.json();
    const grid = document.getElementById('theme-map-grid');
    const expand = document.getElementById('theme-map-expand');
    if (!grid || !data.themes) return;

    // 종목 2개 이상 테마만 표시
    const themes = data.themes.filter(t => t.stock_count >= 2);
    if (themes.length === 0) return;

    let activeTheme = null;

    grid.innerHTML = themes.map(t =>
      `<span class="theme-map-chip" data-theme-id="${t.id}">${escapeHtml(t.name)}<span class="chip-count">${t.stock_count}</span></span>`
    ).join('');

    grid.addEventListener('click', (e) => {
      const chip = e.target.closest('.theme-map-chip');
      if (!chip) return;
      const tid = parseInt(chip.dataset.themeId);
      const theme = themes.find(t => t.id === tid);
      if (!theme) return;

      // 토글
      if (activeTheme === tid) {
        activeTheme = null;
        expand.classList.remove('show');
        chip.classList.remove('active');
        return;
      }

      // 이전 active 해제
      grid.querySelectorAll('.active').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      activeTheme = tid;

      // 확장 패널
      const stocksHtml = theme.stocks.slice(0, 10).map(s =>
        `<div class="theme-map-stock">
          <span class="theme-map-stock-name">${escapeHtml(s.name)}</span>
          <span class="theme-map-stock-industry">${escapeHtml(s.industry || '')}</span>
        </div>`
      ).join('');

      expand.innerHTML = `
        <div class="theme-map-expand-title">${escapeHtml(theme.name)} — ${theme.stock_count}종목</div>
        ${stocksHtml}
      `;
      expand.classList.add('show');
    });
  } catch (e) { console.warn('theme-map:', e); }
}

// ───── 테마 트리 (Indented Tree + Inline Bar) ─────
async function initThemeTree(dateOverride) {
  try {
    // 휴장일이면 안내 메시지 표시 후 종료 (테마 트리는 거래일 데이터 기반)
    if (dateOverride && isMarketClosed(dateOverride)) {
      const tc = document.getElementById('theme-tree-container');
      if (tc) {
        const nextDate = getNextTradingDate(dateOverride);
        const nextLabel = nextDate ? formatKoDate(nextDate) : '';
        tc.innerHTML = `<div style="text-align:center;padding:32px 0;"><div style="font-size:15px;font-weight:700;color:var(--tx2);margin-bottom:6px;">오늘은 장이 쉽니다</div><div style="font-size:12px;color:var(--dm);">${nextLabel ? '다음 거래일 ' + escapeHtml(nextLabel) : ''}</div></div>`;
      }
      return;
    }
    // design-theme-tree-time-state-v1 — PRE_MARKET 시점 분기 (catch).
    // theme-tree.json date(예 5/8) + nodes(5/7) misleading 차단. 종목카드 동형.
    try {
      const _now = new Date();
      const _todayIso = `${_now.getFullYear()}-${String(_now.getMonth()+1).padStart(2,'0')}-${String(_now.getDate()).padStart(2,'0')}`;
      const _state = (typeof getMarketState === 'function') ? getMarketState(dateOverride || _todayIso) : null;
      const _isToday = !dateOverride || dateOverride === _todayIso;
      if (_state === 'PRE_MARKET' && _isToday && !window.__themeTreeBypassPreMarket) {
        const tc = document.getElementById('theme-tree-container');
        if (tc) {
          const _prev = _findPrevTradingIso(_todayIso);
          // 정적 헤더(news.html .theme-tree-header) 신뢰 — 동적 _hdr 추가 시 중복 (대표 catch 2026-05-08 06:06)
          renderPreMarketThemeSection(tc, _todayIso, _prev, '', async (prevBox, prevIso) => {
            // 전일 테마트리 토글 — bypass 플래그 + 전일 dateOverride로 재진입
            window.__themeTreeBypassPreMarket = true;
            try {
              const tmp = document.createElement('div');
              const orig = document.getElementById('theme-tree-container');
              const origId = orig ? orig.id : null;
              if (orig) orig.id = '_theme-tree-container-saved';
              tmp.id = 'theme-tree-container';
              document.body.appendChild(tmp);
              try {
                await initThemeTree(prevIso);
                prevBox.innerHTML = tmp.innerHTML;
              } finally {
                tmp.remove();
                if (orig && origId) orig.id = origId;
                window.__themeTreeBypassPreMarket = false;
              }
            } catch (e) { prevBox.textContent = '전일 테마트리 로드 실패'; window.__themeTreeBypassPreMarket = false; }
          });
        }
        return;
      }
    } catch (_) { /* getMarketState 미정의 시 graceful */ }
    // theme-tree.json 캐시 (최초 1회만 fetch)
    if (!_themeTreeCache) {
      const res = await fetch('data/themes/theme-tree.json');
      if (!res.ok) return;
      _themeTreeCache = await res.json();
    }
    const data = JSON.parse(JSON.stringify(_themeTreeCache)); // deep copy
    if (!data.nodes || data.nodes.length === 0) {
      const tc = document.getElementById('theme-tree-container');
      if (tc) {
        const _n2 = new Date();
        const _t2 = `${_n2.getFullYear()}-${String(_n2.getMonth()+1).padStart(2,'0')}-${String(_n2.getDate()).padStart(2,'0')}`;
        const isLive = (dateOverride === _t2 || !dateOverride) && _n2.getHours() < 16 && !isMarketClosed(_t2);
        tc.innerHTML = `<div class="cal-empty" style="padding:24px 0;">${isLive ? '테마 데이터가 없습니다' : '테마 데이터가 없습니다'}</div>`;
      }
      return;
    }

    // 날짜 지정 시: 해당 날짜의 stock JSON에서 테마 필터링
    const targetDate = dateOverride || data.date;
    if (dateOverride) {
      try {
        // REQ-055 P0 — 빈 stocks=[] 파일도 200 OK로 반환되므로 stocks 비어있으면 7일 이내 fallback.
        //   이 가드 없이는 4/28 같은 신규 거래일 새벽에 theme tree가 "테마 데이터가 없습니다"로 빈 표시되는 결함 발생.
        async function _loadStockJsonWithFallback(d0) {
          // REQ-055 P0 — toISOString()는 KST→UTC 변환되어 하루 전 날짜를 반환하는 버그.
          //   날짜 산술은 로컬 getFullYear/getMonth/getDate 사용.
          const _localYmd = (dt) => {
            const y = dt.getFullYear();
            const m = String(dt.getMonth() + 1).padStart(2, '0');
            const dd = String(dt.getDate()).padStart(2, '0');
            return `${y}-${m}-${dd}`;
          };
          // DSN-frontend §3.6.2.2 (2026-05-28) — 오늘 view + 09:00 이후 시 7일 fallback 차단.
          //   기존 동작 (어제 데이터 자동 호출) → 사용자 매매 판단 misread risk.
          //   테마트리는 종목카드와 동일 정책 cumulative — '테마 데이터가 없습니다' 표시 default.
          const _nowLocal = new Date();
          const _todayLocal = _localYmd(_nowLocal);
          const _isTodayPastOpenLocal = (d0 === _todayLocal && _nowLocal.getHours() >= 9);
          const tryDate = async (d) => {
            try {
              const r = await fetch(`data/interpreted/stock-${d}.json`);
              if (!r.ok) return null;
              const j = await r.json();
              return (j && Array.isArray(j.stocks) && j.stocks.length > 0) ? j : null;
            } catch { return null; }
          };
          let j = await tryDate(d0);
          if (j) return j;
          if (_isTodayPastOpenLocal) return null; // 본 fallback 차단
          const dt = new Date(d0 + 'T00:00:00');
          for (let i = 1; i <= 7; i++) {
            const prev = new Date(dt);
            prev.setDate(prev.getDate() - i);
            const ps = _localYmd(prev);
            j = await tryDate(ps);
            if (j) return j;
          }
          return null;
        }
        const stockData = await _loadStockJsonWithFallback(dateOverride);
        if (stockData) {
          // 해당 날짜 종목들의 테마 이름 수집
          const activeThemes = new Set();
          const themeStocks = {}; // theme_name -> [{code, name, change_pct, trade_amount}]
          for (const s of (stockData.stocks || [])) {
            for (const t of (s.themes || [])) {
              const tName = typeof t === 'string' ? t : t.name;
              activeThemes.add(tName);
              if (!themeStocks[tName]) themeStocks[tName] = [];
              themeStocks[tName].push({
                code: s.code, name: s.name,
                change_pct: s.change_pct || 0,
                trade_amount: s.trade_amount || 0
              });
            }
          }
          // 해당 날짜 테마가 있는 노드만 유지 + 종목 교체
          const nodeById = {};
          data.nodes.forEach(n => { nodeById[n.id] = n; });
          // 활성 노드 ID 수집 (이름 매칭)
          const activeIds = new Set();
          data.nodes.forEach(n => {
            if (activeThemes.has(n.name)) {
              activeIds.add(n.id);
              // 종목 정보 교체
              n.stocks = (themeStocks[n.name] || []);
              n.stock_count = n.stocks.length;
              n.total_stock_count = n.stock_count;
              n.trade_amount = n.stocks.reduce((s, x) => s + (x.trade_amount || 0), 0);
            }
          });
          // 조상 노드도 유지 (트리 연결용)
          data.nodes.forEach(n => {
            if (activeIds.has(n.id)) {
              let pid = n.parent_id;
              while (pid && nodeById[pid] && !activeIds.has(pid)) {
                activeIds.add(pid);
                pid = nodeById[pid].parent_id;
              }
            }
          });
          // 조상-전용 노드의 stocks도 해당 날짜 데이터로 교체
          data.nodes.forEach(n => {
            if (activeIds.has(n.id) && !activeThemes.has(n.name)) {
              n.stocks = (themeStocks[n.name] || []);
              n.stock_count = n.stocks.length;
              n.total_stock_count = n.stock_count;
              n.trade_amount = n.stocks.reduce((s, x) => s + (x.trade_amount || 0), 0);
            }
          });
          // 활성 노드만 필터
          data.nodes = data.nodes.filter(n => activeIds.has(n.id));
          // 부모-자식 종목 중복 제거: 모든 자손에 있는 종목은 부모에서 제외
          const nodeByIdD = {};
          const childrenMapD = {};
          data.nodes.forEach(n => { nodeByIdD[n.id] = n; });
          data.nodes.forEach(n => {
            if (n.parent_id) {
              if (!childrenMapD[n.parent_id]) childrenMapD[n.parent_id] = [];
              childrenMapD[n.parent_id].push(n.id);
            }
          });
          function collectDescendantCodes(nid) {
            const codes = new Set();
            (childrenMapD[nid] || []).forEach(cid => {
              const child = nodeByIdD[cid];
              if (child && child.stocks) child.stocks.forEach(s => codes.add(s.code));
              collectDescendantCodes(cid).forEach(c => codes.add(c));
            });
            return codes;
          }
          data.nodes.forEach(n => {
            const descCodes = collectDescendantCodes(n.id);
            // descendant_stock_count: 자신 + 모든 자손의 고유 종목 수
            const ownCodes = new Set((n.stocks || []).map(s => s.code));
            const allCodes = new Set([...ownCodes, ...descCodes]);
            n.descendant_stock_count = allCodes.size;
            if (descCodes.size > 0 && n.stocks) {
              n.stocks = n.stocks.filter(s => !descCodes.has(s.code));
              n.stock_count = n.stocks.length;
              n.trade_amount = n.stocks.reduce((sum, s) => sum + (s.trade_amount || 0), 0);
            }
          });
        }
      } catch (e) { /* stock JSON 없으면 기본 트리 사용 */ }
    }

    // 필터링 후 노드가 없으면 빈 상태 표시
    if (!data.nodes || data.nodes.length === 0) {
      const tc = document.getElementById('theme-tree-container');
      if (tc) {
        const _n3 = new Date();
        const _t3 = `${_n3.getFullYear()}-${String(_n3.getMonth()+1).padStart(2,'0')}-${String(_n3.getDate()).padStart(2,'0')}`;
        const isLive = (dateOverride === _t3) && _n3.getHours() < 16 && !isMarketClosed(_t3);
        tc.innerHTML = `<div class="cal-empty" style="padding:24px 0;">${isLive ? '테마 데이터가 없습니다' : '해당 날짜의 테마 데이터가 없습니다'}</div>`;
      }
      return;
    }

    const ROOT_COLORS = ['#C9A962','#7C8CBA','#E07C5A','#6BA37E','#B47CC7','#5CABB5','#D4A05A','#8B7EC8','#C75C7C'];
    const nodes = data.nodes;
    const nodeMap = {};
    nodes.forEach(n => { nodeMap[n.id] = { ...n, children: [] }; });
    const roots = [];
    nodes.forEach(n => {
      if (n.parent_id && nodeMap[n.parent_id]) {
        nodeMap[n.parent_id].children.push(nodeMap[n.id]);
      } else if (!n.parent_id) {
        roots.push(nodeMap[n.id]);
      }
    });

    // 자식 거래대금 합산 (재귀, 상향식)
    // unique_trade_amount: 형제 테마 간 종목 중복을 제거한 정확한 합산값 (Python에서 계산)
    function sumTradeAmount(node) {
      // 자식 먼저 재귀 처리 (avg_change_pct 가중평균에 필요)
      node.children.forEach(c => sumTradeAmount(c));
      // 거래대금: unique_trade_amount가 양수면 사용, 0이면 자식 합산으로 대체
      if (node.unique_trade_amount != null && node.unique_trade_amount > 0) {
        node._totalAmt = node.unique_trade_amount;
      } else {
        let childSum = 0;
        node.children.forEach(c => { childSum += c._totalAmt; });
        node._totalAmt = node.trade_amount + childSum;
      }
      // avg_change_pct도 자식 가중 평균 계산
      if (node.trade_amount === 0 && node.children.length > 0) {
        let wSum = 0, wDiv = 0;
        node.children.forEach(c => {
          if (c._totalAmt > 0) { wSum += c._avgPct * c._totalAmt; wDiv += c._totalAmt; }
        });
        node._avgPct = wDiv > 0 ? wSum / wDiv : 0;
      } else {
        node._avgPct = node.avg_change_pct;
      }
      return node._totalAmt;
    }
    roots.forEach(r => sumTradeAmount(r));

    // 거래대금 내림차순 정렬 (재귀)
    function sortByAmt(arr) {
      arr.sort((a, b) => b._totalAmt - a._totalAmt);
      arr.forEach(n => sortByAmt(n.children));
    }
    sortByAmt(roots);

    // _totalAmt > 0인 루트만 표시 (거래대금 0 자식만 있는 루트도 제외)
    const visRoots = roots.filter(r => r._totalAmt > 0);

    // 글로벌 최대 거래대금
    const globalMax = Math.max(...visRoots.map(r => r._totalAmt), 1);

    function fmtAmt(v) {
      if (v >= 1e12) return (v / 1e12).toFixed(1) + '조';
      if (v >= 1e8) return Math.round(v / 1e8).toLocaleString() + '억';
      if (v >= 1e4) return Math.round(v / 1e4).toLocaleString() + '만';
      return v.toString();
    }

    function lighten(hex, pct) {
      const num = parseInt(hex.slice(1), 16);
      let r = (num >> 16) & 0xff, g = (num >> 8) & 0xff, b = num & 0xff;
      r = Math.min(255, Math.round(r + (255 - r) * pct));
      g = Math.min(255, Math.round(g + (255 - g) * pct));
      b = Math.min(255, Math.round(b + (255 - b) * pct));
      return '#' + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1);
    }

    const container = document.getElementById('theme-tree-container');
    if (!container) return;
    container.innerHTML = '';  // 날짜 변경 시 기존 트리 제거 (누적 방지)

    function renderNode(node, depth, rootColor) {
      const hasChildren = node.children.length > 0 && node.children.some(c => c._totalAmt > 0 || c.trade_amount > 0);
      const amt = node._totalAmt;
      const pct = node._avgPct;
      const descStocks = node.descendant_stock_count || (Array.isArray(node.stocks) ? node.stocks.length : 0);
      const isZero = amt === 0 && descStocks === 0;
      const barW = isZero ? 0 : Math.max(4, (amt / globalMax) * 120);
      const barColor = depth === 0 ? rootColor : lighten(rootColor, depth * 0.2);
      const pctColor = pct >= 0 ? '#EF4444' : '#3B82F6';
      const indent = depth * 24;

      const wrapper = document.createElement('div');
      const row = document.createElement('div');
      row.className = 'theme-tree-row';
      row.style.paddingLeft = indent + 'px';

      const arrow = document.createElement('span');
      arrow.className = 'theme-tree-arrow' + (hasChildren ? '' : ' leaf');
      arrow.textContent = '\u25B6';
      row.appendChild(arrow);

      const bar = document.createElement('span');
      bar.className = 'theme-tree-bar';
      bar.style.width = barW + 'px';
      bar.style.maxWidth = '120px';
      bar.style.background = barColor;
      if (isZero) bar.style.display = 'none';
      row.appendChild(bar);

      const name = document.createElement('span');
      name.className = 'theme-tree-name' + (isZero ? ' zero' : '');
      name.textContent = node.name;
      row.appendChild(name);

      if (!isZero) {
        const amtEl = document.createElement('span');
        amtEl.className = 'theme-tree-amt';
        amtEl.textContent = fmtAmt(amt);
        row.appendChild(amtEl);

        // 등락률 제거 (대표 지시 4/14 — 테마트리에 불필요)

        const ownCount = node.stock_count || (Array.isArray(node.stocks) ? node.stocks.length : 0);
        const descCount = node.descendant_stock_count || ownCount;
        if (descCount > 0) {
          const cntEl = document.createElement('span');
          cntEl.className = 'theme-tree-stock-count';
          cntEl.textContent = descCount + '\uC885\uBAA9';
          row.appendChild(cntEl);
        }
      } else {
        // trade_amount=0: dateOverride 후 종목이 채워질 수 있으므로 일단 표시
        // descendant_stock_count로 판단 — 자손 포함 종목이 0이면 숨김
        const descAny = node.descendant_stock_count || 0;
        if (descAny === 0) {
          wrapper.style.display = 'none';
        }
      }

      wrapper.appendChild(row);

      // --- 종목 행 렌더링 헬퍼 ---
      function renderStockRows(stocks, stockIndent) {
        // 종목코드(or 종목명) 기준 dedup — 같은 테마에 동일 종목 2회 표시 방지
        const seenKey = new Set();
        const dedupedStocks = stocks.filter(s => {
          const key = s.stock_code || s.code || s.name || s.stock_name || '';
          if (!key || seenKey.has(key)) return false;
          seenKey.add(key);
          return true;
        });
        const MAX_VISIBLE = 5;
        const frag = document.createDocumentFragment();
        const visible = dedupedStocks.slice(0, MAX_VISIBLE);
        const rest = dedupedStocks.slice(MAX_VISIBLE);

        visible.forEach(s => frag.appendChild(makeStockRow(s, stockIndent)));

        if (rest.length > 0) {
          const hiddenContainer = document.createElement('div');
          hiddenContainer.style.display = 'none';
          rest.forEach(s => hiddenContainer.appendChild(makeStockRow(s, stockIndent)));
          frag.appendChild(hiddenContainer);

          const moreRow = document.createElement('div');
          moreRow.className = 'theme-tree-stock-row';
          moreRow.style.paddingLeft = stockIndent + 'px';
          const moreLabel = document.createElement('span');
          moreLabel.className = 'theme-tree-stock-more';
          moreLabel.textContent = '\u00B7\u00B7\u00B7 \uC678 ' + rest.length + '\uC885\uBAA9';
          moreLabel.addEventListener('click', (e) => {
            e.stopPropagation();
            hiddenContainer.style.display = '';
            moreRow.style.display = 'none';
          });
          moreRow.appendChild(moreLabel);
          frag.appendChild(moreRow);
        }
        return frag;
      }

      function makeStockRow(s, stockIndent) {
        const sr = document.createElement('div');
        sr.className = 'theme-tree-stock-row';
        sr.style.paddingLeft = stockIndent + 'px';

        const sName = document.createElement('span');
        sName.className = 'theme-tree-stock-name';
        sName.textContent = s.name || s.stock_name || '';
        sr.appendChild(sName);

        const sPct = s.change_pct != null ? s.change_pct : s.pct;
        if (sPct != null) {
          const sPctEl = document.createElement('span');
          sPctEl.className = 'theme-tree-stock-pct';
          sPctEl.style.color = sPct >= 0 ? '#EF4444' : '#3B82F6';
          sPctEl.textContent = (sPct >= 0 ? '+' : '') + sPct.toFixed(2) + '%';
          sr.appendChild(sPctEl);
        }

        const sAmt = s.trade_amount != null ? s.trade_amount : s.amount;
        if (sAmt != null && sAmt > 0) {
          const sAmtEl = document.createElement('span');
          sAmtEl.className = 'theme-tree-stock-amt';
          sAmtEl.textContent = fmtAmt(sAmt);
          sr.appendChild(sAmtEl);
        }
        return sr;
      }

      const hasStocks = Array.isArray(node.stocks) && node.stocks.length > 0;
      const hasExpandable = hasChildren || hasStocks;
      const stockIndent = (depth + 1) * 24;

      if (hasChildren || hasStocks) {
        const childContainer = document.createElement('div');
        childContainer.className = 'theme-tree-children collapsed';
        if (hasChildren) {
          node.children.forEach(c => {
            // 거래대금 0인 자식도 표시 (연한 회색)
            childContainer.appendChild(renderNode(c, depth + 1, rootColor));
          });
        }
        if (hasStocks) {
          childContainer.appendChild(renderStockRows(node.stocks, stockIndent));
        }
        wrapper.appendChild(childContainer);

        row.addEventListener('click', () => {
          const isCollapsed = childContainer.classList.contains('collapsed');
          if (isCollapsed) {
            childContainer.classList.remove('collapsed');
            childContainer.style.maxHeight = childContainer.scrollHeight + 'px';
            arrow.classList.add('expanded');
          } else {
            childContainer.style.maxHeight = '0px';
            childContainer.classList.add('collapsed');
            arrow.classList.remove('expanded');
          }
        });

        // max-height transition 후 auto로 전환 (중첩 펼침 대응)
        childContainer.addEventListener('transitionend', () => {
          if (!childContainer.classList.contains('collapsed')) {
            childContainer.style.maxHeight = 'none';
          }
        });

        // hasStocks만 있고 children이 없으면 arrow 표시
        if (!hasChildren && hasStocks) {
          arrow.classList.remove('leaf');
        }
      }

      return wrapper;
    }

    const frag = document.createDocumentFragment();
    visRoots.forEach((root, i) => {
      frag.appendChild(renderNode(root, 0, ROOT_COLORS[i % ROOT_COLORS.length]));
    });
    container.appendChild(frag);

  } catch (e) { console.warn('theme-tree:', e); }
}

/* ───── 초기화 호출 ───── */
// initThemeTrend/initThemeMap/initThemeTree는 _refreshDataAsync에서 비동기 호출
initCalendar();
