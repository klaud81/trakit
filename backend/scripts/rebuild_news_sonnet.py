#!/usr/bin/env python3
"""90일 뉴스 캐시 sonnet 클린 재빌드 (rq-02 §8.1).

기존 haiku 캐시 날짜 목록을 그대로 sonnet 으로 재분석. ticker_graph 집계는
누적 구조라 호출 전 초기화 필요(_macro.json/{TICKER}.json/_graph.json/daily).

실행 (claude_cli/sonnet 강제):
  cd backend && NEWS_LLM=claude_cli NEWS_CLAUDE_MODEL=sonnet \
    python -m scripts.rebuild_news_sonnet
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("rebuild")

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
DATA = BACKEND.parent / "data"
CACHE = DATA / "news_bias_cache"
GRAPH = DATA / "ticker_graph"


def _cached_dates() -> list[str]:
    return sorted(p.stem for p in CACHE.glob("*.json"))


def _reset_graph_aggregates() -> None:
    """누적 집계 파일 삭제 — daily/{date}.json 은 멱등 덮어쓰기라 유지해도 무방하나 클린 위해 같이 제거."""
    for name in ("_macro.json", "_graph.json", "NVDA.json", "AAPL.json",
                 "MSFT.json", "GOOGL.json", "AMZN.json"):
        (GRAPH / name).unlink(missing_ok=True)
    for p in (GRAPH / "daily").glob("*.json"):
        p.unlink()
    log.info("ticker_graph 집계 초기화 완료")


def main() -> None:
    from services import nasdaq_news as nn
    if nn.NEWS_LLM != "claude_cli" or nn.NEWS_CLAUDE_MODEL != "sonnet":
        log.error(f"env 미설정: NEWS_LLM={nn.NEWS_LLM} MODEL={nn.NEWS_CLAUDE_MODEL} "
                  "→ NEWS_LLM=claude_cli NEWS_CLAUDE_MODEL=sonnet 로 실행하세요")
        sys.exit(1)
    dates = _cached_dates()
    log.info(f"재빌드 대상 {len(dates)}일 ({dates[0]} ~ {dates[-1]}) · 모델 sonnet")
    _reset_graph_aggregates()
    # 수집은 1회 패스 (build_range), 분석은 날짜별 sonnet 1콜. use_cache=False 로 강제 재분석.
    # 분석 직전 그날 캐시를 지워 실패 시에도 옛 haiku 값이 남지 않게 함.
    for d in dates:
        (CACHE / f"{d}.json").unlink(missing_ok=True)
    results = nn.build_range(dates, use_cache=False)
    nonzero = sum(1 for r in results.values() if r.get("nasdaq_bias", 0.0))
    strong = sum(1 for r in results.values() if abs(r.get("nasdaq_bias", 0.0)) >= 0.4)
    log.info(f"완료 — 총 {len(dates)}일 · bias≠0 {nonzero}일 · 강한bias(≥0.4) {strong}일 "
             f"(haiku 기준 7일)")


if __name__ == "__main__":
    main()
