"""회차기록(T열) 자동 업데이트 — 시트 쓰기 (서비스계정).

TQQQ 실시간 세션 고저가(사전장+정규장 intraday min~max)를 조회해,
매수/매도 tier 가격이 그 범위에 들어오면(= 체결 간주) 현재 주차 행의
회차기록(T열) 에 기록한다. **매도는 + 부호, 매수는 − 부호.** 기록 후 시트 캐시 refresh.

읽기는 기존 공개 CSV 경로(data_loader)를 그대로 쓰고, **쓰기만** 서비스계정
(GOOGLE_SA_JSON)으로 수행한다. 시트는 서비스계정 이메일에 편집자로 공유돼 있어야 함.

사용:
  python -m services.sheets_writer            # 드라이런(미리보기, 쓰기 없음)
  python -m services.sheets_writer --apply    # 실제 쓰기 + refresh
또는 코드에서:  from services.sheets_writer import update_cycle_record
"""
from __future__ import annotations
import logging
from typing import Optional

import requests
import gspread
from google.oauth2.service_account import Credentials

from config import GOOGLE_SA_KEY, GOOGLE_SA_JSON, GOOGLE_SHEET_ID, SYMBOL
from services.portfolio_service import get_current_portfolio
from services.trade_calculator import get_trade_points
from services.price_service import get_current_price
from core.data_loader import refresh_base_sheet

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_HDR_CYCLE = "회차기록"
_HDR_WEEK = "주차"
_gc = None


def _client():
    global _gc
    if _gc is None:
        if GOOGLE_SA_KEY:  # .env 에 JSON 내용 직접 포함 (우선)
            import json as _json
            creds = Credentials.from_service_account_info(_json.loads(GOOGLE_SA_KEY), scopes=_SCOPES)
        else:  # 파일 경로 폴백
            creds = Credentials.from_service_account_file(GOOGLE_SA_JSON, scopes=_SCOPES)
        _gc = gspread.authorize(creds)
    return _gc


def _worksheet():
    return _client().open_by_key(GOOGLE_SHEET_ID).sheet1


def _fmt(p: float) -> str:
    """가격 표기 (불필요한 0 제거): 57.0→'57', 57.17→'57.17'."""
    return f"{round(float(p), 2):g}"


def session_min_max(symbol: str = SYMBOL) -> Optional[tuple[float, float]]:
    """사전장+정규장 intraday 최저가~최고가 (Yahoo includePrePost 1분봉 high/low).

    실패 시 price_service 의 day_low/day_high 로 폴백.
    """
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        params = {"interval": "1m", "range": "1d", "includePrePost": "true"}
        r = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        r.raise_for_status()
        q = r.json()["chart"]["result"][0]["indicators"]["quote"][0]
        highs = [h for h in (q.get("high") or []) if h is not None]
        lows = [l for l in (q.get("low") or []) if l is not None]
        if highs and lows:
            return round(min(lows), 2), round(max(highs), 2)
    except Exception as e:
        logger.warning(f"session_min_max intraday 실패, 폴백: {e}")
    px = get_current_price() or {}
    lo, hi = px.get("day_low"), px.get("day_high")
    if lo and hi:
        return float(lo), float(hi)
    return None


def update_cycle_record(dry_run: bool = True) -> dict:
    """세션 범위 내 체결 tier 를 회차기록(T열)에 기록. 반환: 결과 dict.

    dry_run=True 면 미리보기만(쓰기·refresh 없음).
    """
    ws = _worksheet()
    header = ws.row_values(1)
    try:
        cyc_col = header.index(_HDR_CYCLE) + 1
        week_col = header.index(_HDR_WEEK) + 1
    except ValueError as e:
        return {"ok": False, "error": f"헤더 없음: {e}"}

    # 1) 현재 주차
    pf = get_current_portfolio() or {}
    week = str(pf.get("week_num") or "").strip()
    if not week:
        return {"ok": False, "error": "현재 주차(week_num) 확인 실패", "portfolio": pf}

    # 2) 매수/매도 tier 가격
    tp = get_trade_points() or {}
    buys = [float(r["price"]) for r in (tp.get("buy_table", {}).get("rows") or []) if r.get("price")]
    sells = [float(r["price"]) for r in (tp.get("sell_table", {}).get("rows") or []) if r.get("price")]

    # 3) 세션 고저가 (사전장+정규장)
    rng = session_min_max()
    if not rng:
        return {"ok": False, "error": "세션 고저가(day_low/high) 조회 실패"}
    lo, hi = rng

    # 4) 범위 포함 tier = 체결. 매도=양수(부호 없음), 매수=음수(- 부호)
    sell_hit = sorted(p for p in sells if lo <= p <= hi)
    buy_hit = sorted((p for p in buys if lo <= p <= hi), reverse=True)
    new_entries = [f"{_fmt(p)}" for p in sell_hit] + [f"-{_fmt(p)}" for p in buy_hit]

    base = {"week": week, "range": [lo, hi], "sell_hit": sell_hit, "buy_hit": buy_hit}
    if not new_entries:
        return {"ok": True, "updated": False, "reason": "범위 내 체결 tier 없음", **base}

    # 5) 현재 주차 행 찾기 (주차 컬럼 = "268 주차" 형식 → 접미사 제거 후 매칭)
    def _norm(v: str) -> str:
        return str(v).replace("주차", "").strip()

    week_vals = ws.col_values(week_col)
    row = next((i + 1 for i, v in enumerate(week_vals) if i > 0 and _norm(v) == week), None)
    if not row:
        return {"ok": False, "error": f"주차 {week} 행을 시트에서 못 찾음", **base}

    # 6) 기존 회차기록 + 중복 제거 후 병합
    existing = (ws.cell(row, cyc_col).value or "").strip()
    parts = [x for x in existing.split("|") if x.strip()]
    have = set(parts)
    added = [e for e in new_entries if e not in have]
    if not added:
        return {"ok": True, "updated": False, "reason": "이미 기록됨", "existing": existing, **base}
    merged = "|".join(parts + added)

    result = {"ok": True, "updated": True, "row": row, "cycle_col": cyc_col,
              "existing": existing, "added": added, "merged": merged, "dry_run": dry_run, **base}
    if dry_run:
        return result

    # 7) 실제 쓰기 + refresh
    # raw=True (value_input_option=RAW): '+'/'-' 로 시작해도 수식 파싱 안 함 (텍스트 저장)
    from gspread.utils import rowcol_to_a1
    ws.update([[merged]], rowcol_to_a1(row, cyc_col), raw=True)
    logger.info(f"💾 회차기록 갱신 (주차 {week}, 행 {row}): {existing!r} → {merged!r}")
    refresh_base_sheet()
    result["refreshed"] = True
    return result


if __name__ == "__main__":
    import argparse
    import json as _json

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        datefmt="%Y-%m-%dT%H:%M:%S%z")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="실제 쓰기+refresh (기본=드라이런)")
    args = ap.parse_args()
    res = update_cycle_record(dry_run=not args.apply)
    print(_json.dumps(res, ensure_ascii=False, indent=2))
