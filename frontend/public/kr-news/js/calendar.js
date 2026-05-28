/* ───── calendar.js — 달력/날짜 로직 ───── */

let calIndex = null;           // data/calendar/index.json (없으면 null)
let holidayData = null;        // data/holidays.json (공휴일 + KRX 휴장일)
let calViewYear, calViewMonth; // 현재 보기 연·월 (month: 1~12)
let calSelectedDate = null;    // 'YYYY-MM-DD'
let calCategory = 'stock';     // 'stock' | 'realestate' | 'policy' (Phase 2/3 확장용)
const calDayCache = (() => {
  try {
    const raw = JSON.parse(localStorage.getItem('calDayCache') || '{}');
    // Map 복원: interpretedByName이 배열이면 Map으로 재구성
    for (const [date, entry] of Object.entries(raw)) {
      if (entry && Array.isArray(entry.interpretedByName)) {
        entry.interpretedByName = new Map(entry.interpretedByName);
      }
    }
    return raw;
  } catch { return {}; }
})();

function _persistCache() {
  try {
    const keys = Object.keys(calDayCache).sort().reverse().slice(0, 7);
    const trimmed = {};
    for (const k of keys) {
      const entry = calDayCache[k];
      if (!entry) continue;
      // Map→Array 직렬화 (JSON.stringify는 Map을 빈 객체로 변환하므로)
      trimmed[k] = {
        ...entry,
        interpretedByName: entry.interpretedByName instanceof Map
          ? Array.from(entry.interpretedByName.entries())
          : entry.interpretedByName
      };
    }
    localStorage.setItem('calDayCache', JSON.stringify(trimmed));
  } catch {}
}

function isHoliday(iso) {
  return holidayData && holidayData.holidays && (iso in holidayData.holidays);
}

function getHolidayName(iso) {
  if (!holidayData || !holidayData.holidays) return null;
  return holidayData.holidays[iso] || null;
}

function isMarketClosed(iso) {
  if (!holidayData || !holidayData.market_closed) return isWeekendDate(iso);
  return iso in holidayData.market_closed;
}

// design-news-time-state-v1 — 시점 4구간 분기 SSOT.
// 본 함수가 PRE_MARKET / OPEN / POST_MARKET / HOLIDAY 단일 출처. renderer.js의
// (hour < 16) 휴리스틱은 04:14에도 true가 되는 결함 → 폐기.
// PRE_MARKET = 거래일 09:00 미만 / OPEN = 09:00~15:30 / POST_MARKET = 15:30 이후
// HOLIDAY = isMarketClosed (주말 + KRX 휴장일)
function getMarketState(iso, now) {
  const _now = now || new Date();
  const todayIso = iso || ymd(_now.getFullYear(), _now.getMonth() + 1, _now.getDate());
  if (isMarketClosed(todayIso)) return 'HOLIDAY';
  const hm = _now.getHours() * 60 + _now.getMinutes();
  if (hm < 9 * 60) return 'PRE_MARKET';
  if (hm < 15 * 60 + 30) return 'OPEN';
  return 'POST_MARKET';
}

function formatKoDate(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  const dow = ['일','월','화','수','목','금','토'][new Date(y, m - 1, d).getDay()];
  return `${m}월 ${d}일 (${dow})`;
}

function isWeekendDate(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  const dow = new Date(y, m - 1, d).getDay();
  return dow === 0 || dow === 6;
}

// 다음 거래일 계산 (최대 10일 탐색)
function getNextTradingDate(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  const dt = new Date(y, m - 1, d);
  for (let i = 0; i < 10; i++) {
    dt.setDate(dt.getDate() + 1);
    const next = ymd(dt.getFullYear(), dt.getMonth() + 1, dt.getDate());
    if (!isMarketClosed(next)) return next;
  }
  return null;
}

function calHasData(date) {
  if (!calIndex || !calIndex.days) return false;
  const entry = calIndex.days[date];
  if (!entry) return false;
  return (entry.stock_count ?? 0) >= 1 && (entry.news_count ?? 0) >= 1;
}

// 비거래일이면 테마트리·거래대금 추이 숨김
function toggleThemeSections(iso) {
  const closed = isMarketClosed(iso);
  const tree = document.getElementById('theme-tree');
  const trend = document.getElementById('theme-trend');
  if (tree) tree.style.display = closed ? 'none' : '';
  if (trend) trend.style.display = closed ? 'none' : '';
}

