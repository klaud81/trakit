"""나스닥 시총 상위 5개 종목 뉴스 → Gemini bias.

TQQQ 는 나스닥100 3배. 지수는 시총 상위 메가캡이 좌우하므로, 상위 5개 종목
(NVDA·AAPL·MSFT·GOOGL·AMZN) 관련 뉴스를 saveticker 아카이브에서 모아
Gemini 로 호재/악재를 판단, 다음 거래일 나스닥 방향 bias(-1.0~+1.0) 를 산출한다.

saveticker 는 텍스트 검색 API 가 없어(=q/keyword 무시) 제목/본문 이름매칭으로
필터. 한국어 번역 피드라 KR/EN 별칭 모두 매칭. created_at(KST) 로 과거 날짜
재구성 가능 → 백테스트도 동일 함수로 처리(디스크 캐시).

비용: 하루치 헤드라인을 1콜로 묶어 분석(일당 Gemini 1회). 결과는 디스크 캐시.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import GEMINI_API_KEY, GEMINI_MODEL, NEWS_LLM, NEWS_CLAUDE_MODEL

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

# 나스닥 시총 상위 5 (KR/EN 별칭). 순서=시총 내림차순 가정, 필요시 갱신.
TOP5_ALIASES = {
    "NVDA": ["엔비디아", "Nvidia", "NVDA"],
    "AAPL": ["애플", "Apple", "AAPL"],
    "MSFT": ["마이크로소프트", "Microsoft", "MSFT"],
    "GOOGL": ["알파벳", "구글", "Alphabet", "Google", "GOOGL", "GOOG"],
    "AMZN": ["아마존", "Amazon", "AMZN"],
}

# 시장 전반(공통) 매크로 카테고리 — 개별 종목 아닌 지수 전체 상승/하락 재료.
# 전쟁·관세·경제지표·연준 등. 그래프의 "공통" 노드로 연결.
MACRO_ALIASES = {
    "전쟁": ["전쟁", "우크라이나", "러시아", "이스라엘", "이란", "중동", "하마스",
             "휴전", "지정학", "분쟁", "war", "공습", "미사일"],
    "관세": ["관세", "무역전쟁", "무역협상", "tariff", "수입세", "보호무역", "무역장벽"],
    "경제지표": ["CPI", "PPI", "PCE", "고용", "실업", "GDP", "소비자물가", "생산자물가",
                 "비농업", "ISM", "소매판매", "물가지수", "경제성장"],
    "연준": ["연준", "Fed", "FOMC", "기준금리", "파월", "금리인하", "금리인상",
             "통화정책", "긴축", "완화"],
}

_UA = {"User-Agent": "Mozilla/5.0 (trakit)"}
_LIST_URL = "https://api.saveticker.com/api/news/list"
_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "news_bias_cache"


def _match_ticker(text: str) -> str | None:
    for tk, aliases in TOP5_ALIASES.items():
        if any(a in text for a in aliases):
            return tk
    return None


def _match_macro(text: str) -> str | None:
    for cat, aliases in MACRO_ALIASES.items():
        if any(a in text for a in aliases):
            return cat
    return None


def _fetch_page(page: int, page_size: int = 100) -> list[dict]:
    url = f"{_LIST_URL}?page={page}&page_size={page_size}&sort=created_at_desc"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=15) as r:
            return json.load(r).get("news_list", []) or []
    except Exception as e:
        logger.warning(f"saveticker page {page} 실패: {e}")
        return []


_MACRO_CAP_PER_CAT = 5   # 일·카테고리당 매크로 헤드라인 상한 (Gemini 입력 바운드)
_LEAD_CAP = 200          # 헤드라인별 리드 스니펫 길이 (제목+리드로 본문 맥락 보강)


def collect_by_date(start_date: str, max_pages: int = 1200) -> dict:
    """단일 패스로 start_date 이후 전 기간을 날짜별 버킷팅 (티커+매크로).

    60일을 매일 page1부터 재수집하는 낭비 방지. created_at_desc 로 거슬러
    올라가며 start_date 미만이면 종료.
    반환: {date: {"tickers":[{ticker,title,id}], "macros":[{category,title,id}]}}
    """
    buckets: dict = {}
    macro_cnt: dict = {}
    page = 1
    while page <= max_pages:
        items = _fetch_page(page)
        if not items:
            break
        page_dates = [it["created_at"][:10] for it in items]
        for it in items:
            d = it["created_at"][:10]
            if d < start_date:
                continue
            text = (it.get("title", "") or "") + " " + (it.get("content", "") or "")
            b = buckets.setdefault(d, {"tickers": [], "macros": []})
            lead = (it.get("content", "") or "").replace("\n", " ").strip()[:_LEAD_CAP]
            tk = _match_ticker(text)
            if tk:
                b["tickers"].append({"ticker": tk, "title": it.get("title", ""),
                                     "lead": lead, "id": it.get("id")})
                continue
            cat = _match_macro(text)
            if cat:
                key = (d, cat)
                if macro_cnt.get(key, 0) < _MACRO_CAP_PER_CAT:
                    macro_cnt[key] = macro_cnt.get(key, 0) + 1
                    b["macros"].append({"category": cat, "title": it.get("title", ""),
                                        "lead": lead, "id": it.get("id")})
        if min(page_dates) < start_date:
            break
        page += 1
    return buckets


def _strip_fence(s: str) -> str:
    """LLM 출력의 ```json … ``` 코드펜스 제거."""
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", s.strip())


def _claude_cli_json(prompt: str) -> dict:
    """claude CLI 헤드리스로 JSON 응답. Gemini 쿼터 우회용.

    프로젝트 CLAUDE.md 컨텍스트 로딩 비용 회피 위해 cwd=/tmp 에서 실행.
    모델은 NEWS_CLAUDE_MODEL(기본 haiku). 응답은 envelope.result 에 들어있고
    코드펜스가 붙을 수 있어 제거 후 파싱.
    """
    import subprocess
    proc = subprocess.run(
        ["claude", "-p", prompt, "--model", NEWS_CLAUDE_MODEL, "--output-format", "json"],
        cwd="/tmp", capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI 실패(rc={proc.returncode}): {proc.stderr[:200]}")
    env = json.loads(proc.stdout)
    if env.get("is_error"):
        raise RuntimeError(f"claude CLI error: {env.get('result', '')[:200]}")
    return json.loads(_strip_fence(env.get("result", "")))


def _gemini_json(prompt: str) -> dict:
    """Gemini API 로 JSON 응답 (429 백오프 재시도)."""
    gen_cfg = {"temperature": 0.3, "responseMimeType": "application/json"}
    if "2.5" in GEMINI_MODEL:  # 2.5-* 만 thinking 지원 → 끔(0). 2.0 은 필드 자체가 에러
        gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}
    payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                          "generationConfig": gen_cfg}).encode("utf-8")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                result = json.loads(resp.read())
            return json.loads(result["candidates"][0]["content"]["parts"][0]["text"])
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 3:
                wait = 15 * (attempt + 1)
                logger.warning(f"Gemini 429 — {wait}s 후 재시도 ({attempt + 1}/3)")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("Gemini 응답 없음")


def _llm_json(prompt: str) -> dict:
    """뉴스 분석 LLM 백엔드 디스패치 (NEWS_LLM=gemini|claude_cli)."""
    if NEWS_LLM == "claude_cli":
        return _claude_cli_json(prompt)
    return _gemini_json(prompt)


def _gemini_day_analysis(date: str, tickers: list[dict], macros: list[dict]) -> dict:
    """하루치 (티커+매크로) 헤드라인 → LLM 1콜 → bias + 이벤트 그래프 입력."""
    def _fmt(h, tag):
        lead = f" — {h['lead']}" if h.get("lead") else ""
        return f"- [{tag}] {h['title']}{lead}"
    tlines = "\n".join(_fmt(h, h["ticker"]) for h in tickers) or "(없음)"
    mlines = "\n".join(_fmt(h, h["category"]) for h in macros) or "(없음)"
    prompt = f"""당신은 나스닥100 지수 트레이딩 분석가입니다. {date} 뉴스로
