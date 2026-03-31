"""밸류 리밸런싱 핵심 엔진

핵심 메커니즘:
- 목표 가치 경로(V): 시간에 따라 증가하는 목표 포트폴리오 가치
- 밴드 설정: V 기준 최소/최대 밴드
- 리밸런싱 로직:
    - 평가금 < 최소 → 매수
    - 평가금 > 최대 → 매도
    - 최소 ≤ 평가금 ≤ 최대 → 홀드
"""
import math
from typing import Optional, Tuple
from core.models import SignalType
from config import GROWTH_STAGES, CONTRIBUTION_PER_CYCLE


def calculate_two_sqrt_g(g: int) -> float:
    """성장 구간에 따른 2/√G 계산"""
    if g in GROWTH_STAGES:
        return GROWTH_STAGES[g]["two_sqrt_g"]
    return 2.0 / math.sqrt(g)


def calculate_target_value(
    prev_v: float,
    contribution: float,
    two_sqrt_g: float,
) -> float:
    """목표 가치(V) 계산

    V_new = V_prev × (1 + 2/√G × contribution / V_prev)
    실질적으로는 시간 가중 성장률을 적용하는 방식
    """
    if prev_v <= 0:
        return contribution
    growth_rate = two_sqrt_g * contribution / prev_v
    return prev_v * (1 + growth_rate / 100)


def calculate_bands(
    target_value: float,
    two_sqrt_g: float,
) -> Tuple[float, float]:
    """최소/최대 밴드 계산

    스프레드시트 분석에 따르면:
    - 최소 = V × (1 - band_width)
    - 최대 = V × (1 + band_width)
    band_width는 약 15~17% 범위
    """
    # 실제 데이터에서 역산한 밴드 비율
    # 최소: V × 0.83 ~ 0.85, 최대: V × 1.15 ~ 1.23
    # 분석 결과: 최소 = V × (1 - 2/√G/10), 최대 = V × (1 + 2/√G/10 × 1.35)
    band_factor = two_sqrt_g / 10.0
    min_band = target_value * (1 - band_factor)
    max_band = target_value * (1 + band_factor * 1.35)
    return min_band, max_band


def determine_signal(
    valuation: float,
    min_band: float,
    max_band: float,
    target_value: float,
) -> Tuple[SignalType, float]:
    """현재 평가금에 따른 시그널 결정

    Returns:
        (signal_type, confidence)
        confidence: 0~1, 밴드 내 위치 기반
    """
    if valuation < min_band:
        # 매수 시그널 - 밴드 아래로 벗어난 정도
        distance = (min_band - valuation) / min_band
        confidence = min(distance * 5, 1.0)  # 20% 이상 벗어나면 최대
        return SignalType.BUY, confidence

    elif valuation > max_band:
        # 매도 시그널 - 밴드 위로 벗어난 정도
        distance = (valuation - max_band) / max_band
        confidence = min(distance * 5, 1.0)
        return SignalType.SELL, confidence

    else:
        # 홀드 - 밴드 중앙으로부터의 위치
        mid = (min_band + max_band) / 2
        range_half = (max_band - min_band) / 2
        if range_half > 0:
            position = abs(valuation - mid) / range_half
        else:
            position = 0
        confidence = 1.0 - position  # 중앙에 가까울수록 높은 확신
        return SignalType.HOLD, confidence


def calculate_trade_amount(
    valuation: float,
    target_value: float,
    signal: SignalType,
    pool: float,
) -> float:
    """거래 금액 계산

    매수: pool에서 차감하여 매수 (음수)
    매도: 매도하여 pool로 환입 (양수)
    """
    if signal == SignalType.HOLD:
        return 0.0

    diff = target_value - valuation

    if signal == SignalType.BUY:
        # 매수: target까지 채우되 pool 한도 내
        buy_amount = min(abs(diff), pool)
        return -buy_amount  # 음수 = 매수

    elif signal == SignalType.SELL:
        # 매도: 초과분 매도
        return abs(diff)  # 양수 = 매도

    return 0.0


def calculate_buy_points(
    current_shares: int,
    min_band: float,
    pool: float,
    unit_size: int = 10,
) -> list:
    """매수 포인트 테이블 생성

    최소값 기준으로 unit_size개씩 매수.
    pool이 초기값의 1/2 이하가 되면 중단.
    """
    points = []
    remaining_pool = pool
    half_pool = pool / 2
    shares = current_shares

    while remaining_pool > half_pool:
        buy_price = round(min_band / shares, 2)
        cost = round(buy_price * unit_size, 2)
        if remaining_pool < cost:
            break
        remaining_pool = round(remaining_pool - cost, 2)
        shares += unit_size
        points.append({
            "action": "BUY",
            "shares_after": shares,
            "price": buy_price,
            "amount": cost,
            "pool_after": remaining_pool,
        })
    return points


def calculate_sell_points(
    current_shares: int,
    max_band: float,
    pool: float,
    unit_size: int = 10,
    max_points: int = 10,
) -> list:
    """매도 포인트 테이블 생성

    최대값 기준으로 unit_size개씩 매도.
    max_points(매수 횟수)만큼 반복.
    """
    points = []
    current_pool = pool
    shares = current_shares

    for i in range(max_points):
        sell_price = round(max_band / shares, 2)
        proceeds = round(sell_price * unit_size, 2)
        current_pool = round(current_pool + proceeds, 2)
        shares -= unit_size
        if shares <= 0:
            break
        points.append({
            "action": "SELL",
            "shares_after": shares,
            "price": sell_price,
            "amount": proceeds,
            "pool_after": current_pool,
        })
    return points
