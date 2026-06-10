#!/usr/bin/env python3
"""TQQQ 일간 예측 — 최근 20일 백테스트 & 캘리브레이션.

목적: 라이브 배포 전, 과거 N거래일에 대해 예측 코어를 돌려보고 정확도를
측정·튜닝한다. (뉴스는 과거 소급 재구성 불가 → 백테스트는 가격/기술+매크로
기반 결정론적 코어만. 뉴스 Gemini 오버레이는 라이브 전용.)

예측 산출(하루):
  - regime  : 흐름 주도 (상승흐름/하락흐름/중립)  ← 다일 추세 레짐
  - direction: 다음날 방향 (상승/하락)              ← 1일 모멘텀
  - band    : P20~P80 등락폭 밴드                    ← 장중 저가20%/고가80% 분위수
              (전일종가 기준 저/고 상대수익률 경험분위수 × 캘리브레이션 폭)

채점:
  - direction_hit : 실제 종가 방향 일치
  - regime_hit    : 레짐이 이후 추세와 부호 일치(근사: 당일+익일 수익 부호)
  - band_cover    : 실제 종가가 [P20, P80] 안에 들어옴 (목표 커버리지 60%)
  - bias          : 밴드 중앙 대비 실제의 부호있는 평균오차

캘리브레이션: 밴드 폭 배수(width multiplier)를 그리드 탐색해 커버리지를
60%에 가장 가깝게 맞춘다. (P20/P80은 정의상 60% 밴드지만 close 기준 실측
커버리지는 변동성 가정에 따라 달라 → 실측으로 보정)

사용:
  cd backend && python -m scripts.predict_backtest [--days 20] [--lookback 20]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from services.price_service import get_overseas_daily  # noqa: E402  (KIS 우선 + Yahoo fallback)

INFLECT_TH = 0.4   # 뉴스 변곡 임계: |bias|≥이 값이고 추세와 반대면 반전 예측


# ── 피처 ──────────────────────────────────────────────────────────────────
def _rsi(closes: np.ndarray, n: int = 14) -> float:
    if len(closes) < n + 1:
        return 50.0
    d = np.diff(closes[-(n + 1):])
    up = d[d > 0].sum() / n
    dn = -d[d < 0].sum() / n
    if dn == 0:
        return 100.0
    rs = up / dn
    return float(100 - 100 / (1 + rs))


def features_asof(hist: list, i: int, lookback: int) -> dict | None:
    """hist[i] 의 *전일(i-1)*까지만 사용해 i일 예측용 피처 구성 (lookahead 차단)."""
    if i < lookback + 2:
        return None
    past = hist[:i]  # i 미포함 → 당일 데이터 안 봄
    closes = np.array([r["close"] for r in past], dtype=float)
    highs = np.array([r["high"] for r in past], dtype=float)
    lows = np.array([r["low"] for r in past], dtype=float)
    prev_close = closes[-1]

    # 전일종가 기준 저/고 상대수익률 분포 (최근 lookback일)
    pc = closes[-lookback - 1:-1]            # 각 일자의 '전일 종가'
    lo = lows[-lookback:]
    hi = highs[-lookback:]
    cl = closes[-lookback:]
    low_rets = (lo - pc) / pc * 100
    high_rets = (hi - pc) / pc * 100
    close_rets = (cl - pc) / pc * 100

    ma5 = closes[-5:].mean()
    ma20 = closes[-20:].mean() if len(closes) >= 20 else closes.mean()
    ma50 = closes[-50:].mean() if len(closes) >= 50 else closes.mean()
    ma20_prev = closes[-21:-1].mean() if len(closes) >= 21 else ma20
    ma50_prev = closes[-55:-5].mean() if len(closes) >= 55 else ma50
    above20 = float(np.mean(closes[-10:] > ma20))      # 최근 10일 MA20 상회 비율(추세 일관성)
    return {
        "prev_close": prev_close,
        "low_rets": low_rets,
        "high_rets": high_rets,
        "close_rets": close_rets,
        "mom": float(close_rets[-5:].mean()),      # 최근 5일 평균 일수익(모멘텀)
        "ma5": ma5, "ma20": ma20, "ma50": ma50,
        "ma20_slope": float((ma20 - ma20_prev) / ma20_prev * 100),
        "ma50_slope": float((ma50 - ma50_prev) / ma50_prev * 100),
        "above20": above20,
        "rsi": _rsi(closes),
        "vol": float(close_rets.std()),            # 실현 변동성
    }


# ── 예측 코어 (결정론적) ───────────────────────────────────────────────────
def _build_reasons(f: dict, news: dict | None, ma_aligned: bool) -> tuple[list, list]:
    """예측 근거를 |기여도| 순 상위 3개 메타데이터로 정리 + 연관 엔티티 추출.

    반환: (reasons[≤3], related_links). reason = {factor, score, related[]}.
    related_links = 둘 이상 근거에 공출현하거나 그래프 공유테마로 엮인 엔티티 그룹.
    """
    cand = []
    # 1) 기술 모멘텀/추세
    tech = f["mom"] + (1.0 if ma_aligned else -1.0)
    cand.append({"factor": f"기술: 모멘텀 {f['mom']:+.1f}%, MA {'정배열' if ma_aligned else '역배열'}",
                 "score": round(tech, 2), "related": []})
    if news:
        # 2) 종목 뉴스
        pt = news.get("per_ticker", {}) or {}
        up = [t for t, j in pt.items() if j == "호재"]
        dn = [t for t, j in pt.items() if j == "악재"]
        if up or dn:
            cand.append({"factor": f"종목뉴스: 호재 {up or '-'} / 악재 {dn or '-'}",
                         "score": round(news.get("nasdaq_bias", 0.0) * 2, 2),
                         "related": up + dn})
        # 3) 공통 매크로
        me = news.get("macro_events", []) or []
        if me:
            cats = {}
            for m in me:
                c = m.get("category", "")
                d = 1 if m.get("direction") == "상승" else -1 if m.get("direction") == "하락" else 0
                cats[c] = cats.get(c, 0) + d
            tag = ", ".join(f"{c}{'↑' if v > 0 else '↓' if v < 0 else '·'}" for c, v in cats.items())
            cand.append({"factor": f"매크로: {tag}", "score": round(sum(cats.values()) * 0.5, 2),
                         "related": list(cats.keys())})
        # 테마(이벤트) 연관
        for ev in news.get("events", []) or []:
            th = ev.get("theme", "")
            if th and ev.get("ticker"):
                cand.append({"factor": f"테마: {th} ({ev['ticker']})", "score": 0.0,
                             "related": [ev["ticker"], th]})
    # |기여도| 큰 순 상위 3
    reasons = sorted([c for c in cand if c["score"] != 0 or c["related"]],
                     key=lambda c: -abs(c["score"]))[:3]
    # 연관: 근거들 간 공유 엔티티
    seen, links = {}, []
    for r in reasons:
        for e in r["related"]:
            seen.setdefault(e, 0)
            seen[e] += 1
    shared = [e for e, c in seen.items() if c >= 2]
    if shared:
        links.append({"shared": shared, "note": "복수 근거 공출현"})
    return reasons, links


def predict_core(f: dict, width: float, bias: float = 0.0, news: dict | None = None,
                 bias_w_dir: float = 2.0, bias_w_band: float = 0.5) -> dict:
    if news is not None:
        bias = news.get("nasdaq_bias", 0.0)
    pc = f["prev_close"]
    # 밴드: 저가 P20 / 고가 P80 경험분위수 × 폭 배수, 뉴스 bias 로 중앙 시프트
    shift = bias * bias_w_band  # %p
    lo_p = float(np.percentile(f["low_rets"], 20)) * width + shift
    hi_p = float(np.percentile(f["high_rets"], 80)) * width + shift
    band_low = round(pc * (1 + lo_p / 100), 2)
    band_high = round(pc * (1 + hi_p / 100), 2)

    # 방향: 기술(모멘텀+MA) 추세 + 뉴스 변곡 오버라이드
    ma_aligned = f["ma5"] > f["ma20"]
    tech_score = f["mom"] + (1.0 if ma_aligned else -1.0)   # 뉴스 제외 추세 신호
    tech_up = tech_score >= 0
    # 변곡점: 뉴스 bias 가 추세와 '강하게' 반대면 반전 예측 (continuation 은 모멘텀에 맡김)
    inflection = None
    if abs(bias) >= INFLECT_TH:
        if tech_up and bias <= -INFLECT_TH:
            inflection, direction = "상승→하락", "하락"
        elif (not tech_up) and bias >= INFLECT_TH:
            inflection, direction = "하락→상승", "상승"
    if inflection is None:
        direction = "상승" if (tech_score + bias * bias_w_dir) >= 0 else "하락"

    # 흐름 주도(레짐): MA 정배열/역배열 + MA20 기울기 (다일 추세 신호)
    bull = (f["ma5"] > f["ma20"] > f["ma50"]) or (f["prev_close"] > f["ma20"] and f["ma20_slope"] > 0.05)
    bear = (f["ma5"] < f["ma20"] < f["ma50"]) or (f["prev_close"] < f["ma20"] and f["ma20_slope"] < -0.05)
    if bull and not bear:
        regime = "상승흐름"
    elif bear and not bull:
        regime = "하락흐름"
    else:
        regime = "중립"

    reasons, links = _build_reasons(f, news, ma_aligned)
    return {
        "regime": regime, "direction": direction,
        "band_low": band_low, "band_high": band_high,
        "low_pct": round(lo_p, 2), "high_pct": round(hi_p, 2),
        "reasons": reasons, "related": links, "inflection": inflection,
        "tech_up": tech_up,
    }


# ── 백테스트 ───────────────────────────────────────────────────────────────
def backtest(hist: list, days: int, lookback: int, width: float,
             news_map: dict | None = None, rhorizon: int = 3) -> dict:
    n = len(hist)
    rows = []
    for i in range(n - days, n):
        f = features_asof(hist, i, lookback)
        if f is None:
            continue
        # D일 예측은 D-1(전 거래일) 뉴스만 사용 (lookahead 차단)
        news = (news_map or {}).get(hist[i - 1]["date"])
        p = predict_core(f, width, news=news)
        actual = hist[i]
        prev = hist[i - 1]["close"]
        act_pct = (actual["close"] - prev) / prev * 100
        act_dir = "상승" if actual["close"] >= prev else "하락"
        # 레짐(흐름) 채점: 예측일 포함 향후 rhorizon 거래일 추세 (다일 지속성)
        fwd_i = min(i + rhorizon - 1, n - 1)
        trend_pct = (hist[fwd_i]["close"] - prev) / prev * 100
        FLAT = 1.0  # 중립 판정 임계(±1% 이내면 횡보)
        regime_hit = ((p["regime"] == "상승흐름" and trend_pct > 0)
                      or (p["regime"] == "하락흐름" and trend_pct < 0)
                      or (p["regime"] == "중립" and abs(trend_pct) <= FLAT))
        band_mid = (p["band_low"] + p["band_high"]) / 2
        # 실제 변곡: 기술추세와 실제 방향이 반대인 날 (continuation 의 반대)
        actual_reversal = (p["tech_up"] and act_dir == "하락") or (not p["tech_up"] and act_dir == "상승")
        rows.append({
            "date": actual["date"],
            "dir_pred": p["direction"], "dir_hit": p["direction"] == act_dir,
            "regime": p["regime"], "regime_hit": regime_hit,
            "cover": p["band_low"] <= actual["close"] <= p["band_high"],
            "act_pct": act_pct,
            "bias": (actual["close"] - band_mid) / prev * 100,
            "band": (p["band_low"], p["band_high"]),
            "low_pct": p["low_pct"], "high_pct": p["high_pct"],
            "reasons": p["reasons"], "related": p["related"],
            "inflection": p["inflection"], "pred_reversal": p["inflection"] is not None,
            "actual_reversal": actual_reversal,
        })
    if not rows:
        return {"rows": []}
    dir_hit = np.mean([r["dir_hit"] for r in rows])
    reg_hit = np.mean([r["regime_hit"] for r in rows])
    cover = np.mean([r["cover"] for r in rows])
    bias = np.mean([r["bias"] for r in rows])
    # 변곡점 포착: 실제 반전일 중 예측한 비율(recall) / 예측 반전 중 실제(precision)
    act_rev = [r for r in rows if r["actual_reversal"]]
    pred_rev = [r for r in rows if r["pred_reversal"]]
    hit_rev = [r for r in rows if r["pred_reversal"] and r["actual_reversal"]]
    rev_recall = len(hit_rev) / len(act_rev) if act_rev else None
    rev_prec = len(hit_rev) / len(pred_rev) if pred_rev else None
    return {"rows": rows, "dir_hit": dir_hit, "regime_hit": reg_hit,
            "cover": cover, "bias": bias, "width": width, "n": len(rows),
            "n_reversal": len(act_rev), "n_pred_rev": len(pred_rev),
            "rev_recall": rev_recall, "rev_prec": rev_prec}


def calibrate(hist: list, days: int, lookback: int, news_map: dict | None = None) -> float:
    """밴드 폭 배수를 그리드 탐색 → 커버리지를 60%에 가장 근접."""
    best, best_err = 1.0, 1e9
    for w in np.arange(0.3, 2.01, 0.05):
        r = backtest(hist, days, lookback, float(w), news_map)
        if not r["rows"]:
            continue
        err = abs(r["cover"] - 0.60)
        if err < best_err:
            best_err, best = err, float(w)
    return round(best, 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=20, help="백테스트 거래일 수")
    ap.add_argument("--lookback", type=int, default=20, help="분위수/모멘텀 룩백")
    ap.add_argument("--width", type=float, default=None, help="밴드 폭 배수(미지정 시 자동 캘리브)")
    ap.add_argument("--news", action="store_true", help="뉴스 bias 사용(나스닥 top5+매크로 지식그래프)")
    ap.add_argument("--rhorizon", type=int, default=3, help="레짐 채점 전방 거래일 수")
    args = ap.parse_args()

    hist = get_overseas_daily("TQQQ", days=max(130, args.days + args.lookback + 60))
    if len(hist) < args.days + args.lookback + 5:
        print(f"❌ 데이터 부족: {len(hist)}행")
        return 1
    print(f"📈 TQQQ {len(hist)}행 (~{hist[-1]['date']}) 로드")

    news_map = None
    if args.news:
        from services.nasdaq_news import build_range
        # 예측 D 는 D-1 뉴스를 쓰므로 백테스트 구간의 '전 거래일'들 날짜 수집
        need = [hist[i - 1]["date"] for i in range(len(hist) - args.days, len(hist))]
        news_map = build_range(need)
        avg = np.mean([abs(v.get("nasdaq_bias", 0.0)) for v in news_map.values()])
        print(f"📰 뉴스 적용: {len(news_map)}일 (평균 |bias| {avg:.2f})\n")

    width = args.width if args.width else calibrate(hist, args.days, args.lookback, news_map)
    print(f"🎛  밴드 폭 배수 = {width} (목표 커버리지 60%)\n")

    r = backtest(hist, args.days, args.lookback, width, news_map, rhorizon=args.rhorizon)
    print(f"{'날짜':<12}{'레짐':<7}{'방향':<5}{'실제%':>7} {'밴드':>16} {'적중':>10}")
    print("─" * 64)
    for x in r["rows"]:
        bl, bh = x["band"]
        flags = ("방" if x["dir_hit"] else "·") + ("밴" if x["cover"] else "·") + ("흐" if x["regime_hit"] else "·")
        print(f"{x['date']:<12}{x['regime']:<7}{x['dir_pred']:<5}{x['act_pct']:>+6.2f}% "
              f"{bl:>7.2f}~{bh:<7.2f} {flags:>10}")
    print("─" * 64)
    print(f"방향 적중 : {r['dir_hit']*100:>5.1f}%  ({sum(x['dir_hit'] for x in r['rows'])}/{r['n']})  [기준 50%]")
    print(f"흐름 적중 : {r['regime_hit']*100:>5.1f}%")
    print(f"밴드 커버 : {r['cover']*100:>5.1f}%  [목표 60%]")
    print(f"폭 편향   : {r['bias']:>+5.2f}%p  (양수=실제가 밴드중앙보다 위)")
    # 변곡점 포착 (뉴스의 핵심 가치)
    rr = f"{r['rev_recall']*100:.0f}%" if r['rev_recall'] is not None else "—"
    rp = f"{r['rev_prec']*100:.0f}%" if r['rev_prec'] is not None else "—"
    print(f"변곡 포착 : recall {rr} (실제반전 {r['n_reversal']}일 중 예측)"
          f" · precision {rp} (예측반전 {r['n_pred_rev']}일 중 적중)")

    # 예측 근거 메타데이터(상위 3) + 연관 — 최근 3일 샘플
    print("\n[예측 근거 메타데이터 — 최근 3일]")
    for x in r["rows"][-3:]:
        print(f"· {x['date']} {x['dir_pred']}:")
        for rs in x["reasons"]:
            rel = f"  ↔연관 {rs['related']}" if rs["related"] else ""
            print(f"    - {rs['factor']} (기여 {rs['score']:+.2f}){rel}")
        if x["related"]:
            print(f"    ⚡ {x['related']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