function renderCalendar() {
  const grid = document.getElementById('toss-cal-grid');
  const ymEl = document.getElementById('toss-cal-ym');
  const subEl = document.getElementById('toss-cal-sub');
  const prevBtn = document.getElementById('toss-cal-prev');
  const nextBtn = document.getElementById('toss-cal-next');

  ymEl.textContent = `${calViewYear}년 ${calViewMonth}월`;

  const today = new Date();
  const todayY = today.getFullYear();
  const todayM = today.getMonth() + 1;
  const todayD = today.getDate();
  const todayStr = ymd(todayY, todayM, todayD);

  // 서브 텍스트 (해당 월 집계)
  subEl.textContent = '';

  // 네비게이션 제한
  nextBtn.disabled = (calViewYear > todayY) || (calViewYear === todayY && calViewMonth >= todayM);

  // 그리드 렌더
  const firstDow = new Date(calViewYear, calViewMonth - 1, 1).getDay();
  const daysInMonth = new Date(calViewYear, calViewMonth, 0).getDate();
  const dows = ['일','월','화','수','목','금','토'];
  let html = '';
  dows.forEach((d, i) => {
    const cls = i === 0 ? 'sun' : (i === 6 ? 'sat' : '');
    html += `<div class="toss-cal-dow ${cls}">${d}</div>`;
  });
  for (let i = 0; i < firstDow; i++) {
    html += `<div class="toss-cal-cell outside"></div>`;
  }
  for (let d = 1; d <= daysInMonth; d++) {
    const date = ymd(calViewYear, calViewMonth, d);
    const isFuture = (calViewYear > todayY) ||
                     (calViewYear === todayY && calViewMonth > todayM) ||
                     (calViewYear === todayY && calViewMonth === todayM && d > todayD);
    const hasData = isFuture ? false : calHasData(date);
    const dow = new Date(calViewYear, calViewMonth - 1, d).getDay();
    const isWeekend = (dow === 0 || dow === 6);
    const isToday = (date === todayStr);
    const isHol = isHoliday(date);
    const classes = ['toss-cal-cell'];
    const isTodayMarketHours = isToday && !isMarketClosed(date) && (new Date().getHours() < 16);
    if (isFuture) classes.push('future');
    else if (!hasData && !isToday && !isTodayMarketHours) classes.push('no-data');
    else if (!hasData && isTodayMarketHours) classes.push('market-hours');
    if (isWeekend) classes.push('weekend');
    if (dow === 0) classes.push('sunday');
    if (dow === 6) classes.push('saturday');
    if (isHol) classes.push('holiday');
    if (isToday) classes.push('today');
    if (date === calSelectedDate) classes.push('selected');
    const holName = getHolidayName(date);
    const aria = `${date}${isToday ? ' (오늘)' : ''}${isTodayMarketHours ? ' (장중)' : ''}${holName ? ' ' + holName : ''}`;
    const isClickable = !isFuture && (hasData || isToday);
    html += `<div class="${classes.join(' ')}" data-date="${date}" role="button" tabindex="${isClickable ? 0 : -1}" aria-label="${aria}">${d}</div>`;
  }
  grid.innerHTML = html;

  grid.querySelectorAll('.toss-cal-cell[data-date]').forEach(el => {
    if (el.classList.contains('future')) return;
    el.addEventListener('click', () => onCalCellClick(el.dataset.date));
  });
}

async function onCalCellClick(date, pushState) {
  calSelectedDate = date;
  toggleThemeSections(date);
  // Static URL — /news/{date}.html로 공유 시 날짜별 OG 이미지 매칭
  if (pushState !== false) {
    history.pushState(null, '', 'news/stock/' + date + '.html');
  }
  renderCalendar();
  const inner = document.getElementById('cal-content');
  inner.innerHTML = `
    <div class="cal-content-head" role="button" tabindex="0" aria-label="달력으로 이동" data-scroll-to-cal="1">
      <div class="cal-content-date">${formatKoDate(date)}</div>
      <div class="cal-content-meta">불러오는 중…</div>
    </div>
    <div class="cal-empty"><div>데이터 로드 중</div></div>
  `;
  const data = await loadCalDayData(date);
  renderCalExpandContent(date, data);
  // 테마트리도 해당 날짜 기준으로 재렌더링 (휴장일은 안내 메시지)
  initThemeTree(date);
}

