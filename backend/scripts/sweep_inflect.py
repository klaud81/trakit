#!/usr/bin/env python3
"""INFLECT_TH 스윕 (rq-02 §8.2) — 뉴스 변곡 임계값별 예측 성능 비교.

predict_backtest 의 결정론 코어를 재사용하되, news_map 은 캐시 JSON 을 직접
읽어 구성(build_range 의 6분 수집 패스 회피). INFLECT_TH 글로벌을 값마다
바꿔가며 backtest 를 돌려 방향적중·변곡 recall/precision/F1 을 표로 출력.

밴드 폭(width)은 방향/변곡과 무관(밴드 커버리지 전용)하므로 기본 TH 에서
한 번만 캘리브레이션하고 모든 스윕에 동일 적용한다.

사용:
  cd backend && python -m scripts.sweep_inflect [--days 64] [--lookback 20]
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import scripts.predict_backtest as pb  # noqa: E402
from services.price_service import get_overseas_daily  # noqa: E402

CACHE = BACKEND_DIR.parent / "data" / "news_bias_cache"
TH_GRID = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]


def load_news_map() -> dict:
    out = {}
    for f in sorted(glob.glob(str(CACHE / "*.json"))):
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
        out[d["date"]] = d
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=64, help="백테스트 거래일 수")
    ap.add_argument("--lookback", type=int, default=20)
    ap.add_argument("--rhorizon", type=int, default=3)
    args = ap.parse_args()

    hist = get_overseas_daily("TQQQ", days=max(160, args.days + args.lookback + 60))
    news_map = load_news_map()
    if not news_map:
        print("❌ 뉴스 캐시 없음")
        return 1
    # 캐시가 커버하는 D-1 날짜와 hist 교집합 기준으로 실효 평가일 산정
    nd = sorted(news_map)
    avg = np.mean([abs(v.get("nasdaq_bias", 0.0)) for v in news_map.values()])
    strong = sum(1 for v in news_map.values() if abs(v.get("nasdaq_bias", 0.0)) >= 0.40)
    print(f"📈 TQQQ {len(hist)}행 (~{hist[-1]['date']}) · 📰 뉴스 {len(news_map)}일 "
          f"({nd[0]}~{nd[-1]}) 평균|bias| {avg:.2f} · 강신호(≥0.40) {strong}일\n")

    # width 1회 캘리브 (기본 TH)
    width = pb.calibrate(hist, args.days, args.lookback, news_map)
    print(f"🎛  밴드 폭 배수 = {width} (고정)\n")

    print(f"{'TH':>5} | {'방향적중':>8} | {'변곡recall':>10} {'precision':>10} {'F1':>6} | "
          f"{'예측반전':>8} {'적중':>5}")
    print("─" * 72)
    base = pb.INFLECT_TH
    rows = []
    for th in TH_GRID:
        pb.INFLECT_TH = th
        r = pb.backtest(hist, args.days, args.lookback, width, news_map, rhorizon=args.rhorizon)
        if not r["rows"]:
            continue
        rec = r["rev_recall"]
        prec = r["rev_prec"]
        f1 = (2 * rec * prec / (rec + prec)) if (rec and prec) else 0.0
        npr = r["n_pred_rev"]
        nhit = int(round((prec or 0) * npr))
        rows.append((th, r["dir_hit"], rec, prec, f1, npr, nhit, r["n_reversal"]))
        rs = f"{rec*100:.0f}%" if rec is not None else "—"
        ps = f"{prec*100:.0f}%" if prec is not None else "—"
        print(f"{th:>5.2f} | {r['dir_hit']*100:>7.1f}% | {rs:>10} {ps:>10} {f1:>5.2f} | "
              f"{npr:>8} {nhit:>5}")
    pb.INFLECT_TH = base
    print("─" * 72)
    if rows:
        n_rev = rows[0][7]
        print(f"실제 반전일: {n_rev}일 / 평가 {args.days}일  ·  기준 방향적중 50%")
        best = max(rows, key=lambda x: x[4])
        print(f"\n🏆 F1 최대: TH={best[0]:.2f} (recall {best[2]*100:.0f}% · "
              f"precision {best[3]*100:.0f}% · F1 {best[4]:.2f} · 방향 {best[1]*100:.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
