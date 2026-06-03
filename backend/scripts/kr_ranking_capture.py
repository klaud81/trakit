#!/usr/bin/env python3
"""KR 랭킹 장중 라이브 캡처 — 조건검색 '500억이상' (ka10172).

100m1s 미러의 kiwoom/{date}.json (거래대금 500억+ 상위 종목 랭킹)을 자체 생성.
조건검색은 실시간 전용이라 **장중(평일 09:00~15:30 KST)에 매 15분 cron** 으로 1회씩
실행하여 스냅샷을 누적한다. (장외엔 0종목 — 파일 변경 없음)

원본 참고: 100m1s-homepage/scripts/kiwoom-scraper/main.py (스냅샷 누적/스키마),
           동일 출력 스키마(date, condition_name, snapshot_count, latest_stocks,
           daily_top, accumulated_stocks) → 프론트 data-loader 무수정.
차이: 100m1s kiwoom_client 대신 trakit kiwoom_service 사용, 출력은
      frontend/public/kr-news/data/kiwoom/ (gitignore, 서버 cron in-place).

거래대금 정합: ka10172 응답의 거래대금(field 14)은 영구 부재 → 종목별 ka10081
(get_today_trade_amount, 원단위)로 보강. change_pct = field 12 ÷ 1000 (키움 스케일).

서버 cron (KST, 장중 매 15분):
  */15 9-15 * * 1-5  cd /path/to/trakit/backend && python3 -m scripts.kr_ranking_capture

env: KIWOOM_APP_KEY, KIWOOM_APP_SECRET, KIWOOM_MODE, KIWOOM_BASE_URL
사전: 영웅문에 '500억이상' 조건식이 (모의 키와 동일 키움 ID로) 클라우드 저장돼 있어야 함.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from services import kiwoom_service  # noqa: E402

KST = timezone(timedelta(hours=9))
OUT_DIR = REPO_ROOT / "frontend" / "public" / "kr-news" / "data" / "kiwoom"
CONDITION_MATCH = "500억"  # 조건식 이름 부분매칭

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("kr_ranking_capture")


def _int(v) -> int:
    if v is None or v == "":
        return 0
    s = str(v).replace("+", "").replace(",", "").strip()
    if s.startswith("-"):
        try:
            return int(s)
        except ValueError:
            return 0
    s = s.lstrip("0") or "0"
    try:
        return int(s)
    except ValueError:
        return 0


def _float(v) -> float:
    if v is None or v == "":
        return 0.0
    try:
        return float(str(v).replace("+", "").replace(",", "").strip())
    except ValueError:
        return 0.0


def parse_stock(s: dict, ka10081_ta: int | None) -> dict:
    """ka10172 응답 1건 → 표준 dict. (100m1s parse_kiwoom_stock 동형)

    필드: 9001 종목코드(A접두) / 302 명 / 10 현재가 / 11 전일대비 / 12 등락률(×1000)
          13 거래량 / 14 거래대금(영구부재) / 16 시가 / 17 고가 / 18 저가
    """
    code = str(s.get("9001", "")).lstrip("A")
    price = _int(s.get("10", ""))
    volume = _int(s.get("13", ""))
    raw14 = _int(s.get("14", "")) * 1_000_000  # 백만원→원 (영구 부재)
    if ka10081_ta is not None and ka10081_ta > 0:
        trade_amount, source = ka10081_ta, "ka10081"
    elif raw14 > 0:
        trade_amount, source = raw14, "ka10172"
    else:
        trade_amount, source = price * volume, "calc_fallback"
    return {
        "ticker": code,
        "name": str(s.get("302", "")).strip(),
        "price": price,
        "open": _int(s.get("16", "")),
        "high": _int(s.get("17", "")),
        "low": _int(s.get("18", "")),
        "change": _int(s.get("11", "")),
        "change_pct": _float(s.get("12", "")) / 1000.0,  # 키움 등락률 스케일
        "volume": volume,
        "trade_amount": trade_amount,
        "trade_amount_source": source,
    }


def merge_into_daily(daily: dict, snapshot: dict) -> None:
    """누적 종목 갱신 (그날 한 번이라도 등장한 종목). 100m1s 동형."""
    accum = daily.setdefault("accumulated_stocks", {})
    snap_time = snapshot["fetched_at"][11:16]  # HH:MM
    for st in snapshot["stocks"]:
        t = st["ticker"]
        if not t:
            continue
        if t in accum:
            ex = accum[t]
            ex["max_trade_amount"] = max(ex["max_trade_amount"], st["trade_amount"])
            ex["max_change_pct"] = max(ex["max_change_pct"], st["change_pct"])
            ex["min_change_pct"] = min(ex["min_change_pct"], st["change_pct"])
            ex["appearances"] = ex.get("appearances", 0) + 1
            ex["last_seen"] = snap_time
            ex["last_price"] = st["price"]
            if st.get("high"):
                ex["high"] = max(ex.get("high", 0), st["high"])
            if st.get("low") and st["low"] > 0:
                ex["low"] = min(ex.get("low", st["low"]), st["low"])
            if st.get("open"):
                ex["open"] = st["open"]
        else:
            accum[t] = {
                "ticker": t, "name": st["name"],
                "max_trade_amount": st["trade_amount"],
                "max_change_pct": st["change_pct"], "min_change_pct": st["change_pct"],
                "first_seen": snap_time, "last_seen": snap_time, "appearances": 1,
                "last_price": st["price"],
                "open": st.get("open", 0), "high": st.get("high", 0), "low": st.get("low", 0),
            }


def _load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(KST)
    hm = now.hour * 60 + now.minute
    if now.weekday() >= 5 or not (9 * 60 <= hm <= 15 * 60 + 35):
        logger.warning("KRX 정규장(평일 09:00~15:30 KST)이 아님 → 조건검색 0건 가능")

    if not kiwoom_service.get_token():
        logger.error("키움 토큰 발급 실패 — KIWOOM_APP_KEY/SECRET 확인")
        return 1

    conds = kiwoom_service.condition_list()
    seq = name = None
    for s, n in conds:
        if CONDITION_MATCH in n:
            seq, name = s, n
            break
    if seq is None:
        logger.error(f"'{CONDITION_MATCH}' 조건식 미등록. 등록된: {[n for _, n in conds]}")
        return 2
    logger.info(f"조건검색 실행: [{seq}] {name}")

    raw = kiwoom_service.condition_search(seq)
    logger.info(f"수신 {len(raw)}종목")
    if not raw:
        logger.info("0건 (장외 또는 매칭 없음) — 파일 변경 없음")
        return 0

    # 종목별 ka10081 거래대금 보강 (rate limit: 0.4s)
    ka_amt: dict[str, int] = {}
    for s in raw:
        code = str(s.get("9001", "")).lstrip("A")
        if not code:
            continue
        ta = kiwoom_service.get_today_trade_amount(code)
        if ta:
            ka_amt[code] = ta
        time.sleep(0.4)
    logger.info(f"ka10081 거래대금 보강 {len(ka_amt)}/{len(raw)}")

    stocks = [parse_stock(s, ka_amt.get(str(s.get("9001", "")).lstrip("A"))) for s in raw]
    stocks = [s for s in stocks if s["ticker"]]
    stocks.sort(key=lambda x: x["trade_amount"], reverse=True)
    for i, s in enumerate(stocks):
        s["rank"] = i + 1

    today = now.strftime("%Y-%m-%d")
    snap_iso = now.isoformat(timespec="seconds")
    snapshot = {"fetched_at": snap_iso, "stocks": stocks}

    # 일별 파일 누적
    daily_path = OUT_DIR / f"{today}.json"
    daily = _load(daily_path)
    if not daily:
        daily = {
            "date": today, "condition_name": name,
            "first_snapshot_at": snap_iso, "snapshot_count": 0,
            "accumulated_stocks": {},
        }
    daily["last_snapshot_at"] = snap_iso
    daily["snapshot_count"] = daily.get("snapshot_count", 0) + 1
    daily["latest_stocks"] = stocks[:30]
    merge_into_daily(daily, snapshot)
    accum_list = sorted(daily["accumulated_stocks"].values(),
                        key=lambda x: x["max_trade_amount"], reverse=True)
    daily["daily_top"] = accum_list[:50]
    daily_path.write_text(json.dumps(daily, ensure_ascii=False, indent=2), encoding="utf-8")

    # latest.json
    (OUT_DIR / "latest.json").write_text(json.dumps({
        "date": today, "fetched_at": snap_iso,
        "snapshot_count": daily["snapshot_count"], "stocks": stocks[:30],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # index.json
    idx_path = OUT_DIR / "index.json"
    idx = _load(idx_path)
    idx.setdefault("dates", [])
    if today not in idx["dates"]:
        idx["dates"].insert(0, today)
        idx["dates"] = idx["dates"][:90]
    idx["updated_at"] = snap_iso
    idx_path.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info(f"✓ {today} 스냅샷 #{daily['snapshot_count']} 저장 ({len(stocks)}종목)")
    # 토큰 폐기 안 함 (kiwoom_service 디스크 캐시 재사용)
    return 0


if __name__ == "__main__":
    sys.exit(main())
