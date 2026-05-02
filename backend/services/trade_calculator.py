"""매매 포인트 계산 서비스"""
from typing import Optional
from core.rebalancing_engine import calculate_buy_points, calculate_sell_points
from core.data_loader import parse_trade_points
from services.portfolio_service import get_current_portfolio
from config import TRADE_UNIT


def _calc_unit_size(shares: int, min_band: float, pool: float) -> int:
    """기준 단수 = ROUND(pool / 13 / (min_band / shares) / 2) * 2"""
    if shares <= 0 or min_band <= 0:
        return TRADE_UNIT
    buy_price = min_band / shares  # C5 = 매수점(최소값/잔여갯수)
    unit = round(pool / 13 / buy_price / 2) * 2  # D4/13/C5/2 * 2
    return max(1, unit)


def _build_table(shares, min_band, max_band, pool, unit, consumption_rate=0.5):
    """매수/매도 테이블 전체 데이터 구성 (헤더 행 + 데이터 행)"""
    buy_raw = calculate_buy_points(
        current_shares=shares,
        min_band=min_band,
        pool=pool,
        unit_size=unit,
        consumption_rate=consumption_rate,
    )
    buy_count = len(buy_raw)
    sell_raw = calculate_sell_points(
        current_shares=shares,
        max_band=max_band,
        pool=pool,
        unit_size=unit,
        max_points=buy_count,
    )

    buy_table = {
        "header": {
            "label": "최소값",
            "band": round(min_band, 2),
            "shares": shares,
            "pool": round(pool, 2),
        },
        "rows": buy_raw,
    }
    sell_table = {
        "header": {
            "label": "최대값",
            "band": round(max_band, 2),
            "shares": shares,
            "pool": round(pool, 2),
        },
        "rows": sell_raw,
    }
    return buy_table, sell_table, buy_count


def get_trade_points(current_price: Optional[float] = None) -> dict:
    """현재 포트폴리오 기반 매수/매도 포인트 계산"""
    portfolio = get_current_portfolio(current_price)
    unit = _calc_unit_size(portfolio["shares"], portfolio["min_band"], portfolio["pool"])
    consumption_rate = portfolio.get("consumption_rate") or 0.5
    buy_table, sell_table, count = _build_table(
        portfolio["shares"], portfolio["min_band"], portfolio["max_band"],
        portfolio["pool"], unit, consumption_rate=consumption_rate,
    )
    return {
        "buy_table": buy_table,
        "sell_table": sell_table,
        "unit_size": unit,
        "count": count,
    }


def get_trade_points_by_params(
    shares: int, min_band: float, max_band: float, pool: float, unit: Optional[int] = None
) -> dict:
    """파라미터 기반 매수/매도 포인트 계산 (주차 이동 시 사용)"""
    if unit is None or unit <= 0:
        unit = _calc_unit_size(shares, min_band, pool)
    buy_table, sell_table, count = _build_table(
        shares, min_band, max_band, pool, unit,
    )
    return {
        "buy_table": buy_table,
        "sell_table": sell_table,
        "unit_size": unit,
        "count": count,
    }


def get_saved_trade_points() -> dict:
    """CSV에서 저장된 매매 포인트 로딩"""
    buy_raw, sell_raw, settings = parse_trade_points()
    return {
        "buy_points": buy_raw,
        "sell_points": sell_raw,
        "settings": settings,
    }
