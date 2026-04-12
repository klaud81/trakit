"""포트폴리오 상태 서비스"""
import math
import re
from datetime import datetime, date
from typing import Optional
import pandas as pd
from core.models import Portfolio
from core.data_loader import load_base_sheet, get_latest_week
from config import GOAL_KRW, DEFAULT_EXCHANGE_RATE, GOAL_WEEK


def _parse_date_range_end(date_range: str) -> Optional[date]:
    """date_range에서 종료일 파싱 ('2026/3/23-4/3' → 2026-04-03)"""
    if not date_range or date_range == 'nan':
        return None
    try:
        # "2026/3/23-4/3" or "2025/12/29-1/9"
        parts = date_range.split('-')
        if len(parts) < 2:
            return None
        start_part = parts[0].strip()  # "2026/3/23"
        end_part = parts[1].strip()    # "4/3"

        # 시작일에서 년도 추출
        start_tokens = start_part.split('/')
        year = int(start_tokens[0])
        start_month = int(start_tokens[1])

        # 종료일 파싱
        end_tokens = end_part.split('/')
        end_month = int(end_tokens[0])
        end_day = int(end_tokens[1])

        # 연도 넘김 처리 (12월→1월)
        end_year = year + 1 if end_month < start_month else year
        return date(end_year, end_month, end_day)
    except (ValueError, IndexError):
        return None


def _safe_float(val, default=None):
    """pandas NaN 안전 변환"""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_int(val, default=None):
    """pandas NaN 안전 변환 (int)"""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def _week_str(val):
    """week_num을 문자열로 반환 (204-1, 258 등)"""
    s = str(val).strip()
    if s in ("nan", "None", ""):
        return "0"
    return s


def _week_num_int(val):
    """week_num 문자열에서 숫자 부분만 추출 (204-1 -> 204, 258 -> 258)"""
    s = str(val).strip()
    m = re.match(r"(\d+)", s)
    return int(m.group(1)) if m else 0


def _filter_by_date(df: pd.DataFrame) -> pd.DataFrame:
    """현재 날짜 기준으로 종료일이 지나지 않은 미래 데이터 제외 (진행 중 주차는 포함)"""
    today = date.today()
    mask = []
    for _, row in df.iterrows():
        dr = str(row["date_range"]) if pd.notna(row["date_range"]) else ""
        start_date = _parse_date_range_start(dr)
        if start_date and start_date > today:
            mask.append(False)
        else:
            mask.append(True)
    return df[mask]


def _parse_date_range_start(date_range: str) -> Optional[date]:
    """date_range에서 시작일 파싱 ('2026/3/23-4/3' → 2026-03-23)"""
    if not date_range or date_range == 'nan':
        return None
    try:
        start_part = date_range.split('-')[0].strip()
        tokens = start_part.split('/')
        return date(int(tokens[0]), int(tokens[1]), int(tokens[2]))
    except (ValueError, IndexError):
        return None


def get_current_portfolio(current_price: Optional[float] = None) -> dict:
    """현재 포트폴리오 상태 계산 - dict로 반환하여 JSON 직렬화 안전"""
    df = load_base_sheet()

    # 가격 데이터가 있고, 시작일이 오늘 이전인 행만
    valid = df[df["price"].notna()]
    valid = _filter_by_date(valid)
    if valid.empty:
        raise ValueError("포트폴리오 데이터가 없습니다")

    last = valid.iloc[-1]

    price = current_price if current_price else float(last["price"])
    shares = int(last["shares"])
    valuation = price * shares
    pool = _safe_float(last["pool"], 0)
    target_value = _safe_float(last["target_value"], 0)
    min_band = _safe_float(last["min_band"], 0)
    max_band = _safe_float(last["max_band"], 0)
    g = _safe_int(last["g"], 11)
    total_value = valuation + pool

    # 목표 대비 진행률
    from services.exchange_rate_service import get_exchange_rate
    exchange = get_exchange_rate()
    goal_usd = GOAL_KRW / exchange["rate"]
    goal_progress = (total_value / goal_usd) * 100

    avg_cost = round(float(last["avg_cost"]), 2) if pd.notna(last["avg_cost"]) else None
    profit = round((price - avg_cost) * shares, 2) if avg_cost and avg_cost > 0 else None
    profit_pct = round((price - avg_cost) / avg_cost * 100, 2) if avg_cost and avg_cost > 0 else None

    return {
        "week_num": _week_str(last["week_num"]),
        "date_range": str(last["date_range"]) if pd.notna(last["date_range"]) else None,
        "price": round(price, 2),
        "shares": shares,
        "avg_cost": avg_cost,
        "valuation": round(valuation, 2),
        "pool": round(pool, 2),
        "target_value": round(target_value, 2),
        "min_band": round(min_band, 2),
        "max_band": round(max_band, 2),
        "growth_stage": g,
        "total_value": round(total_value, 2),
        "goal_progress": round(goal_progress, 2),
        "profit": profit,
        "profit_pct": profit_pct,
        "exchange_rate": exchange["rate"],
        "updated_at": datetime.now().isoformat(),
    }


def get_portfolio_history() -> list:
    """포트폴리오 히스토리 (차트 데이터) - 현재 날짜까지만 반영"""
    df = load_base_sheet()
    valid = df[df["price"].notna()]
    valid = _filter_by_date(valid)

    history = []
    for _, row in valid.iterrows():
        valuation = _safe_float(row["valuation"], 0)
        pool = _safe_float(row["pool"], 0)
        history.append({
            "week_num": _week_str(row["week_num"]),
            "date_range": str(row["date_range"]) if pd.notna(row["date_range"]) else "",
            "price": round(_safe_float(row["price"], 0), 2),
            "shares": _safe_int(row["shares"], 0),
            "valuation": round(valuation, 2),
            "pool": round(pool, 2),
            "total": round(valuation + pool, 2),
            "target_value": round(_safe_float(row["target_value"], 0), 2),
            "min_band": round(_safe_float(row["min_band"], 0), 2),
            "max_band": round(_safe_float(row["max_band"], 0), 2),
            "avg_cost": round(_safe_float(row["avg_cost"], 0), 2) if pd.notna(row["avg_cost"]) else None,
            "g": _safe_int(row["g"]),
        })
    return history


def get_remaining_cycles() -> dict:
    """남은 적립 횟수 및 예상 정보"""
    df = load_base_sheet()
    valid = df[df["price"].notna()]
    last_week = _week_num_int(valid.iloc[-1]["week_num"])

    remaining_weeks = GOAL_WEEK - last_week
    remaining_cycles = remaining_weeks // 2

    return {
        "current_week": last_week,
        "goal_week": GOAL_WEEK,
        "remaining_weeks": remaining_weeks,
        "remaining_cycles": remaining_cycles,
        "progress_pct": round(last_week / GOAL_WEEK * 100, 1),
    }
