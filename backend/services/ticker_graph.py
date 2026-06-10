"""티커별 지식그래프 — 날짜별 뉴스 분석 출력을 누적·연결.

저장 구조 (data/ticker_graph/):
  daily/{date}.json   ← 1차 데이터: 그날의 {nasdaq_bias, ticker_events, macro_events}
  {TICKER}.json       ← 집계: 종목별 이벤트 타임라인 + 테마 빈도 + 연결 티커
  _macro.json         ← 집계: 공통(전쟁/관세/경제지표/연준) 상승·하락 이벤트
  _graph.json         ← 노드+엣지 (ticker / theme / macro), 소비/렌더용

노드: ticker(NVDA..) · theme(AI반도체..) · macro(전쟁/관세..)
엣지: ticker→theme(언급) · ticker↔ticker(공유테마 공출현) · macro→MARKET(상승/하락)
"""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)
GRAPH_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "ticker_graph"
DAILY_DIR = GRAPH_DIR / "daily"

_TICKER_NAME = {"NVDA": "엔비디아", "AAPL": "애플", "MSFT": "마이크로소프트",
                "GOOGL": "알파벳", "AMZN": "아마존"}


def _load(p: Path) -> dict:
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save(p: Path, d: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def ingest_day(date: str, analysis: dict) -> None:
    """하루치 분석을 날짜별 데이터로 저장하고 집계 그래프 갱신.

    analysis: {nasdaq_bias, confidence, summary,
               events:[{ticker,judgment,theme,causal_chain}],
               macro_events:[{category,direction(상승/하락),causal_chain,title?}]}
    """
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    ticker_events = analysis.get("events", []) or []
    macro_events = analysis.get("macro_events", []) or []

    # 1) 날짜별 1차 데이터
    _save(DAILY_DIR / f"{date}.json", {
        "date": date,
        "nasdaq_bias": analysis.get("nasdaq_bias", 0.0),
        "confidence": analysis.get("confidence", "약"),
        "summary": analysis.get("summary", ""),
        "ticker_events": ticker_events,
        "macro_events": macro_events,
        "n_headlines": analysis.get("n_headlines", 0),
    })

    # 2) 티커별 집계 타임라인
    for ev in ticker_events:
        tk = ev.get("ticker")
        if tk not in _TICKER_NAME:
            continue
        node = _load(GRAPH_DIR / f"{tk}.json") or {
            "ticker": tk, "name": _TICKER_NAME[tk], "events": [], "themes": {}}
        # 같은 (date, title) 중복 방지
        sig = (date, ev.get("causal_chain", "")[:40])
        if not any((e["date"], e.get("causal_chain", "")[:40]) == sig for e in node["events"]):
            node["events"].append({
                "date": date, "judgment": ev.get("judgment", "중립"),
                "theme": ev.get("theme", ""), "causal_chain": ev.get("causal_chain", "")})
            th = ev.get("theme", "")
            if th:
                node["themes"][th] = node["themes"].get(th, 0) + 1
        node["events"].sort(key=lambda e: e["date"])
        _save(GRAPH_DIR / f"{tk}.json", node)

    # 3) 공통(매크로) 집계
    if macro_events:
        macro = _load(GRAPH_DIR / "_macro.json") or {"categories": {}}
        for me in macro_events:
            cat = me.get("category", "")
            if not cat:
                continue
            c = macro["categories"].setdefault(cat, {"events": [], "up": 0, "down": 0})
            direction = me.get("direction", "")
            c["events"].append({"date": date, "direction": direction,
                                "causal_chain": me.get("causal_chain", ""),
                                "title": me.get("title", "")})
            if direction == "상승":
                c["up"] += 1
            elif direction == "하락":
                c["down"] += 1
        _save(GRAPH_DIR / "_macro.json", macro)

    rebuild_graph_index()


def rebuild_graph_index() -> dict:
    """티커/테마/매크로 파일을 읽어 노드+엣지 그래프 인덱스 재생성."""
    nodes, edges = [], []
    theme_tickers = defaultdict(set)

    for tk, name in _TICKER_NAME.items():
        node = _load(GRAPH_DIR / f"{tk}.json")
        if not node:
            continue
        ev = node.get("events", [])
        up = sum(1 for e in ev if e["judgment"] == "호재")
        dn = sum(1 for e in ev if e["judgment"] == "악재")
        nodes.append({"id": tk, "type": "ticker", "name": name,
                      "events": len(ev), "호재": up, "악재": dn})
        for th, cnt in node.get("themes", {}).items():
            theme_tickers[th].add(tk)
            edges.append({"from": tk, "to": th, "type": "theme", "weight": cnt})

    for th, tks in theme_tickers.items():
        nodes.append({"id": th, "type": "theme", "tickers": sorted(tks)})
        tl = sorted(tks)
        for i in range(len(tl)):  # 공유 테마 → 티커 간 공출현 엣지
            for j in range(i + 1, len(tl)):
                edges.append({"from": tl[i], "to": tl[j], "type": "co_theme", "via": th})

    macro = _load(GRAPH_DIR / "_macro.json")
    for cat, c in (macro.get("categories", {}) or {}).items():
        nodes.append({"id": cat, "type": "macro", "up": c.get("up", 0),
                      "down": c.get("down", 0), "events": len(c.get("events", []))})
        edges.append({"from": cat, "to": "MARKET", "type": "macro_impact",
                      "net": c.get("up", 0) - c.get("down", 0)})

    index = {"nodes": nodes, "edges": edges}
    _save(GRAPH_DIR / "_graph.json", index)
    return index


def get_daily(date: str) -> dict:
    return _load(DAILY_DIR / f"{date}.json")


def bias_map(dates: list[str]) -> dict:
    """날짜→nasdaq_bias 맵 (백테스트용). 없는 날짜는 0.0."""
    out = {}
    for d in dates:
        dd = _load(DAILY_DIR / f"{d}.json")
        out[d] = dd.get("nasdaq_bias", 0.0) if dd else 0.0
    return out