다음 거래일 나스닥100(TQQQ 기초자산) 방향을 평가하세요.

[시총상위5 종목 뉴스] (개별 종목 재료)
{tlines}

[공통 매크로 뉴스] (전쟁·관세·경제지표·연준 등 지수 전체 재료)
{mlines}

아래 JSON 으로만 답하세요.
- nasdaq_bias: -1.0(강한 하방)~+1.0(강한 상방) 종합 점수 (종목+매크로 모두 반영)
- confidence: "강"|"중"|"약"
- summary: 1줄 한국어 근거
- per_ticker: {{"NVDA":"호재"|"악재"|"중립", ...}} (뉴스 있는 종목만)
- events: 종목 헤드라인별 [{{"ticker":..,"judgment":"호재"|"악재"|"중립","theme":"테마 한단어(AI반도체/규제/실적 등)","causal_chain":"원인 → 메커니즘 → 주가영향"}}]
- macro_events: 공통 헤드라인별 [{{"category":"전쟁"|"관세"|"경제지표"|"연준","direction":"상승"|"하락","causal_chain":"원인 → 메커니즘 → 지수영향","title":"원제목"}}]

{{"nasdaq_bias":0.0,"confidence":"약","summary":"...","per_ticker":{{}},"events":[],"macro_events":[]}}"""
    p = _llm_json(prompt)
    try:
        bias = max(-1.0, min(1.0, round(float(p.get("nasdaq_bias", 0.0)), 2)))
    except (TypeError, ValueError):
        bias = 0.0
    return {"nasdaq_bias": bias, "confidence": p.get("confidence", "약"),
            "summary": p.get("summary", ""), "per_ticker": p.get("per_ticker", {}),
            "events": p.get("events", []), "macro_events": p.get("macro_events", []),
            "n_headlines": len(tickers) + len(macros)}


def analyze_day(date: str, collected: dict | None = None, use_cache: bool = True) -> dict:
    """date 분석 → 캐시 + 지식그래프 ingest. collected 미지정 시 그날만 수집.

    반환: {date, nasdaq_bias, confidence, summary, per_ticker, events, macro_events, n_headlines}
    """
    from services import ticker_graph
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = _CACHE_DIR / f"{date}.json"
    if use_cache and cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    if collected is None:
        collected = collect_by_date(date).get(date, {"tickers": [], "macros": []})
    tickers, macros = collected.get("tickers", []), collected.get("macros", [])

    failed = False
    if (not tickers and not macros) or not GEMINI_API_KEY:
        res = {"date": date, "nasdaq_bias": 0.0, "confidence": "약",
               "summary": "헤드라인 없음" if not (tickers or macros) else "API 키 없음",
               "per_ticker": {}, "events": [], "macro_events": [],
               "n_headlines": len(tickers) + len(macros)}
    else:
        try:
            res = {"date": date, **_gemini_day_analysis(date, tickers, macros)}
        except Exception as e:
            logger.warning(f"analyze_day Gemini 실패 ({date}): {e}")
            failed = True
            res = {"date": date, "nasdaq_bias": 0.0, "confidence": "약",
                   "summary": f"분석 실패: {e}", "per_ticker": {}, "events": [],
                   "macro_events": [], "n_headlines": len(tickers) + len(macros)}
    if not failed:  # 실패(429/타임아웃)는 캐시 안 함 → 다음 실행에서 재시도
        cache.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        ticker_graph.ingest_day(date, res)
    return res


def build_range(dates: list[str], use_cache: bool = True) -> dict:
    """여러 날짜를 단일 수집 패스로 분석·그래프 구축. 반환: {date: 분석 dict 전체}."""
    start = min(dates)
    logger.info(f"📰 뉴스 수집 단일패스 (since {start}) …")
    buckets = collect_by_date(start)
    out = {}
    for idx, d in enumerate(sorted(dates)):
        if idx > 0 and NEWS_LLM == "gemini":
            time.sleep(5)  # Gemini 무료 tier RPM 한도 회피 (claude_cli 는 불필요)
        res = analyze_day(d, buckets.get(d, {"tickers": [], "macros": []}), use_cache=use_cache)
        out[d] = res
        logger.info(f"  {d}: bias {res['nasdaq_bias']:+.2f} "
                    f"(뉴스 {res['n_headlines']}건, {res.get('confidence','')})")
    return out


# 하위호환 별칭
def day_bias(date: str, use_cache: bool = True) -> dict:
    return analyze_day(date, None, use_cache)


if __name__ == "__main__":  # 수동 테스트: 특정일 분석 + 그래프 ingest
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else datetime.now(KST).strftime("%Y-%m-%d")
    print(json.dumps(analyze_day(d, use_cache=False), ensure_ascii=False, indent=2))
