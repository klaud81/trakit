"""백테스팅 서비스"""
import math
from typing import Optional
import pandas as pd
from core.models import SignalType
from core.data_loader import load_base_sheet
from core.rebalancing_engine import determine_signal


def _safe_float(val, default=0):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def run_backtest(
    start_week: Optional[int] = None,
    end_week: Optional[int] = None,
) -> dict:
    """과거 데이터로 밸류 리밸런싱 백테스트 실행 - dict 반환"""
    df = load_base_sheet()
    valid = df[df["price"].notna()].copy()

    if start_week:
        valid = valid[valid["week_num"] >= start_week]
    if end_week:
        valid = valid[valid["week_num"] <= end_week]

    if valid.empty:
        raise ValueError("백테스트할 데이터가 없습니다")

    buy_count = 0
    sell_count = 0
    hold_count = 0
    total_trades = 0
    total_contributions = 0.0
    equity_curve = []

    first = valid.iloc[0]
    initial_value = _safe_float(first["valuation"]) + _safe_float(first["pool"])

    for _, row in valid.iterrows():
        valuation = _safe_float(row["valuation"])
        pool = _safe_float(row["pool"])
        target_v = _safe_float(row["target_value"])
        min_b = _safe_float(row["min_band"])
        max_b = _safe_float(row["max_band"])
        contribution = _safe_float(row["contribution"])
        trade_amount = _safe_float(row["trade_amount"])

        total_contributions += contribution

        if min_b > 0 and max_b > 0 and valuation > 0:
            signal, _ = determine_signal(valuation, min_b, max_b, target_v)
            if signal == SignalType.BUY:
                buy_count += 1
            elif signal == SignalType.SELL:
                sell_count += 1
            else:
                hold_count += 1

            if trade_amount != 0:
                total_trades += 1

        equity_curve.append({
            "week": int(row["week_num"]) if pd.notna(row["week_num"]) else 0,
            "valuation": round(valuation, 2),
            "pool": round(pool, 2),
            "total": round(valuation + pool, 2),
            "target": round(target_v, 2),
            "min": round(min_b, 2),
            "max": round(max_b, 2),
        })

    last = valid.iloc[-1]
    final_value = _safe_float(last["valuation"]) + _safe_float(last["pool"])
    total_return_pct = ((final_value - initial_value) / initial_value * 100) if initial_value > 0 else 0

    return {
        "start_week": int(valid.iloc[0]["week_num"]),
        "end_week": int(last["week_num"]),
        "total_weeks": len(valid),
        "total_trades": total_trades,
        "buy_count": buy_count,
        "sell_count": sell_count,
        "hold_count": hold_count,
        "initial_value": round(initial_value, 2),
        "final_value": round(final_value, 2),
        "total_return_pct": round(total_return_pct, 2),
        "total_contributions": round(total_contributions, 2),
        "equity_curve": equity_curve,
    }