async function initCalendar() {
  const meta = document.getElementById('meta');
  if (meta) meta.textContent = '';

  // 1단계: localStorage 캐시에서 즉시 복원 (fetch 0건, ~10ms)
  const cachedCalIndex = (() => { try { return JSON.parse(localStorage.getItem('calIndex') || 'null'); } catch { return null; } })();
  calIndex = cachedCalIndex;
  holidayData = (() => { try { return JSON.parse(localStorage.getItem('holidayData') || 'null'); } catch { return null; } })();
  themesData = (() => { try { return JSON.parse(localStorage.getItem('themesData') || 'null'); } catch { return null; } })();

  const now = new Date();
  const todayStr = ymd(now.getFullYear(), now.getMonth() + 1, now.getDate());
  // URL ?cat= / ?date= 파라미터. cat 기본값 stock.
  const urlParams = new URLSearchParams(window.location.search);
  const urlCat = urlParams.get('cat');
  if (urlCat && ['stock', 'realestate', 'policy'].includes(urlCat)) calCategory = urlCat;
  const urlDate = urlParams.get('date');
  // 해시 앵커(#2026-04-10) 지원 — news/YYYY-MM-DD.html에서 리다이렉트
  const hashDate = window.location.hash.replace('#', '');
  const hasUrlDate = (urlDate && /^\d{4}-\d{2}-\d{2}$/.test(urlDate))
    || (hashDate && /^\d{4}-\d{2}-\d{2}$/.test(hashDate));
  let initialDate = hasUrlDate ? (urlDate || hashDate) : todayStr;
  // URL 날짜가 없고, 오늘이 주말/휴장이면 최근 거래일로 폴백
  // 오늘이 평일이면 calIndex에 없어도 항상 오늘 선택 (데이터 비동기 로드)
  if (!hasUrlDate && (isWeekendDate(todayStr) || isHoliday(todayStr))) {
    if (calIndex && calIndex.days) {
      const collectedDays = Object.keys(calIndex.days)
        .filter(d => d <= todayStr)
        .sort();
      if (collectedDays.length > 0) {
        initialDate = collectedDays[collectedDays.length - 1];
      }
    }
  }
  const [iy, im] = initialDate.split('-').map(Number);
  calViewYear = iy;
  calViewMonth = im;
  calSelectedDate = initialDate;

  // 2단계: 달력 UI 즉시 렌더 (캐시 기반, fetch 안 기다림)
  renderCalendar();

  // 3단계: 캐시된 당일 데이터로 즉시 카드 렌더 (있으면)
  if (calDayCache[initialDate]) {
    toggleThemeSections(initialDate);
    renderCalExpandContent(initialDate, calDayCache[initialDate]);
  } else {
    // 캐시 없음 — 로딩 표시
    toggleThemeSections(initialDate);
    const inner = document.getElementById('cal-content');
    if (inner) inner.innerHTML = '<div class="cal-content-head" role="button" tabindex="0" aria-label="달력으로 이동" data-scroll-to-cal="1"><div class="cal-content-date">' + formatKoDate(initialDate) + '</div><div class="cal-content-meta">불러오는 중\u2026</div></div><div class="cal-empty"><div>데이터 로드 중</div></div>';
  }

  // 4단계: 비동기 네트워크 갱신 (사용자가 기다리지 않음)
  _refreshDataAsync(initialDate);

  // 이벤트 리스너 (동기, 즉시)
  window.addEventListener('popstate', () => {
    const p = new URLSearchParams(window.location.search);
    const d = p.get('date');
    const h = window.location.hash.replace('#', '');
    const date = d || (h && /^\d{4}-\d{2}-\d{2}$/.test(h) ? h : null);
    const c = p.get('cat');
    if (c && ['stock', 'realestate', 'policy'].includes(c)) calCategory = c;
    if (date && /^\d{4}-\d{2}-\d{2}$/.test(date)) onCalCellClick(date, false);
  });

  document.getElementById('toss-cal-prev').addEventListener('click', () => {
    calViewMonth--;
    if (calViewMonth < 1) { calViewMonth = 12; calViewYear--; }
    renderCalendar();
  });
  document.getElementById('toss-cal-next').addEventListener('click', () => {
    const now2 = new Date();
    if (calViewYear > now2.getFullYear() ||
        (calViewYear === now2.getFullYear() && calViewMonth >= now2.getMonth() + 1)) return;
    calViewMonth++;
    if (calViewMonth > 12) { calViewMonth = 1; calViewYear++; }
    renderCalendar();
  });
}

// 비동기 데이터 갱신 — 초기 렌더 후 백그라운드
async function _refreshDataAsync(initialDate) {
  try {
    // 네트워크에서 최신 메타 데이터 fetch (병렬)
    const [calIdx, themes, holidays] = await Promise.all([
      loadCalendarIndex(), loadThemes(), loadHolidayData()
    ]);
    if (calIdx) { calIndex = calIdx; try { localStorage.setItem('calIndex', JSON.stringify(calIdx)); } catch {} }
    if (themes) { themesData = themes; try { localStorage.setItem('themesData', JSON.stringify(themes)); } catch {} }
    if (holidays) { holidayData = holidays; try { localStorage.setItem('holidayData', JSON.stringify(holidays)); } catch {} }

    // 달력 재렌더 (인덱스 업데이트 반영)
    renderCalendar();

    // 당일 데이터 강제 재로드 (캐시 무시) + 카드 렌더
    delete calDayCache[initialDate];
    const data = await loadCalDayData(initialDate);
    renderCalExpandContent(initialDate, data);

    // 테마 트리/트렌드 초기화 (휴장일은 함수 내부에서 안내 메시지 표시)
    initThemeTree(initialDate);
    initThemeTrend();
    initLimitUpTrend();
    initThemeMap();
  } catch (e) {
    console.warn('_refreshDataAsync:', e);
  }
}
