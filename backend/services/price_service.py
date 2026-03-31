"""실시간 가격 조회 서비스

yfinance SDK를 기본 소스로 사용하여 정확한 가격 변동 정보 제공.
Yahoo Finance v8 API는 fallback으로 사용.
"""
import requests
import yfinance as yf
from datetime import datetime, timezone, timedelta
from typing import Optional
from config import SYMBOL
import logging

logger = logging.getLogger(__name__)

_price_cache: Optional[dict] = None
_cache_time: Optional[datetime] = None
CACHE_TTL_SECONDS = 30  # 30초 캐시


def _is_market_open() -> bool:
    """미국 주식 시장 개장 여부 (간단한 체크)"""
    now_et = datetime.now(timezone(timedelta(hours=-4)))  # EDT
    weekday = now_et.weekday()
    if weekday >= 5:  # 토/일
        return False
    hour = now_et.hour
    minute = now_et.minute
    # 9:30 ~ 16:00 ET
    if hour < 9 or (hour == 9 and minute < 30) or hour >= 16:
        return False
    return True


def _fetch_yahoo_api(symbol: str) -> Optional[dict]:
    """Yahoo Finance API v8로 실시간 가격 조회"""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        params = {"interval": "1d", "range": "5d"}
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        result = data["chart"]["result"][0]
        meta = result["meta"]

        price = meta.get("regularMarketPrice", 0)
        prev_close = meta.get("previousClose", 0)

        # previousClose가 없으면 실제 종가 데이터에서 전일 종가 계산
        # chartPreviousClose는 분할/배당 조정값이라 부호가 뒤집힐 수 있어 사용하지 않음
        if not prev_close:
            try:
                closes = result["indicators"]["quote"][0]["close"]
                valid_closes = [c for c in closes if c is not None]
                if len(valid_closes) >= 2:
                    prev_close = valid_closes[-2]
            except (KeyError, IndexError):
                pass
        if not prev_close:
            prev_close = meta.get("chartPreviousClose", 0)

        return {
            "price": round(float(price), 2),
            "prev_close": round(float(prev_close), 2) if prev_close else 0,
            "day_high": round(float(meta.get("regularMarketDayHigh", 0) or 0), 2) or None,
            "day_low": round(float(meta.get("regularMarketDayLow", 0) or 0), 2) or None,
        }
    except Exception as e:
        logger.warning(f"Yahoo API v8 failed: {e}")
        return None


def _fetch_yahoo_quote(symbol: str) -> Optional[dict]:
    """Yahoo Finance quote API fallback"""
    try:
        url = f"https://query1.finance.yahoo.com/v7/finance/quote"
        params = {"symbols": symbol}
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        quote = data["quoteResponse"]["result"][0]
        price = quote.get("regularMarketPrice", 0)
        prev_close = quote.get("regularMarketPreviousClose", 0)

        return {
            "price": round(float(price), 2),
            "prev_close": round(float(prev_close), 2) if prev_close else 0,
            "day_high": round(float(quote.get("regularMarketDayHigh", 0) or 0), 2) or None,
            "day_low": round(float(quote.get("regularMarketDayLow", 0) or 0), 2) or None,
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


def get_current_price(symbol: str = SYMBOL, use_cache: bool = True) -> dict:
    """실시간 TQQQ 가격 조회 (다중 소스 fallback)"""
    global _price_cache, _cache_time

    if use_cache and _price_cache and _cache_time:
        elapsed = (datetime.now() - _cache_time).total_seconds()
        if elapsed < CACHE_TTL_SECONDS:
            return _price_cache

    # 순서대로 시도: yfinance → Yahoo API v8 → Yahoo quote
    raw = _fetch_yfinance(symbol)
    if not raw or raw["price"] == 0:
        raw = _fetch_yahoo_api(symbol)
    if not raw or raw["price"] == 0:
        raw = _fetch_yahoo_quote(symbol)

    if raw and raw["price"] > 0:
        price = raw["price"]
        prev_close = raw["prev_close"]
        # yfinance에서 직접 제공한 change/change_pct 사용 (정확함)
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
            "day_high": raw.get("day_high"),
            "day_low": raw.get("day_low"),
            "market_open": _is_market_open(),
        }

        _price_cache = result
        _cache_time = datetime.now()
        return result

    # 모든 소스 실패
    if _price_cache:
        return _price_cache

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
