"""목표 진행률 + 계획대비 시간차 계산 서비스.

ProgressCard / Discord /goal 가 공통으로 사용.

핵심:
- 시트의 "계획" 컬럼 (V_prev+200) × ratio (홀수 sn 1.03, 짝수 1.0)
- 조정 행이 있는 구간은 시트값을 그대로 사용 (단순 alternating 으로 안 맞음)
- 시트에 없는 미래 cycle 은 마지막 값에서 동일 패턴으로 연장
"""
from __future__ import annotations
import logging
import requests
from datetime import datetime
from typing import Optional
from config import GOOGLE_SHEET_URL, GOAL_KRW, GOAL_WEEK
from services.exchange_rate_service import get_exchange_rate

logger = logging.getLogger(__name__)

CONTRIBUTION = 200.0
_CACHE: Optional[dict] = None
_CACHE_TIME: Optional[datetime] = None
_CACHE_TTL_SEC = 300  # 5분


def _load_planned_map() -> dict[int, float]:
    """시트에서 week_num → 계획값 매핑 로드. 5분 캐시.

    "계획" 컬럼은 끝에서 3번째 (적립액/계획/ratio/V+pool 4컬럼 trailing).
    """
    global _CACHE, _CACHE_TIME
    if _CACHE is not None and _CACHE_TIME:
        if (datetime.now() - _CACHE_TIME).total_seconds() < _CACHE_TTL_SEC:
            return _CACHE

    planned_map: dict[int, float] = {}
    try:
        r = requests.get(GOOGLE_SHEET_URL, timeout=15)
        r.raise_for_status()
        for line in r.text.splitlines()[1:]:
            cols = line.split(",")
            if len(cols) < 5 or not cols[0].strip().isdigit():
                continue
            week_str = (cols[1] or "").strip().split()[0]
            if not week_str.isdigit():
                continue
            try:
                week_num = int(week_str)
                plan_val = float(cols[-3])
                # 같은 week_num이 여러 번 나오면 (조정 행) 마지막 값 사용
                planned_map[week_num] = plan_val
            except (ValueError, IndexError):
                continue
        _CACHE = planned_map
        _CACHE_TIME = datetime.now()
        logger.info(f"📊 계획 컬럼 캐시 저장 ({len(planned_map)}주차)")
    except Exception as e:
        logger.warning(f"계획 컬럼 로드 실패: {e}")
        if _CACHE is None:
            _CACHE = {}
    return _CACHE


def _build_full_trajectory() -> dict[int, float]:
    """week_num(2,4,6,...,560) → planned 매핑.
    시트에 있는 값은 그대로, 없는 미래 cycle 은 (V_prev + 200) × ratio 로 연장.
    """
    sheet = _load_planned_map()
    full: dict[int, float] = dict(sheet)
    if not sheet:
        # 시트 로드 실패 → 순수 alternating 사용
        v = 0.0
        for cycle in range(1, GOAL_WEEK // 2 + 1):
            v = (v + CONTRIBUTION) * (1.03 if cycle % 2 == 1 else 1.0)
            full[cycle * 2] = v
        return full

    # 마지막 시트값 이후 연장
    last_week = max(sheet.keys())
    v = sheet[last_week]
    cycle = last_week // 2
    for w in range(last_week + 2, GOAL_WEEK + 2, 2):
        cycle += 1
        v = (v + CONTRIBUTION) * (1.03 if cycle % 2 == 1 else 1.0)
        full[w] = v
    return full


def compute_goal_status(
    week_num: int,
    actual_value: float,
    rate: Optional[float] = None,
) -> dict:
    """목표 진행률 + 계획대비 + 시간차 계산.

    Args:
        week_num: 기준 주차 (2, 4, ..., 262)
        actual_value: 실제 평가금 (보통 valuation + pool, 현재는 live, 과거는 V+pool)
        rate: 환율 (없으면 자동 조회)

    Returns dict: actual_value, planned, plan_pct, goal_progress, weeks_diff, time_label,
                  weeks_remaining, years_left, weeks_left_in_year, target_week
    """
    if rate is None:
        rate = get_exchange_rate().get("rate", 1400)
    goal_usd = GOAL_KRW / rate if rate > 0 else 0
    goal_progress = (actual_value / goal_usd * 100) if goal_usd > 0 else 0

    trajectory = _build_full_trajectory()
    planned = trajectory.get(week_num, 0)
    plan_pct = (actual_value / planned * 100) if planned > 0 else 0

    # weeks_diff: actual_value 가 trajectory 상 어느 주차에 도달하는지
    sorted_weeks = sorted(trajectory.keys())
    target_week = sorted_weeks[-1] if sorted_weeks else week_num
    for w in sorted_weeks:
        if trajectory[w] >= actual_value:
            target_week = w
            break
    weeks_diff = target_week - week_num
    if weeks_diff > 0:
        time_label = f"{weeks_diff}주 빠름"
    elif weeks_diff < 0:
        time_label = f"{abs(weeks_diff)}주 느림"
    else:
        time_label = "계획대로"

    weeks_remaining = max(0, GOAL_WEEK - week_num)
    years_left, weeks_left_in_year = divmod(weeks_remaining, 52)
    remaining_cycles = weeks_remaining // 2

    return {
        "week_num": week_num,
        "actual_value": round(actual_value, 2),
        "planned": round(planned, 2),
        "plan_pct": round(plan_pct, 2),
        "goal_progress": round(goal_progress, 2),
        "goal_usd": round(goal_usd, 2),
        "weeks_diff": weeks_diff,
        "time_label": time_label,
        "target_week": target_week,
        "weeks_remaining": weeks_remaining,
        "years_left": years_left,
        "weeks_left_in_year": weeks_left_in_year,
        "remaining_cycles": remaining_cycles,
        "rate": rate,
    }
