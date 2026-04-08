"""환율 조회 서비스

캐시 정책:
- 캐시 없으면 → 조회하여 캐시 저장
- 캐시 있고 KST 17시 이후 + 오늘 갱신 안 됨 → 재조회하여 캐시 갱신
- 나머지 → 캐시 반환
"""
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

_rate_cache: Optional[dict] = None
_cache_time: Optional[datetime] = None


def _fetch_exchange_rate() -> Optional[float]:
    """외부 API에서 USD/KRW 환율 조회"""
    # 1순위: exchangerate-api (무료, 일 1500회)
    try:
        resp = requests.get(
            "https://open.er-api.com/v6/latest/USD",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("result") == "success":
            rate = data["rates"].get("KRW")
            if rate:
                return round(float(rate), 2)
    except Exception as e:
        logger.warning(f"exchangerate-api failed: {e}")

    # 2순위: frankfurter (ECB 기반, 무료)
    try:
        resp = requests.get(
            "https://api.frankfurter.dev/v1/latest?base=USD&symbols=KRW",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        rate = data.get("rates", {}).get("KRW")
        if rate:
            return round(float(rate), 2)
    except Exception as e:
        logger.warning(f"frankfurter API failed: {e}")

    return None


def _need_refresh() -> bool:
    """캐시 갱신이 필요한지 판단"""
    if not _rate_cache or not _cache_time:
        return True
    now_kst = datetime.now(KST)
    cache_kst = _cache_time.astimezone(KST)
    # KST 17시 이후이고, 캐시가 오늘 17시 이전에 저장된 경우 갱신
    if now_kst.hour >= 17 and cache_kst.date() < now_kst.date():
        return True
    if now_kst.hour >= 17 and cache_kst.hour < 17 and cache_kst.date() == now_kst.date():
        return True
    return False


def get_exchange_rate() -> dict:
    """USD/KRW 환율 조회 (KST 17시 이후 하루 1회 갱신)"""
    global _rate_cache, _cache_time

    if not _need_refresh():
        return _rate_cache

    rate = _fetch_exchange_rate()

    if rate:
        _rate_cache = {
            "base": "USD",
            "target": "KRW",
            "rate": rate,
            "date": datetime.now(KST).strftime("%Y-%m-%d"),
            "source": "live",
        }
        _cache_time = datetime.now(KST)
        return _rate_cache

    # 조회 실패 시 캐시 반환
    if _rate_cache:
        return _rate_cache

    # 캐시도 없으면 기본값
    from config import DEFAULT_EXCHANGE_RATE
    return {
        "base": "USD",
        "target": "KRW",
        "rate": DEFAULT_EXCHANGE_RATE,
        "date": datetime.now(KST).strftime("%Y-%m-%d"),
        "source": "default",
    }
