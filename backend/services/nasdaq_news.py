"""나스닥 시총 상위 5개 종목 + 매크로 뉴스 → LLM bias.

TQQQ 는 나스닥100 3배. 지수는 시총 상위 메가캡이 좌우하므로, 상위 5개 종목
(NVDA·AAPL·MSFT·GOOGL·AMZN) 관련 뉴스와 공통 매크로(전쟁·관세·경제지표·연준)
뉴스를 모아 LLM 으로 호재/악재를 판단, 다음 거래일 나스닥 방향 bias(-1.0~+1.0) 를 산출한다.

뉴스 소스: Google News RSS 검색(한국어, 키 불필요). `after:`/`before:` 날짜 연산자로
과거 날짜도 재구성 가능 → 백테스트도 동일 함수로 처리(디스크 캐시).
(기존 saveticker list API 는 2026-07 서비스 개편 후 안내글 1건만 반환 → 교체)

비용: 하루치 헤드라인을 1콜로 묶어 분석(일당 LLM 1회, NEWS_LLM 으로 백엔드 선택). 결과는 디스크 캐시.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path

from typing import Literal

from pydantic import BaseModel

from config import (GEMINI_API_KEY, GEMINI_MODEL, NEWS_LLM, NEWS_CLAUDE_MODEL,
                    ANTHROPIC_API_KEY, NEWS_CLAUDE_API_MODEL, NEWS_CLAUDE_EFFORT)

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

# Google News 검색어 — 티커는 TOP5_ALIASES 첫 두 별칭(KR/EN)으로 검색 후 제목 별칭으로 재확인,
# 매크로는 카테고리별 대표 키워드로 검색 (MACRO_ALIASES 는 분류 규칙으로 유지).
MACRO_QUERIES = {
    "전쟁": "전쟁 OR 지정학 OR 중동 OR 우크라이나 증시",
    "관세": "관세 OR 무역협상 OR 무역전쟁 미국",
    "경제지표": "미국 CPI OR PPI OR PCE OR 고용지표 OR GDP OR 소매판매",
    "연준": "연준 OR FOMC OR 기준금리 OR 파월",
}
# 매크로 검색은 동음이의(예: 인물명 '연준')가 섞이므로 시장 맥락 단어가 있는 제목만 채택
_MARKET_WORDS = ("증시", "주가", "주식", "나스닥", "S&P", "다우", "뉴욕", "금리", "채권", "국채",
                 "달러", "환율", "물가", "인플레", "경제", "경기", "시장", "미국", "美", "연준", "Fed",
                 "FOMC", "관세", "무역", "유가", "지표", "고용")

_UA = {"User-Agent": "Mozilla/5.0 (trakit)"}
_RSS_URL = "https://news.google.com/rss/search"
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


_MACRO_CAP_PER_CAT = 5   # 일·카테고리당 매크로 헤드라인 상한 (LLM 입력 바운드)
_TICKER_CAP_PER_DAY = 8  # 일·티커당 헤드라인 상한 (LLM 입력 바운드)
_RSS_SLEEP = 0.5         # 검색 요청 간격 (Google News 레이트리밋 회피)


def _clean_title(title: str) -> tuple[str, str]:
    """Google News 제목 'XXX - 언론사' → (제목, 언론사)."""
    head, sep, src = (title or "").rpartition(" - ")
    return (head.strip(), src.strip()) if sep else ((title or "").strip(), "")


def _search_rss(query: str, day: str) -> list[dict]:
    """day 하루치 검색 결과 (최대 100건, 관련도순). 실패 시 [].

    Google 의 `after:D before:D+1` 은 미국 태평양시(PT) 하루 = KST D 16:00 ~ D+1 16:00.
    사전장 예측(KST 17:00)이 쓰는 day_bias(전일 D) 에는 직전까지의 최신 뉴스가 담긴다.
    """
    d = _date.fromisoformat(day)
    q = f"{query} after:{d} before:{d + timedelta(days=1)}"
    url = f"{_RSS_URL}?" + urllib.parse.urlencode({"q": q, "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=15) as r:
            root = ET.fromstring(r.read())
    except Exception as e:
        logger.warning(f"Google News 검색 실패 ({day}, {query[:20]}): {e}")
        return []
    out = []
    for it in root.iter("item"):
        title, source = _clean_title(it.findtext("title") or "")
        out.append({"title": title, "source": source, "id": it.findtext("guid") or it.findtext("link")})
    return out


def _collect_day(day: str) -> dict:
    """하루치 티커+매크로 헤드라인. 제목 중복 제거, 티커 매칭 우선(기존 규칙 유지)."""
    b: dict = {"tickers": [], "macros": []}
    seen: set[str] = set()
    for tk, aliases in TOP5_ALIASES.items():
        n = 0
        for h in _search_rss(" OR ".join(aliases[:2]), day):
            if n >= _TICKER_CAP_PER_DAY:
                break
            if h["title"] in seen or _match_ticker(h["title"]) != tk:
                continue
            seen.add(h["title"])
            b["tickers"].append({"ticker": tk, "title": h["title"], "lead": h["source"], "id": h["id"]})
            n += 1
        time.sleep(_RSS_SLEEP)
    for cat, query in MACRO_QUERIES.items():
        n = 0
        for h in _search_rss(query, day):
            if n >= _MACRO_CAP_PER_CAT:
                break
            t = h["title"]
            if t in seen or _match_ticker(t) or _match_macro(t) != cat \
                    or not any(w in t for w in _MARKET_WORDS if w not in MACRO_ALIASES[cat]):
                continue
            seen.add(h["title"])
            b["macros"].append({"category": cat, "title": h["title"], "lead": h["source"], "id": h["id"]})
            n += 1
        time.sleep(_RSS_SLEEP)
    return b


def collect_by_date(start_date: str, end_date: str | None = None) -> dict:
    """start_date~end_date(기본 오늘 KST) 날짜별 헤드라인 버킷 (티커+매크로). 날짜 경계는 _search_rss 참고.

    주말 뉴스도 다음 거래일 재료가 될 수 있어 모든 날짜를 수집한다.
    반환: {date: {"tickers":[{ticker,title,lead,id}], "macros":[{category,title,lead,id}]}}
    lead 는 언론사명 (RSS 는 본문 요약을 주지 않음).
    """
    end = _date.fromisoformat(end_date) if end_date else datetime.now(KST).date()
    d = _date.fromisoformat(start_date)
    buckets: dict = {}
    while d <= end:
        buckets[d.isoformat()] = _collect_day(d.isoformat())
        d += timedelta(days=1)
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


# claude_api 구조화 출력 스키마 — 프롬프트의 JSON 형식과 동일
_Judgment = Literal["호재", "악재", "중립"]


class _TickerJudgment(BaseModel):
    ticker: str
    judgment: _Judgment


class _TickerEvent(BaseModel):
    ticker: str
    judgment: _Judgment
    theme: str
    causal_chain: str


class _MacroEvent(BaseModel):
    category: Literal["전쟁", "관세", "경제지표", "연준"]
    direction: Literal["상승", "하락"]
    causal_chain: str
    title: str


class _DayAnalysis(BaseModel):
    nasdaq_bias: float
    confidence: Literal["강", "중", "약"]
    summary: str
    per_ticker: list[_TickerJudgment]  # 스키마 호환 위해 list 로 받고 dict 로 변환
    events: list[_TickerEvent]
    macro_events: list[_MacroEvent]


_anthropic_client = None


def _claude_api_json(prompt: str) -> dict:
    """Anthropic Messages API 구조화 출력으로 JSON 응답. 서버(도커)용.

    실패(레이트리밋·네트워크·refusal)는 raise → analyze_day 가 캐시 없이 강등 처리.
    """
    global _anthropic_client
    import anthropic
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=120, max_retries=2)
    resp = _anthropic_client.messages.parse(
        model=NEWS_CLAUDE_API_MODEL,
        max_tokens=16000,
        output_config={"effort": NEWS_CLAUDE_EFFORT},
        messages=[{"role": "user", "content": prompt}],
        output_format=_DayAnalysis,
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude API refusal")
    if resp.parsed_output is None:
        raise RuntimeError(f"Claude API 파싱 실패 (stop_reason={resp.stop_reason})")
    u = resp.usage
    logger.info(f"🤖 Claude API {NEWS_CLAUDE_API_MODEL}: in {u.input_tokens} / out {u.output_tokens} tok")
    out = resp.parsed_output.model_dump()
    out["per_ticker"] = {t["ticker"]: t["judgment"] for t in out["per_ticker"]}
    return out


def _llm_json(prompt: str) -> dict:
    """뉴스 분석 LLM 백엔드 디스패치 (NEWS_LLM=gemini|claude_cli|claude_api)."""
    if NEWS_LLM == "claude_cli":
        return _claude_cli_json(prompt)
    if NEWS_LLM == "claude_api":
        return _claude_api_json(prompt)
    return _gemini_json(prompt)


def _llm_ready() -> bool:
    """선택된 백엔드의 키가 준비됐는지 (claude_cli 는 로컬 로그인 사용)."""
    return {"gemini": bool(GEMINI_API_KEY), "claude_api": bool(ANTHROPIC_API_KEY),
            "claude_cli": True}.get(NEWS_LLM, False)


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
            cached = json.loads(cache.read_text(encoding="utf-8"))
            # 헤드라인 0건 캐시는 재수집 (saveticker 폐쇄 기간·수집 실패분 복구)
            if cached.get("n_headlines", 0) > 0:
                return cached
        except json.JSONDecodeError:
            pass

    if collected is None:
        collected = _collect_day(date)
    tickers, macros = collected.get("tickers", []), collected.get("macros", [])

    failed = False
    if (not tickers and not macros) or not _llm_ready():
        res = {"date": date, "nasdaq_bias": 0.0, "confidence": "약",
               "summary": "헤드라인 없음" if not (tickers or macros) else "API 키 없음",
               "per_ticker": {}, "events": [], "macro_events": [],
               "n_headlines": len(tickers) + len(macros)}
    else:
        try:
            res = {"date": date, **_gemini_day_analysis(date, tickers, macros)}
        except Exception as e:
            logger.warning(f"analyze_day {NEWS_LLM} 실패 ({date}): {e}")
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
    buckets = collect_by_date(start, max(dates))
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
