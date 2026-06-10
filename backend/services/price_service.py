"""실시간 가격 조회 서비스

KIS(한국투자증권) API를 기본 소스로, yfinance/Yahoo API를 fallback으로 사용.
"""
import json
import requests
import yfinance as yf
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from config import SYMBOL, PRICE_FETCH_ALWAYS, EXCHANGE_MAP, DAYTIME_EXCD, DEFAULT_EXCHANGE, DATA_DIR
import logging

logger = logging.getLogger(__name__)

_price_cache: dict[str, dict] = {}
_cache_time: dict[str, datetime] = {}
CACHE_TTL_SECONDS = 30  # 30초 캐시


KST = timezone(timedelta(hours=9))

# KIS API 토큰 캐시 (메모리 + 디스크 영속화)
# 재시작 후에도 만료 전이면 그대로 재사용 → KIS 의 토큰 발급 SMS 알림 최소화
_kis_token: Optional[str] = None
_kis_token_expires: Optional[datetime] = None
_KIS_TOKEN_FILE = DATA_DIR / ".kis_token.json"  # 영속 볼륨에 저장 (Docker 재배포 후에도 유지)


def _load_kis_token_from_disk() -> bool:
    """디스크에서 토큰 로드. 유효하면 메모리 캐시에 적재."""
    global _kis_token, _kis_token_expires
    try:
        if not _KIS_TOKEN_FILE.exists():
            return False
        data = json.loads(_KIS_TOKEN_FILE.read_text())
        expires = datetime.fromisoformat(data["expires_at"])
        if datetime.now() >= expires:
            return False  # 만료됨
        _kis_token = data["token"]
        _kis_token_expires = expires
        logger.info(f"🔑 KIS 토큰 디스크 로드 (만료: {expires.strftime('%Y-%m-%d %H:%M')})")
        return True
    except Exception as e:
        logger.warning(f"KIS 토큰 디스크 로드 실패: {e}")
        return False


def _save_kis_token_to_disk(token: str, expires: datetime) -> None:
    """토큰을 디스크에 저장 (재시작 시 재사용)."""
    try:
        _KIS_TOKEN_FILE.write_text(json.dumps({
            "token": token,
            "expires_at": expires.isoformat(),
        }))
    except Exception as e:
        logger.warning(f"KIS 토큰 디스크 저장 실패: {e}")


