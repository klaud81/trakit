"""매매 시그널 생성기"""
from datetime import datetime
from typing import Optional
from core.models import Signal, SignalType, Portfolio
from core.rebalancing_engine import determine_signal


def generate_signal(
    portfolio,
    current_price: Optional[float] = None,
) -> dict:
    """현재 포트폴리오 상태에서 매매 시그널 생성. portfolio는 dict 또는 Portfolio 모델"""

    # dict/모델 양쪽 지원
    def _get(key):
        if isinstance(portfolio, dict):
            return portfolio.get(key)
        return getattr(portfolio, key, None)

    shares = _get("shares")
    valuation_orig = _get("valuation")
    min_band = _get("min_band") or 0
    max_band = _get("max_band") or 0
    target_value = _get("target_value") or 0

    # 실시간 가격이 있으면 평가금 재계산
    if current_price is not None and shares:
        valuation = current_price * shares
    else:
        valuation = valuation_orig or 0

    signal_type, confidence = determine_signal(
        valuation=valuation,
        min_band=min_band,
        max_band=max_band,
        target_value=target_value,
    )

    distance_to_buy = valuation - min_band
    distance_to_sell = max_band - valuation

    # 한글 추천 메시지 생성
    if signal_type == SignalType.BUY:
        pct = abs(distance_to_buy / min_band * 100) if min_band else 0
        recommendation = f"매수 추천: 평가금이 최소밴드 대비 {pct:.1f}% 하락. 적극 매수 구간입니다."
    elif signal_type == SignalType.SELL:
        pct = abs(distance_to_sell / max_band * 100) if max_band else 0
        recommendation = f"매도 추천: 평가금이 최대밴드 대비 {pct:.1f}% 상승. 일부 매도를 고려하세요."
    else:
        band_range = max_band - min_band
        if band_range > 0:
            position = (valuation - min_band) / band_range * 100
        else:
            position = 50
        recommendation = f"홀드: 밴드 내 {position:.0f}% 위치. 현재 상태 유지하세요."

    return {
        "signal_type": signal_type.value,
        "confidence": round(confidence, 4),
        "current_valuation": round(valuation, 2),
        "target_value": round(target_value, 2),
        "min_band": round(min_band, 2),
        "max_band": round(max_band, 2),
        "distance_to_buy": round(distance_to_buy, 2),
        "distance_to_sell": round(distance_to_sell, 2),
        "recommendation": recommendation,
        "timestamp": datetime.now().isoformat(),
    }
