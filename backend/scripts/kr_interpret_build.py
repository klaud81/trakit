#!/usr/bin/env python3
"""KR 뉴스 정리(interpreted) 자체생성 — 랭킹 종목 → 네이버 뉴스 → Gemini(newzy).

파이프라인:
  kiwoom/{date}.json (랭킹 종목)
    → 종목별 네이버 검색 API 로 뉴스 수집
    → analyze_news_newzy (Gemini) 로 causal_chain·newzy 점수 생성
    → dailybars 로 OHLC 보강
    → interpreted/stock-{date}.json 출력 (프론트 data-loader 소비)

100m1s interpreted 스키마 중 **코어 필드만** 생성한다. themes_tree / status_badges /
togusa_verdict / hugepark_grade / bullish_* 등은 100m1s 사설 파이프라인(테마 DB·다중
에이전트) 의존이라 재현 불가 → 생성하지 않음(렌더러는 누락 필드 graceful degrade).

사용:
  cd backend && python -m scripts.kr_interpret_build [--date YYYY-MM-DD] [--limit N]
                 [--news N] [--sleep S]
env: NAVER_CLIENT_ID/SECRET, GEMINI_API_KEY (config)
서버 cron (장 마감 후, 랭킹 캡처 다음):
  30 16 * * 1-5  cd /path/to/trakit/backend && python3 -m scripts.kr_interpret_build
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from config import NAVER_CLIENT_ID, NAVER_CLIENT_SECRET  # noqa: E402
from services.kr_news_interpret import analyze_news_newzy  # noqa: E402

KST = timezone(timedelta(hours=9))
KR_NEWS_DIR = REPO_ROOT / "frontend" / "public" / "kr-news" / "data"
KIWOOM_DIR = KR_NEWS_DIR / "kiwoom"
DAILYBARS_DIR = KR_NEWS_DIR / "dailybars"
INTERPRETED_DIR = KR_NEWS_DIR / "interpreted"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("kr_interpret_build")

_TAG = re.compile(r"<[^>]+>")


def _strip(s: str) -> str:
    return _TAG.sub("", s or "").replace("&quot;", '"').replace("&amp;", "&").strip()


def naver_news(query: str, display: int = 3) -> list[dict]:
    """네이버 검색 API 뉴스 → [{title,url,source,published_at}, ...]."""
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return []
    q = urllib.parse.quote(query)
    url = f"https://openapi.naver.com/v1/search/news.json?query={q}&display={display}&sort=sim"
    req = urllib.request.Request(url, headers={
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            items = json.load(r).get("items", [])
    except Exception as e:
        logger.warning(f"네이버 검색 실패 ({query}): {e}")
        return []
    out = []
    for it in items:
        link = it.get("link") or it.get("originallink") or ""
        host = urllib.parse.urlparse(it.get("originallink") or link).netloc
        out.append({
            "title": _strip(it.get("title", "")),
            "url": link,
            "source": host,
            "published_at": it.get("pubDate", ""),
        })
    return out


def _load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _ohlc(code: str, date: str) -> dict:
    """dailybars/{code}.json 에서 해당일 OHLC + 전일대비 change_pct."""
    d = _load(DAILYBARS_DIR / f"{code}.json")
    rows = d.get("rows") or []
    for i, r in enumerate(rows):
        if r["d"] == date:
            prev = rows[i - 1]["c"] if i > 0 else None
            chg = round((r["c"] - prev) / prev * 100, 2) if prev else None
            return {"close_price": r["c"], "open_price": r["o"], "high_price": r["h"],
                    "low_price": r["l"], "change_pct": chg}
    return {}


def build(date: str, limit: int, news_n: int, sleep: float) -> dict:
    kf = _load(KIWOOM_DIR / f"{date}.json")
    ranked = kf.get("daily_top") or kf.get("latest_stocks") or []
    if limit > 0:
        ranked = ranked[:limit]
    logger.info(f"{date} 랭킹 {len(ranked)}종목 → 뉴스 해석")

    stocks = []
    for i, rk in enumerate(ranked):
        code = str(rk.get("ticker", ""))
        name = rk.get("name", "")
        if not code or not name:
            continue
        articles = naver_news(name, display=news_n)
        news = []
        for a in articles:
            nz = analyze_news_newzy(a["url"], stock_name=name, title=a["title"])
            news.append({**a, **nz})
            time.sleep(sleep)
        entry = {
            "code": code, "name": name, "rank": rk.get("rank", i + 1),
            "trade_amount": rk.get("max_trade_amount") or rk.get("trade_amount") or 0,
            "themes": [], "news": news,
        }
        entry.update(_ohlc(code, date))  # close/open/high/low/change_pct
        if entry.get("change_pct") is None:
            entry["change_pct"] = rk.get("max_change_pct") or rk.get("change_pct") or 0
        stocks.append(entry)
        logger.info(f"[{i + 1}/{len(ranked)}] {code} {name} → 뉴스 {len(news)}건")

    return {
        "date": date,
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "data_source": "kiwoom+naver+gemini",  # 자체수집 (100m1s 미러 아님)
        "stocks": stocks,
    }


def main() -> int:
    INTERPRETED_DIR.mkdir(parents=True, exist_ok=True)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--date", default=datetime.now(KST).strftime("%Y-%m-%d"))
    ap.add_argument("--limit", type=int, default=15, help="처리 종목 수 (0=전체)")
    ap.add_argument("--news", type=int, default=3, help="종목당 뉴스 수")
    ap.add_argument("--sleep", type=float, default=0.5, help="Gemini 호출 간 sleep(초)")
    args = ap.parse_args()

    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        logger.error("네이버 검색 키 미설정 (NAVER_CLIENT_ID/SECRET)")
        return 1
    if not (KIWOOM_DIR / f"{args.date}.json").exists():
        logger.error(f"랭킹 파일 없음: kiwoom/{args.date}.json (랭킹 캡처 먼저 필요)")
        return 1

    started = datetime.now(KST)
    result = build(args.date, args.limit, args.news, args.sleep)
    if not result["stocks"]:
        logger.warning("생성된 종목 없음")
        return 1
    out = INTERPRETED_DIR / f"stock-{args.date}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    elapsed = (datetime.now(KST) - started).total_seconds()
    total_news = sum(len(s["news"]) for s in result["stocks"])
    logger.info(f"✓ {out.name} 저장 — {len(result['stocks'])}종목 / 뉴스 {total_news}건 ({elapsed:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
