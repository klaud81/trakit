"""VI 차익거래 — Kiwoom 실연동 관측 observer (rq-01 FR-01~06, 관측 전용).

OBSERVATION MODE — NO ORDERS. 주문 API 호출 없음.

흐름: get_token → WS LOGIN → 1h(VI) 구독 → VI 발동 시 {code}/{code}_NX 동적구독
      → NXT 매도호가 vs KRX 예상체결가 스프레드 계산 → hub.broadcast (mock 과 동일 스키마)
      → KRX 첫 체결(0B)=랜덤엔드 재개 → TTL(발동+210s) 만료 시 구독 해제.

⚠️ §5.2 미검증(공식문서 확인 필요): 예상체결 실시간 타입코드(추정 0E), 1h 전종목 등록
   가능 여부, VI/NXT FID 체계, NXT 시세 이용신청. → 수신 raw values 를 로그로 남겨
   라이브에서 FID 매핑을 확정한다. 미매핑이어도 연결/구독/브로드캐스트는 동작.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from config import KIWOOM_ENVS, VI_ARB_UNIVERSE, VI_ARB_ORDER, VI_ARB_OBS_ENV
from services.vi_arb import TAX, FEE, EDGE_BUFFER, _now_iso

logger = logging.getLogger(__name__)
# 관측 환경(기본 real — NXT 차익 괴리는 mockapi 미지원). 주문은 kiwoom_order 가 mock 고정.
_OBS = KIWOOM_ENVS.get(VI_ARB_OBS_ENV, KIWOOM_ENVS["real"])


_token_cache: dict[str, tuple] = {}   # base_url → (token, expire_epoch)


def _env_token(env: dict) -> str | None:
    """주어진 환경(env)으로 토큰 발급 (1시간 캐시)."""
    import urllib.request
    url = env.get("base_url", "")
    c = _token_cache.get(url)
    if c and c[1] > time.time() + 60:
        return c[0]
    if not (env.get("app_key") and env.get("app_secret")):
        return None
    body = json.dumps({"grant_type": "client_credentials", "appkey": env["app_key"],
                       "secretkey": env["app_secret"]}).encode()
    req = urllib.request.Request(f"{url}/oauth2/token", data=body,
                                 headers={"Content-Type": "application/json;charset=UTF-8"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
        tok = d.get("token") or d.get("access_token")
        if tok:
            _token_cache[url] = (tok, time.time() + 3600)
        return tok
    except Exception as e:
        logger.warning(f"토큰 발급 실패({url}): {e}")
        return None


_nxt_cache: dict[str, bool] = {}   # code → NXT 상장 여부 (장중 불변, 1회 조회)


async def _is_nxt_listed(code: str) -> bool:
    """VI 종목이 NXT 상장이라 실시간 구독 의미 있는지 (REST ka10001, 캐시)."""
    if code in _nxt_cache:
        return _nxt_cache[code]
    loop = asyncio.get_event_loop()
    try:
        r = await loop.run_in_executor(None, lambda: check_nxt_quote(code))
        enabled = bool(r.get("nxt_enabled"))
    except Exception:
        enabled = False
    _nxt_cache[code] = enabled
    return enabled


_REST_PATH = {"ka10004": "/api/dostk/mrkcond", "ka10001": "/api/dostk/stkinfo"}


def _rest(api_id: str, sym: str) -> dict:
    """REST 시세 조회 (ka10004 호가 / ka10001 기본정보). 실시간 WS 대체."""
    import urllib.request
    token = _env_token(_OBS)
    if not token:
        return {}
    req = urllib.request.Request(
        f"{_OBS['base_url']}{_REST_PATH[api_id]}",
        data=json.dumps({"stk_cd": sym}).encode(),
        headers={"Content-Type": "application/json;charset=UTF-8",
                 "authorization": f"Bearer {token}", "api-id": api_id}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())
    except Exception as e:
        logger.warning(f"{api_id} 실패({sym}): {e}")
        return {}


async def _poll_nxt_spread(broadcast, w: "_Watch") -> None:
    """KRX·NXT 호가를 REST 폴링해 스프레드 계산 (실시간 WS NXT 미수신 대체).

    NXT 매도최우선호가 = ka10004(code_NX).sel_fpr_bid
    KRX 기준가 = ka10001(code).exp_cntr_pric(단일가 예상체결) 우선, 없으면 cur_prc(현재가)
    TTL 윈도우 동안 폴링. spread = KRX − NXT매도호가.
    """
    loop = asyncio.get_event_loop()
    while time.time() < w.expire:
        nxt = await loop.run_in_executor(None, lambda: _rest("ka10004", f"{w.code}_NX"))
        krx = await loop.run_in_executor(None, lambda: _rest("ka10001", w.code))
        nxt_ask = round(_num(nxt.get("sel_fpr_bid")))
        nxt_qty = round(_num(nxt.get("sel_fpr_req"))) or None
        exp = round(_num(krx.get("exp_cntr_pric")))
        krx_exp = exp if exp > 0 else round(_num(krx.get("cur_prc")))  # 단일가면 예상, 아니면 현재가
        if nxt_ask > 0 and krx_exp > 0:
            spread = krx_exp - nxt_ask
            cost = krx_exp * TAX + (nxt_ask + krx_exp) * FEE
            net = spread - cost
            if w.first_buy is None:
                w.first_buy = nxt_ask
            w.max_profit_pct = max(w.max_profit_pct, (krx_exp - w.first_buy) / w.first_buy * 100)
            await broadcast({
                "type": "spread", "code": w.code, "name": w.name, "direction": w.direction,
                "sec_since_vi": round(TTL_SEC - (w.expire - time.time()), 1),
                "krx_expected": krx_exp, "nxt_best_ask": nxt_ask, "nxt_ask_qty": nxt_qty,
                "first_buy": w.first_buy, "spread": round(spread), "cost": round(cost),
                "net_spread": round(net), "net_pct": round(net / nxt_ask * 100, 3),
                "max_profit_pct": round(w.max_profit_pct, 3),
                "opportunity": 1 if net > cost * (EDGE_BUFFER - 1) else 0, "ts": _now_iso()})
        await asyncio.sleep(_NXT_POLL_SEC)


def _env_ws_connect(env: dict):
    """주어진 환경 WS 연결 (wss://{domain}:10000/api/dostk/websocket)."""
    import ssl
    import urllib.parse
    import websockets
    host = urllib.parse.urlparse(env["base_url"]).netloc
    ctx = ssl.create_default_context()
    return websockets.connect(f"wss://{host}:10000/api/dostk/websocket", ssl=ctx, open_timeout=15)


def check_nxt_quote(code: str = "005930") -> dict:
    """real 환경 NXT 시세 이용신청 여부 확인 (ka10001 주식기본정보, _NX 심볼).

    NXT 시세 권한이 있으면 현재가/기준가가 채워져 옴 → nxt_enabled=True.
    없으면 빈값 또는 오류. 장중·장외 무관(기준가로 판별).
    """
    import urllib.request
    token = _env_token(_OBS)
    if not token:
        return {"ok": False, "reason": f"관측({VI_ARB_OBS_ENV}) 토큰 없음"}
    body = json.dumps({"stk_cd": f"{code}_NX"}).encode()
    req = urllib.request.Request(
        f"{_OBS['base_url']}/api/dostk/stkinfo", data=body,
        headers={"Content-Type": "application/json;charset=UTF-8",
                 "authorization": f"Bearer {token}", "api-id": "ka10001"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
    except Exception as e:
        return {"ok": False, "reason": str(e)}
    cur, base = (d.get("cur_prc") or "").strip(), (d.get("base_pric") or "").strip()
    return {"ok": str(d.get("return_code", "0")) in ("0", "None"),
            "nxt_enabled": bool(_num(cur) or _num(base)), "symbol": f"{code}_NX",
            "stk_nm": d.get("stk_nm", ""), "cur_prc": cur, "base_pric": base,
            "env": VI_ARB_OBS_ENV, "return_msg": d.get("return_msg", "")}


def _fill_msg(d: dict) -> dict:
    """00 주문체결 프레임 → order_fill 메시지 (p.471 FID)."""
    v = d.get("values", {}) or {}
    return {"type": "order_fill", "code": (v.get(FID_CODE) or "").strip(),
            "name": v.get("302", ""), "status": v.get("913", ""), "ord_no": v.get("9203", ""),
            "side": "매수" if v.get("907") == "2" else "매도" if v.get("907") == "1" else "",
            "ord_qty": round(_num(v.get("900"))), "fill_price": round(_num(v.get("910"))),
            "fill_qty": round(_num(v.get("911"))), "exchange": v.get("2135", ""), "ts": _now_iso()}


async def _mock_fill_listener(broadcast, is_active) -> None:
    """mock WS 로 00(주문체결) 수신 → order_fill 방송. (모의 체결은 mock 도메인에서만)"""
    env = KIWOOM_ENVS["mock"]
    backoff = 1
    while is_active():
        try:
            token = _env_token(env)
            if not token:
                return
            async with await _env_ws_connect(env) as ws:
                await ws.send(json.dumps({"trnm": "LOGIN", "token": token}))
                await ws.recv()
                await ws.send(json.dumps({"trnm": "REG", "grp_no": "9", "refresh": "1",
                                          "data": [{"item": [""], "type": [RT_ORDER]}]}))
                logger.info("⚡ mock 체결(00) 리스너 시작")
                backoff = 1
                while is_active():
                    raw = await asyncio.wait_for(ws.recv(), timeout=60)
                    msg = json.loads(raw)
                    if _is_session_takeover(msg):
                        raise _SessionTakenOver(msg.get("message", ""))
                    if msg.get("trnm") == "PING":
                        await ws.send(raw)
                        continue
                    if msg.get("trnm") == "REAL":
                        for d in msg.get("data", []):
                            if d.get("type") == RT_ORDER:
                                await broadcast(_fill_msg(d))
        except asyncio.CancelledError:
            return
        except _SessionTakenOver as e:
            logger.warning(f"⚠️ mock 체결 리스너 세션 종료 — 동일 App key 중복({e}). 중단.")
            return
        except Exception as e:
            logger.warning(f"mock 체결 리스너 오류: {e}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

# 실시간 타입 — docs/kiwoom-rest-api.pdf p.6 인덱스 확인
RT_ORDER = "00"        # 주문체결 (p.470) — 모의 주문 체결 스트림
RT_VI = "1h"            # VI발동/해제 (p.528)
RT_TRADE = "0B"        # 주식체결 (p.480) — KRX 재개 감지
RT_QUOTE = "0D"        # 주식호가잔량 (p.486) — NXT 최우선매도호가/잔량
RT_EXPECTED = "0H"     # 주식예상체결 (p.504) — KRX 예상체결가. (0E는 시간외호가!)
TTL_SEC = 210          # 단일가120 + 랜덤엔드30 + 여유60
_NXT_POLL_SEC = 1.0    # NXT 호가 REST(ka10004) 폴링 간격 (실시간 WS NXT 미수신 대체)

# FID — docs 확인 (p.471/481/487/505/529)
FID_CODE = "9001"       # 종목코드
FID_NAME = "302"        # 종목명
FID_PRICE = "10"        # 현재가/예상체결가
FID_ASK1 = "41"         # 0D 매도호가1(최우선)
FID_ASKQTY1 = "61"      # 0D 매도호가수량1
FID_TRADE_ASK = "27"    # 0B (최우선)매도호가
# VI 1h FIDs (p.529, 라이브 raw 검증)
FID_VI_GUBUN = "1225"    # VI적용구분: 정적/동적/동적+정적
FID_VI_TRIGGER = "1221"  # VI발동가격(원)
FID_VI_KIND = "9068"     # VI발동구분: 1=발동, 2=해제
FID_VI_DIR = "9069"      # 발동방향구분: 1=상방(+), 2=하방(-)
FID_VI_RATE_S = "1238"   # 괴리율 정적(%)
FID_VI_RATE_D = "1239"   # 괴리율 동적(%)
FID_VI_RELEASE = "1224"  # VI해제시각(HHmmss) — 보조


class _SessionTakenOver(Exception):
    """동일 App key 로 다른 곳에서 접속 → 이 세션이 종료됨 (재연결 중단 신호)."""


def _is_session_takeover(msg: dict) -> bool:
    return msg.get("trnm") == "SYSTEM" and (
        str(msg.get("code")) == "R10001" or "App key" in str(msg.get("message", "")))


def _num(v) -> float:
    """시세 부호(+/-)·콤마 정규화 (rq-01 FR-07)."""
    if v is None:
        return 0.0
    try:
        return abs(float(str(v).replace(",", "").lstrip("+-")))
    except (TypeError, ValueError):
        return 0.0


class _Watch:
    __slots__ = ("code", "name", "trigger", "gubun", "direction", "vi_pct",
                 "expire", "krx_resumed", "first_buy", "max_profit_pct", "ordered", "released")

    def __init__(self, code, name, trigger, gubun, direction, vi_pct):
        self.code, self.name, self.trigger = code, name, trigger
        self.gubun, self.direction, self.vi_pct = gubun, direction, vi_pct
        self.expire = time.time() + TTL_SEC
        self.krx_resumed = False
        self.first_buy = None
        self.max_profit_pct = 0.0
        self.ordered = False
        self.released = False


async def _place_mock_order(broadcast, w: "_Watch") -> None:
    """VI 발동 종목에 모의 매수 (장중이면 체결 → 00 스트림으로 수신)."""
    from services import kiwoom_order
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(
        None, lambda: kiwoom_order.place_order(w.code, "buy", price=w.trigger or None, exchange="KRX"))
    await broadcast({"type": "order", "code": w.code, "name": w.name,
                     "direction": w.direction, "ok": res.get("ok"),
                     "ord_no": res.get("ord_no"), "reason": res.get("reason", ""),
                     "ts": _now_iso()})


async def run(broadcast, is_active) -> None:
    """관측 메인 루프 (지수 백오프 재연결). broadcast: async 콜백, is_active: ()->bool.

    관측 WS = real 환경(NXT 차익 괴리). 주문 = mock(kiwoom_order). 하이브리드.
    """
    backoff = 1
    logger.info(f"⚡ VI 관측 환경={VI_ARB_OBS_ENV}({_OBS['base_url']}) · 주문=mock")
    while is_active():
        try:
            token = _env_token(_OBS)
            if not token:
                logger.warning("관측 토큰 없음 — 중단")
                return
            async with await _env_ws_connect(_OBS) as ws:
                await ws.send(json.dumps({"trnm": "LOGIN", "token": token}))
                login = json.loads(await ws.recv())
                if str(login.get("return_code")) not in ("0", "None") and login.get("trnm") != "LOGIN":
                    logger.warning(f"Kiwoom WS LOGIN 응답: {login}")
                # 1h(VI) 구독 (real WS) — 유니버스 있으면 종목 한정, 없으면 전종목
                items = VI_ARB_UNIVERSE or [""]
                await ws.send(json.dumps({"trnm": "REG", "grp_no": "1", "refresh": "1",
                                          "data": [{"item": items, "type": [RT_VI]}]}))
                mode_label = "모의 매수 활성" if VI_ARB_ORDER else "관측 전용 — NO ORDERS"
                logger.info(f"⚡ VI 관측 시작 ({mode_label}) "
                            f"universe={'전종목' if items == [''] else len(items)}")
                backoff = 1
                watches: dict[str, _Watch] = {}
                recent: dict = {}  # (code,kind)→time, 거래소 중복(KRX/NXT/SOR) 제거용
                # 주문 활성 시 mock WS 체결(00) 리스너 병행 (모의 체결은 mock 도메인에서만 수신)
                fill_task = asyncio.create_task(_mock_fill_listener(broadcast, is_active)) if VI_ARB_ORDER else None
                try:
                    await _recv_loop(ws, broadcast, is_active, watches, recent)
                finally:
                    if fill_task:
                        fill_task.cancel()
        except asyncio.CancelledError:
            return
        except _SessionTakenOver as e:
            logger.warning(f"⚠️ 관측 세션 종료 — 동일 App key 중복 접속({e}). 재연결 중단.")
            return
        except Exception as e:
            logger.warning(f"Kiwoom 관측 연결 오류: {e} — {backoff}s 후 재연결")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


async def _recv_loop(ws, broadcast, is_active, watches, recent) -> None:
    while is_active():
        raw = await asyncio.wait_for(ws.recv(), timeout=60)
        msg = json.loads(raw)
        if _is_session_takeover(msg):
            raise _SessionTakenOver(msg.get("message", ""))
        trnm = msg.get("trnm")
        if trnm == "PING":
            await ws.send(raw)  # echo 원문 그대로 (FR-02)
            continue
        if trnm == "REAL":
            for d in msg.get("data", []):
                await _on_real(ws, broadcast, watches, recent, d)
        # TTL 만료 정리
        now = time.time()
        for code in [c for c, w in watches.items() if w.expire < now]:
            await _unsub(ws, code)
            watches.pop(code, None)


async def _on_real(ws, broadcast, watches, recent, d: dict) -> None:
    rtype = d.get("type")
    raw_item = d.get("item") or ""
    item = raw_item.replace("_NX", "").replace("_AL", "")
    vals = d.get("values", {}) or {}
    # 거래소 접미사 제거 → base 종목코드 (KRX/NXT/SOR VI 이벤트 통합)
    code = (vals.get(FID_CODE) or item or "").strip().replace("_NX", "").replace("_AL", "")
    if not code:
        return

    is_nxt = "_NX" in raw_item

    if rtype == RT_ORDER:
        # 00 주문체결 스트림 (p.471 FID): 913 주문상태, 910 체결가, 911 체결량
        await broadcast({
            "type": "order_fill", "code": code, "name": vals.get("302", code),
            "status": vals.get("913", ""), "ord_no": vals.get("9203", ""),
            "side": "매수" if vals.get("907") == "2" else "매도" if vals.get("907") == "1" else "",
            "ord_qty": round(_num(vals.get("900"))), "fill_price": round(_num(vals.get("910"))),
            "fill_qty": round(_num(vals.get("911"))), "exchange": vals.get("2135", ""),
            "ts": _now_iso(),
        })
        return

    if rtype == RT_VI:
        # VI 발동/해제 — 라이브 raw 검증 FID 기준
        gubun = (vals.get(FID_VI_GUBUN) or "정적").strip()
        trigger = round(_num(vals.get(FID_VI_TRIGGER)))
        kind = "해제" if str(vals.get(FID_VI_KIND)) == "2" else "발동"   # 9068: 1발동/2해제
        direction = "-" if str(vals.get(FID_VI_DIR)) == "2" else "+"    # 9069: 1상방/2하방
        # 발동률 = 괴리율 (동적→1239, 정적→1238). 부호 제거한 절대값.
        rate_fid = FID_VI_RATE_S if "정적" in gubun and "동적" not in gubun else FID_VI_RATE_D
        vi_pct = round(_num(vals.get(rate_fid)), 2) or None
        name = vals.get(FID_NAME) or d.get("name", code)

        # 거래소(KRX/NXT/SOR) 중복 제거 — (code,kind) 2초 윈도우
        key = (code, kind)
        now = time.time()
        if key in recent and now - recent[key] < 2.0:
            return
        recent[key] = now

        # 발동·해제 모두 방송 (관측·기록)
        await broadcast({"type": "vi", "code": code, "name": name, "kind": kind,
                         "gubun": gubun, "direction": direction, "vi_pct": vi_pct,
                         "trigger_price": trigger, "ts": _now_iso()})
        # NXT 상장 종목만 동적구독/모의주문 (비상장은 스프레드 불가)
        if kind == "발동" and code not in watches and await _is_nxt_listed(code):
            w = _Watch(code, name, trigger, gubun, direction, vi_pct)
            watches[code] = w
            await _sub_dynamic(ws, code)                       # KRX 예상체결(WS)
            asyncio.create_task(_poll_nxt_spread(broadcast, w))  # NXT 매도호가(REST 폴링)
            if VI_ARB_ORDER:
                w.ordered = True
                await _place_mock_order(broadcast, w)
        return

    w = watches.get(code)
    if not w:
        return

    if not is_nxt:
        # KRX 측: 0H 예상체결가(FID10) / 0B 첫 체결=랜덤엔드 재개
        if rtype == RT_TRADE and not w.krx_resumed:
            w.krx_resumed = True  # FR-06
            await broadcast({"type": "krx_resume", "code": code, "name": w.name,
                             "direction": w.direction, "randomend_sec": None, "ts": _now_iso()})
        if rtype in (RT_EXPECTED, RT_TRADE):
            w._krx = round(_num(vals.get(FID_PRICE)))
    else:
        # NXT 측: 0D 최우선매도호가(41)/잔량(61), 0B 매도호가(27) 보조
        nxt_ask = round(_num(vals.get(FID_ASK1) or vals.get(FID_TRADE_ASK) or vals.get(FID_PRICE)))
        krx_exp = getattr(w, "_krx", 0)
        if nxt_ask > 0 and krx_exp > 0:
            spread = krx_exp - nxt_ask
            cost = krx_exp * TAX + (nxt_ask + krx_exp) * FEE
            net = spread - cost
            if w.first_buy is None:
                w.first_buy = nxt_ask
            w.max_profit_pct = max(w.max_profit_pct, (krx_exp - w.first_buy) / w.first_buy * 100)
            await broadcast({
                "type": "spread", "code": code, "name": w.name, "direction": w.direction,
                "sec_since_vi": round(TTL_SEC - (w.expire - time.time()), 1),
                "krx_expected": krx_exp, "nxt_best_ask": nxt_ask,
                "nxt_ask_qty": round(_num(vals.get(FID_ASKQTY1))) or None,
                "first_buy": w.first_buy, "spread": round(spread), "cost": round(cost),
                "net_spread": round(net), "net_pct": round(net / nxt_ask * 100, 3),
                "max_profit_pct": round(w.max_profit_pct, 3),
                "opportunity": 1 if net > cost * (EDGE_BUFFER - 1) else 0, "ts": _now_iso(),
            })


async def _sub_dynamic(ws, code: str) -> None:
    """VI 발동 종목 동적 구독: {code}_NX(0B,0D) / {code}(0B,예상) (FR-04)."""
    # KRX 만 WS 구독(0B 체결 + 0H 예상체결). NXT 는 실시간 WS 미수신 → ka10004 REST 폴링.
    await ws.send(json.dumps({"trnm": "REG", "grp_no": "2", "refresh": "1", "data": [
        {"item": [code], "type": [RT_TRADE, RT_EXPECTED]},
    ]}))


async def _unsub(ws, code: str) -> None:
    await ws.send(json.dumps({"trnm": "REMOVE", "grp_no": "2", "data": [
        {"item": [f"{code}_NX", code], "type": [RT_TRADE, RT_QUOTE, RT_EXPECTED]},
    ]}))
