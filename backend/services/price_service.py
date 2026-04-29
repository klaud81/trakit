"""실시간 가격 조회 서비스

KIS(한국투자증권) API를 기본 소스로, yfinance/Yahoo API를 fallback으로 사용.
"""
import requests
import yfinance as yf
from datetime import datetime, timezone, timedelta
from typing import Optional
from config import SYMBOL, PRICE_FETCH_ALWAYS, EXCHANGE_MAP, DAYTIME_EXCD, DEFAULT_EXCHANGE
import logging

logger = logging.getLogger(__name__)

_price_cache: dict[str, dict] = {}
_cache_time: dict[str, datetime] = {}
CACHE_TTL_SECONDS = 30  # 30초 캐시


KST = timezone(timedelta(hours=9))

# KIS API 토큰 캐시
_kis_token: Optional[str] = None
_kis_token_expires: Optional[datetime] = None


def _get_kis_token() -> Optional[str]:
    """KIS API 접근토큰 발급 (24시간 유효)"""
    global _kis_token, _kis_token_expires
    if _kis_token and _kis_token_expires and datetime.now() < _kis_token_expires:
        return _kis_token
    from config import KIS_APP_KEY, KIS_APP_SECRET, KIS_BASE_URL
    if not KIS_APP_KEY or not KIS_APP_SECRET:
        return None
    try:
        resp = requests.post(
            f"{KIS_BASE_URL}/oauth2/tokenP",
            json={"grant_type": "client_credentials", "appkey": KIS_APP_KEY, "appsecret": KIS_APP_SECRET},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        _kis_token = data["access_token"]
        _kis_token_expires = datetime.now() + timedelta(hours=23)
        logger.info(f"🔑 KIS 토큰 캐시 저장 (만료: {_kis_token_expires.strftime('%Y-%m-%d %H:%M')})")
        return _kis_token
    except Exception as e:
        logger.warning(f"KIS token failed: {e}")
        return None


def _fetch_kis(symbol: str) -> Optional[dict]:
    """한국투자증권 API로 해외주식 현재가 조회.

    심볼별로 상장 거래소(NAS/NYS/AMS) 매핑하여 호출.
    실서버에서는 사전장/시간외 시간대에도 자동으로 확장된 시간 가격을 반환함.
    """
    token = _get_kis_token()
    if not token:
        return None
    from config import KIS_APP_KEY, KIS_APP_SECRET, KIS_BASE_URL
    excd = EXCHANGE_MAP.get(symbol.upper(), DEFAULT_EXCHANGE)
    try:
        resp = requests.get(
            f"{KIS_BASE_URL}/uapi/overseas-price/v1/quotations/price",
            headers={
                "authorization": f"Bearer {token}",
                "appkey": KIS_APP_KEY,
                "appsecret": KIS_APP_SECRET,
                "tr_id": "HHDFS00000300",
                "Content-Type": "application/json; charset=utf-8",
            },
            params={"AUTH": "", "EXCD": excd, "SYMB": symbol},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        output = data.get("output", {})
        price = float(output.get("last", 0))
        prev_close = float(output.get("base", 0))
        if price > 0 and prev_close > 0:
            change = price - prev_close
            change_pct = change / prev_close * 100
            return {
                "price": round(price, 2),
                "prev_close": round(prev_close, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "day_high": round(float(output.get("high", 0) or 0), 2) or None,
                "day_low": round(float(output.get("low", 0) or 0), 2) or None,
                "extended": _is_us_extended_session(),
                "excd": excd,
            }
    except Exception as e:
        logger.warning(f"KIS API failed (excd={excd}): {e}")
    return None


def _is_market_open() -> bool:
    """미국 주식 시장 개장 여부 (KST 기준 21:30~06:00, 주말 제외)"""
    now_kst = datetime.now(KST)
    # ET 기준 평일 체크
    now_et = datetime.now(timezone(timedelta(hours=-4)))
    if now_et.weekday() >= 5:
        return False
    hour = now_kst.hour
    minute = now_kst.minute
    # KST 21:30 ~ 다음날 06:00 (서머타임 기준, ET 9:30~16:00 ≈ KST 22:30~05:00 but 여유 있게)
    if hour >= 22 or (hour == 21 and minute >= 30):
        return True
    if hour < 6:
        return True
    return False


def _is_trading_hours() -> bool:
    """KST 21시~06시 사이인지 (자동 갱신 시간대)"""
    hour = datetime.now(KST).hour
    return hour >= 21 or hour < 6


def _is_us_extended_session() -> bool:
    """미국 사전장/시간외 시간대 (KST, 평일 기준).

    - 사전장(pre-market): ET 04:00~09:30 ≈ KST 17:00~22:30 (DST)
    - 시간외(after-hours): ET 16:00~20:00 ≈ KST 05:00~09:00 (DST)
    EST(겨울)는 +1시간씩 늦어지지만 여유 있게 잡음.
    """
    now = datetime.now(KST)
    if now.weekday() >= 5:
        return False
    h, m = now.hour, now.minute
    # 사전장: 17:00 ~ 22:30
    if 17 <= h < 22:
        return True
    if h == 22 and m < 30:
        return True
    # 시간외: 05:00 ~ 09:00 (정규장 22:30~05:00 직후)
    if 5 <= h < 9:
        return True
    return False


def _fetch_yahoo_api(symbol: str) -> Optional[dict]:
    """Yahoo Finance API v8로 실시간 가격 조회 (프리/포스트마켓 포함)"""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        params = {"interval": "1m", "range": "1d", "includePrePost": "true"}
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        result = data["chart"]["result"][0]
        meta = result["meta"]

        regular_price = float(meta.get("regularMarketPrice", 0))
        prev_close = float(meta.get("chartPreviousClose", 0) or meta.get("previousClose", 0))

        # 프리/포스트마켓: 차트 데이터의 마지막 close 값 사용
        price = regular_price
        extended = False
        timestamps = result.get("timestamp", [])
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        if timestamps and closes:
            # 마지막 유효한 close 값 (프리/포스트마켓 포함)
            last_close = None
            for c in reversed(closes):
                if c is not None:
                    last_close = c
                    break
            if last_close and abs(last_close - regular_price) > 0.01:
                price = last_close
                extended = True

        return {
            "price": round(float(price), 2),
            "prev_close": round(float(prev_close), 2) if prev_close else 0,
            "day_high": round(float(meta.get("regularMarketDayHigh", 0) or 0), 2) or None,
            "day_low": round(float(meta.get("regularMarketDayLow", 0) or 0), 2) or None,
            "extended": extended,
        }
    except Exception as e:
        logger.warning(f"Yahoo API v8 failed: {e}")
        return None


def _fetch_yahoo_quote(symbol: str) -> Optional[dict]:
    """Yahoo Finance quote API fallback (프리/포스트마켓 지원)"""
    try:
        url = f"https://query1.finance.yahoo.com/v7/finance/quote"
        params = {"symbols": symbol}
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        quote = data["quoteResponse"]["result"][0]
        regular_price = float(quote.get("regularMarketPrice", 0))
        prev_close = float(quote.get("regularMarketPreviousClose", 0))

        # 프리마켓/포스트마켓 가격 우선 사용
        market_state = quote.get("marketState", "")
        price = regular_price
        extended = False
        if market_state == "PRE":
            pre = float(quote.get("preMarketPrice", 0) or 0)
            if pre > 0:
                price = pre
                extended = True
        elif market_state in ("POST", "POSTPOST", "CLOSED"):
            post = float(quote.get("postMarketPrice", 0) or 0)
            if post > 0:
                price = post
                extended = True

        return {
            "price": round(price, 2),
            "prev_close": round(prev_close, 2) if prev_close else 0,
            "day_high": round(float(quote.get("regularMarketDayHigh", 0) or 0), 2) or None,
            "day_low": round(float(quote.get("regularMarketDayLow", 0) or 0), 2) or None,
            "extended": extended,
            "market_state": market_state,
        }
    except Exception as e:
        logger.warning(f"Yahoo quote API failed: {e}")
        return None


def _fetch_yfinance(symbol: str) -> Optional[dict]:
    """yfinance SDK로 실시간 가격 조회 (기본 소스, fast_info 사용)"""
    try:
        ticker = yf.Ticker(symbol)
        fi = ticker.fast_info

        price = float(fi.last_price)
        prev_close = float(fi.previous_close)
        day_high = float(fi.day_high) if fi.day_high else None
        day_low = float(fi.day_low) if fi.day_low else None

        if price > 0 and prev_close > 0:
            change = price - prev_close
            change_pct = change / prev_close * 100
            return {
                "price": round(price, 2),
                "prev_close": round(prev_close, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "day_high": round(day_high, 2) if day_high else None,
                "day_low": round(day_low, 2) if day_low else None,
            }
    except Exception as e:
        logger.warning(f"yfinance failed: {e}")
    return None


def get_current_price(symbol: str = SYMBOL) -> dict:
    """실시간 가격 조회 (심볼별 캐시)

    캐시 정책:
    - 캐시 있고 30초 이내 → 캐시 반환
    - KST 21~06시(트레이딩 시간) + 30초 초과 → 재조회
    - KST 06~21시(비트레이딩) → 캐시 반환 (없으면 1회 조회)
    """
    symbol = symbol.upper()
    cached = _price_cache.get(symbol)
    cached_at = _cache_time.get(symbol)

    if cached and cached_at:
        elapsed = (datetime.now() - cached_at).total_seconds()
        if elapsed < CACHE_TTL_SECONDS:
            return cached
        # PRICE_FETCH_ALWAYS=False일 때만 장외시간 캐시 고정
        if not PRICE_FETCH_ALWAYS and not _is_trading_hours():
            return cached

    # 순서대로 시도: KIS → yfinance → Yahoo API v8 → Yahoo quote
    # KIS 정규 EXCD(NAS/AMS/NYS) 가 사전장/시간외에도 확장된 시간 가격 반환함.
    raw = _fetch_kis(symbol)
    if not raw or raw["price"] == 0:
        raw = _fetch_yfinance(symbol)
    if not raw or raw["price"] == 0:
        raw = _fetch_yahoo_api(symbol)
    if not raw or raw["price"] == 0:
        raw = _fetch_yahoo_quote(symbol)

    # 고가/저가 누락 시 Yahoo에서 보충
    if raw and raw["price"] > 0 and not raw.get("day_high"):
        supplement = _fetch_yahoo_api(symbol) or _fetch_yahoo_quote(symbol)
        if supplement:
            raw["day_high"] = raw.get("day_high") or supplement.get("day_high")
            raw["day_low"] = raw.get("day_low") or supplement.get("day_low")

    if raw and raw["price"] > 0:
        price = raw["price"]
        prev_close = raw["prev_close"]
        if "change" in raw:
            change = raw["change"]
            change_pct = raw["change_pct"]
        else:
            change = price - prev_close if prev_close else 0
            change_pct = (change / prev_close * 100) if prev_close else 0

        result = {
            "symbol": symbol,
            "price": round(price, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "timestamp": datetime.now().isoformat(),
            "prev_close": round(prev_close, 2) if prev_close else None,
            "day_high": round(raw["day_high"], 2) if raw.get("day_high") else None,
            "day_low": round(raw["day_low"], 2) if raw.get("day_low") else None,
            "market_open": _is_market_open(),
            "extended": raw.get("extended", False),
        }

        _price_cache[symbol] = result
        _cache_time[symbol] = datetime.now()
        logger.info(f"💰 가격 캐시 저장 [{symbol}]: ${price} (변동: {change:+.2f}, {change_pct:+.2f}%) prev_close=${prev_close}")
        return result

    # 모든 소스 실패
    if cached:
        return cached

    return {
        "symbol": symbol,
        "price": 0,
        "change": 0,
        "change_pct": 0,
        "timestamp": datetime.now().isoformat(),
        "market_open": False,
    }


def get_price_history(symbol: str = SYMBOL, period: str = "6mo") -> list:
    """가격 히스토리 조회"""
    # Yahoo Finance API v8로 직접 조회
    interval_map = {
        "1d": ("1d", "5m"),
        "5d": ("5d", "15m"),
        "1mo": ("1mo", "1d"),
        "3mo": ("3mo", "1d"),
        "6mo": ("6mo", "1d"),
        "1y": ("1y", "1d"),
        "2y": ("2y", "1wk"),
    }
    api_range, api_interval = interval_map.get(period, ("6mo", "1d"))

    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        params = {"interval": api_interval, "range": api_range}
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        quotes = result["indicators"]["quote"][0]

        records = []
        for i, ts in enumerate(timestamps):
            dt = datetime.fromtimestamp(ts)
            o = quotes["open"][i]
            h = quotes["high"][i]
            l = quotes["low"][i]
            c = quotes["close"][i]
            v = quotes["volume"][i]
            if c is None:
                continue
            records.append({
                "date": dt.strftime("%Y-%m-%d"),
                "open": round(float(o or 0), 2),
                "high": round(float(h or 0), 2),
                "low": round(float(l or 0), 2),
                "close": round(float(c), 2),
                "volume": int(v or 0),
            })
        return records
    except Exception as e:
        logger.warning(f"price history fetch failed: {e}")

    # yfinance fallback
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)
        records = []
        for date, row in hist.iterrows():
            records.append({
                "date": date.strftime("%Y-%m-%d"),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]),
            })
        return records
    except Exception:
        return []
