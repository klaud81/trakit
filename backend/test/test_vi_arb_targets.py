"""VI 차익거래 추천 매도가 순수 함수 단위 테스트.

calc_fallback_target (개장 전 폴백, 이월 3단계 규칙) /
calc_intraday_target (장중 변동폭 로직) / calc_net_rate / _tick_ceil.
네트워크·상태 의존 없음.

실행: cd backend && python -m pytest test/test_vi_arb_targets.py -v
"""
from services.vi_arb_kiwoom import (
    _tick_ceil,
    calc_fallback_target,
    calc_intraday_target,
    calc_net_rate,
)


# ---- _tick_ceil: KRX 호가단위 올림 ----

def test_tick_ceil_band_units():
    assert _tick_ceil(1999.1) == 2000      # <2,000원: 1원
    assert _tick_ceil(2000) == 2000        # 정확히 단위 위 = 그대로
    assert _tick_ceil(2001) == 2005        # 2,000~5,000: 5원
    assert _tick_ceil(19991) == 20000      # 5,000~20,000: 10원
    assert _tick_ceil(20001) == 20050      # 20,000~50,000: 50원
    assert _tick_ceil(50001) == 50100      # 50,000~200,000: 100원
    assert _tick_ceil(200001) == 200500    # 200,000~500,000: 500원
    assert _tick_ceil(500000) == 500000    # ≥500,000: 1,000원
    assert _tick_ceil(500001) == 501000


# ---- calc_net_rate: 평단 대비 세후 수익률 ----

def test_net_rate_positive():
    # 101,000원 매도: 수취 100,833.35 → +0.83%
    assert calc_net_rate(101000, 100000) == 0.83


def test_net_rate_at_breakeven_is_nonnegative():
    # 손익분기가(평단×1.0018)를 호가단위 올림한 가격에 팔면 세후 ≥ 0
    t, _ = calc_fallback_target(100000, 100000, held_over=False)
    assert calc_net_rate(t, 100000) >= 0


# ---- calc_fallback_target: 개장 전 폴백 (이월 3단계 규칙) ----

def test_fallback_stoploss_below_minus7():
    # 이월 -15% 손실 → 손실률 1/3 지점 = 평단×0.95
    t, kind = calc_fallback_target(100000, 85000, held_over=True)
    assert (t, kind) == (95000, "stoploss")


def test_fallback_stoploss_boundary_minus7_inclusive():
    # 정확히 -7% 도 손절 (≤ -7): 평단×(1−7/300) = 97,666.7 → 97,700
    t, kind = calc_fallback_target(100000, 93000, held_over=True)
    assert (t, kind) == (97700, "stoploss")


def test_fallback_band_fixed_half_percent():
    # 이월 -2% → 세후 +0.5% 고정: 100,000×1.005/0.99835 = 100,666.1 → 100,700
    t, kind = calc_fallback_target(100000, 98000, held_over=True)
    assert (t, kind) == (100700, None)
    assert calc_net_rate(t, 100000) >= 0.5


def test_fallback_band_upper_boundary_below_half_percent():
    # 이월 +0.4% (< +0.5%) 도 밴드 → 고정 추천
    t, kind = calc_fallback_target(100000, 100400, held_over=True)
    assert (t, kind) == (100700, None)


def test_fallback_profit_uses_current_price():
    # 이월 +10% 수익 → max(손익분기, 현재가) = 현재가
    t, kind = calc_fallback_target(100000, 110000, held_over=True)
    assert (t, kind) == (110000, None)


def test_fallback_today_bought_ignores_tiers():
    # 당일 매수분은 손실 커도 손절/밴드 미적용 → max(손익분기, 현재가) = 100,180 → 100,200
    t, kind = calc_fallback_target(100000, 85000, held_over=False)
    assert (t, kind) == (100200, None)


# ---- calc_intraday_target: 장중 변동폭 로직 ----

def test_intraday_volatility_based():
    # 변동폭 4,000 → 현재가 + 2,000
    assert calc_intraday_target(100000, 101000, high=103000, low=99000) == 103000


def test_intraday_breakeven_floor_for_losers():
    # 변동폭 항(95,500)이 손익분기(100,180) 아래 → 손익분기로 하한
    assert calc_intraday_target(100000, 95000, high=95500, low=94500) == 100200


def test_intraday_upper_limit_cap():
    # 상한가 캡: 변동폭 목표 103,000 이 upl 102,000 에 캡
    assert calc_intraday_target(100000, 101000, high=103000, low=99000, upl=102000) == 102000


def test_intraday_zero_range_at_open():
    # 개장 직후 변동폭 0 → max(손익분기, 현재가)
    assert calc_intraday_target(100000, 99000, high=99000, low=99000) == 100200
    assert calc_intraday_target(100000, 110000, high=110000, low=110000) == 110000