def _get_kis_token() -> Optional[str]:
    """KIS API 접근토큰 발급 (24시간 유효, 디스크 캐시)."""
    global _kis_token, _kis_token_expires
    # 1) 메모리 캐시
    if _kis_token and _kis_token_expires and datetime.now() < _kis_token_expires:
        return _kis_token
    # 2) 디스크 캐시
    if _load_kis_token_from_disk():
        return _kis_token
    # 3) 신규 발급 (SMS 알림 발생)
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
        # KIS 응답에 access_token_token_expired (KST naive) 포함 → 사용. 없으면 23h 후
        exp_str = data.get("access_token_token_expired")
        if exp_str:
            try:
                _kis_token_expires = datetime.strptime(exp_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                _kis_token_expires = datetime.now() + timedelta(hours=23)
        else:
            _kis_token_expires = datetime.now() + timedelta(hours=23)
        _save_kis_token_to_disk(_kis_token, _kis_token_expires)
        logger.info(f"🔑 KIS 토큰 신규 발급 (만료: {_kis_token_expires.strftime('%Y-%m-%d %H:%M')})")
        return _kis_token
    except Exception as e:
        logger.warning(f"KIS token failed: {e}")
        return None


# 시도 후 발견한 심볼→EXCD 매핑 캐시 (KIS 호출 횟수 절감)
_EXCD_DISCOVERY: dict[str, str] = {}


def _fetch_kis_one(symbol: str, excd: str, token: str) -> Optional[dict]:
    """단일 EXCD 로 KIS 호출."""
    from config import KIS_APP_KEY, KIS_APP_SECRET, KIS_BASE_URL
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
        try:
            price = float(output.get("last") or 0)
            prev_close = float(output.get("base") or 0)
        except (ValueError, TypeError):
            return None
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
        logger.warning(f"KIS API failed (excd={excd}, symbol={symbol}): {e}")
    return None


def _fetch_kis(symbol: str) -> Optional[dict]:
    """한국투자증권 API로 해외주식 현재가 조회.

    1) `EXCHANGE_MAP` 또는 디스커버리 캐시에 있으면 해당 EXCD 로 호출
    2) 없으면 NAS → NYS → AMS 순으로 시도하고, 성공한 EXCD 를 캐시
    실서버에서 사전장/시간외 시간대에도 자동으로 확장된 시간 가격을 반환.
    """
    sym = symbol.upper()
    token = _get_kis_token()
    if not token:
        return None

    excd = EXCHANGE_MAP.get(sym) or _EXCD_DISCOVERY.get(sym)
    if excd:
        # KST 데일리장 시간대(10~17시 평일)면 주간 EXCD(BAQ/BAY/BAA) 먼저 시도
        if _is_kis_daytime_session():
            daytime_excd = DAYTIME_EXCD.get(excd)
            if daytime_excd:
                result = _fetch_kis_one(sym, daytime_excd, token)
                if result:
                    result["extended"] = True
                    return result
        return _fetch_kis_one(sym, excd, token)

    for candidate in ("NAS", "NYS", "AMS"):
        result = _fetch_kis_one(sym, candidate, token)
        if result:
            _EXCD_DISCOVERY[sym] = candidate
            logger.info(f"🔍 KIS EXCD 디스커버리: {sym} → {candidate}")
            return result
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


def _is_kis_daytime_session() -> bool:
    """KIS 미국주식 주간거래(데일리장) 시간대 (KST 10:00~17:00 평일)."""
    now = datetime.now(KST)
    if now.weekday() >= 5:
        return False
    return 10 <= now.hour < 17


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


def _fetch_kis_daily_one(symbol: str, excd: str, token: str, bymd: str) -> list:
    """KIS 해외주식 기간별시세(HHDFS76240000) 1콜 → 일봉 리스트(내림차순, 최대 ~100).

    bymd: 조회 기준일(YYYYMMDD). "" 이면 최신부터. 페이지네이션은 이전 배치의
    가장 오래된 일자-1 을 bymd 로 다시 호출.
    """
    from config import KIS_APP_KEY, KIS_APP_SECRET, KIS_BASE_URL
    try:
        resp = requests.get(
            f"{KIS_BASE_URL}/uapi/overseas-price/v1/quotations/dailyprice",
            headers={
                "authorization": f"Bearer {token}",
                "appkey": KIS_APP_KEY,
                "appsecret": KIS_APP_SECRET,
                "tr_id": "HHDFS76240000",
                "Content-Type": "application/json; charset=utf-8",
            },
            params={"AUTH": "", "EXCD": excd, "SYMB": symbol,
                    "GUBN": "0", "BYMD": bymd, "MODP": "1"},  # GUBN0=일, MODP1=수정주가
            timeout=10,
        )
        resp.raise_for_status()
        rows = resp.json().get("output2", []) or []
    except Exception as e:
        logger.warning(f"KIS daily failed (excd={excd}, symbol={symbol}): {e}")
        return []
    out = []
    for r in rows:
        ymd = r.get("xymd") or ""
        try:
            c = float(r.get("clos") or 0)
        except (ValueError, TypeError):
            continue
        if len(ymd) != 8 or c <= 0:
            continue
        out.append({
            "date": f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}",
            "open": round(float(r.get("open") or c), 2),
            "high": round(float(r.get("high") or c), 2),
            "low": round(float(r.get("low") or c), 2),
            "close": round(c, 2),
            "volume": int(float(r.get("tvol") or 0)),
        })
    return out


def get_overseas_daily(symbol: str = SYMBOL, days: int = 130) -> list:
    """KIS 해외 일봉 우선 조회 → 실패 시 Yahoo(get_price_history) fallback.

    반환: {date,open,high,low,close,volume} 오름차순 리스트 (get_price_history 동일 포맷).
    라이브 예측이 KIS 실시간을 쓰므로 백테스트도 동일 소스로 캘리브레이션하기 위함.
    """
    sym = symbol.upper()
    token = _get_kis_token()
    if token:
        excd = EXCHANGE_MAP.get(sym) or _EXCD_DISCOVERY.get(sym)
        candidates = [excd] if excd else ["NAS", "NYS", "AMS"]
        for cand in candidates:
            if not cand:
                continue
            merged, bymd, seen = [], "", set()
            for _ in range((days // 90) + 2):  # 1콜 ~100봉 → 페이지네이션
                batch = _fetch_kis_daily_one(sym, cand, token, bymd)
                if not batch:
                    break
                new = [b for b in batch if b["date"] not in seen]
                if not new:
                    break
                merged += new
                seen.update(b["date"] for b in new)
                if len(merged) >= days:
                    break
                oldest = min(b["date"] for b in new).replace("-", "")
                # 가장 오래된 일자 - 1일 (문자열 감산 회피: 그대로 줘도 중복은 seen 으로 컷)
                bymd = oldest
            if merged:
                if not excd:
                    _EXCD_DISCOVERY[sym] = cand
                    logger.info(f"🔍 KIS 일봉 EXCD 디스커버리: {sym} → {cand}")
                merged.sort(key=lambda b: b["date"])
                return merged[-days:]
    # fallback
    logger.info(f"KIS 일봉 실패/미설정 → Yahoo fallback ({sym})")
    return get_price_history(sym, period="6mo")
