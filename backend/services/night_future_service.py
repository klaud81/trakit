"""KOSPI200 야간선물 실시간 시세 서비스.

데이터 소스: esignal.co.kr (socket.io)
- 연결: wss://esignal.co.kr/proxy/8888/socket.io/
- 이벤트: "populate" (server push)
- 종목: kospif_ngt (KOSPI Futures Night)

세션:
- 야간장: KST 18:00 ~ 다음날 05:00
- 05:00 이후엔 마지막 tick 을 freeze 하여 18:00 까지 표출
- 18:00 신규 세션 시작 시 자동 갱신

비고: esignal 은 사설 시그널 서비스이므로 비공식 사용. ToS / 차단 가능.
"""
from __future__ import annotations
import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import socketio

KST = timezone(timedelta(hours=9))
logger = logging.getLogger(__name__)

SOCKET_URL = "https://esignal.co.kr"
SOCKET_PATH = "/proxy/8888/socket.io"
EVENT = "populate"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Origin": "https://esignal.co.kr",
    "Referer": "https://esignal.co.kr/kospi200-futures-night/",
}

# 가장 최근 tick
_latest: dict = {
    "value": None,            # 현재가
    "value_diff": None,       # 등락폭
    "prev_close": None,       # 전일 종가 (등락률 계산용)
    "change_pct": None,       # 등락률 (%)
    "high": None,
    "low": None,
    "volume": None,
    "ttime": None,            # esignal 의 거래시각 (HHMMSS 등)
    "unix_timestamp": None,
    "updated_at": None,       # 서버 수신 시각 (KST ISO)
    "session": None,          # 'night' (live) / 'closed' (snapshot)
    "source": "esignal.co.kr",
}

# 05:00 KST 이전 마지막 값 (snapshot 비교용)
_last_session_close_value: Optional[float] = None
_last_session_close_at: Optional[datetime] = None

_sio: Optional[socketio.AsyncClient] = None
_task: Optional[asyncio.Task] = None
_stop_event: Optional[asyncio.Event] = None


def _now_kst() -> datetime:
    return datetime.now(KST)


def _is_night_session(now: Optional[datetime] = None) -> bool:
    """KST 18:00 ~ 다음날 05:00 = 야간장."""
    n = now or _now_kst()
    h = n.hour
    return h >= 18 or h < 5


def _compute_change(value: float, prev_close: Optional[float]) -> Optional[float]:
    if not prev_close or prev_close == 0:
        return None
    return round((value - prev_close) / prev_close * 100, 2)


def _f(v) -> Optional[float]:
    """str/None/number → float."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def _on_populate(raw) -> None:
    """esignal 의 'populate' 이벤트 핸들러 (payload 는 JSON 문자열로 옴)."""
    global _latest, _last_session_close_value, _last_session_close_at
    try:
        if isinstance(raw, str):
            data = json.loads(raw)
        elif isinstance(raw, dict):
            data = raw
        else:
            return
        value = _f(data.get("value"))
        if not value or value <= 0:
            return
        diff = _f(data.get("value_diff"))
        # value_day = 전일 종가 (esignal 이 직접 제공). 없으면 value-diff 로 역산.
        prev_close = _f(data.get("value_day")) or (value - diff if diff is not None else None)
        pct = _compute_change(value, prev_close)
        now = _now_kst()
        _latest.update({
            "value": value,
            "value_diff": diff,
            "prev_close": prev_close,
            "change_pct": pct,
            "open": _f(data.get("open")) or _latest.get("open"),
            "high": _f(data.get("high")) or _latest.get("high"),
            "low": _f(data.get("low")) or _latest.get("low"),
            "volume": data.get("volume"),
            "ttime": data.get("ttime"),
            "unix_timestamp": data.get("unix_timestamp"),
            "updated_at": now.isoformat(timespec="seconds"),
            "session": "night" if _is_night_session(now) else "closed",
        })
        # 05:00 직전 (04:50 ~ 05:00) 의 tick 을 snapshot 으로 저장
        if 4 <= now.hour < 5:
            _last_session_close_value = value
            _last_session_close_at = now
    except Exception as e:
        logger.debug(f"populate 처리 실패: {e}")


async def _connect_and_listen() -> None:
    """socket.io 연결 + 자동 재연결."""
    global _sio
    _sio = socketio.AsyncClient(reconnection=True, reconnection_attempts=0,
                                reconnection_delay=3, reconnection_delay_max=30,
                                logger=False, engineio_logger=False)

    @_sio.event
    async def connect():
        logger.info("📡 esignal socket.io 연결 성공")

    @_sio.event
    async def disconnect():
        logger.warning("📡 esignal socket.io 연결 끊김")

    @_sio.on(EVENT)
    async def _handler(data):
        await _on_populate(data)

    while not (_stop_event and _stop_event.is_set()):
        try:
            await _sio.connect(SOCKET_URL, socketio_path=SOCKET_PATH,
                               headers=HEADERS, transports=["websocket"])
            await _sio.wait()
        except Exception as e:
            logger.warning(f"📡 esignal 연결 실패: {e} — 30초 후 재시도")
            await asyncio.sleep(30)


async def start() -> None:
    """FastAPI lifespan startup 에서 호출."""
    global _task, _stop_event
    if _task and not _task.done():
        return
    _stop_event = asyncio.Event()
    _task = asyncio.create_task(_connect_and_listen(), name="kr_night_future")
    logger.info("🚀 KR 야간선물 실시간 구독 시작")


async def stop() -> None:
    """FastAPI lifespan shutdown 에서 호출."""
    global _task, _sio
    if _stop_event:
        _stop_event.set()
    if _sio and _sio.connected:
        try:
            await _sio.disconnect()
        except Exception:
            pass
    if _task:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
    logger.info("🛑 KR 야간선물 구독 종료")


def get_latest() -> dict:
    """현재 캐시된 tick 반환. 야간장이 아니면 마지막 snapshot 으로 표시."""
    now = _now_kst()
    payload = dict(_latest)
    # 야간장 종료 후 → 마지막 값을 closed 로 표시
    if not _is_night_session(now):
        payload["session"] = "closed"
    return payload
