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
import math
import time
from pathlib import Path

from config import (KIWOOM_ENVS, VI_ARB_UNIVERSE, VI_ARB_ORDER, VI_ARB_OBS_ENV,
                    VI_ARB_ORDER_QTY, VI_ARB_MIN_MCAP)
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

    NXT 호가 = ka10004(code_NX): sel_fpr_bid(매도호가=매수체결가) / buy_fpr_bid(매수호가=매도체결가)
    KRX 기준가 = WS 0H 예상체결가 우선 → ka10001.exp_cntr_pric → cur_prc(스테일)
    양방향 차익: KRX예상>NXT매도호가 → NXT매수/KRX매도 / KRX예상<NXT매수호가 → NXT매도/KRX매수.
    """
    loop = asyncio.get_event_loop()
    while time.time() < w.expire:
        now = time.time()
        sec_since_vi = round(TTL_SEC - (w.expire - now), 1)
        fresh_0h = w._krx > 0 and (now - w._krx_ts) < _KRX_0H_FRESH_SEC
        # 발동후 윈도우(10s) 경과 / 해제 / (재개+0H끊김) → 단일가 차익 종료 → 폴링 중단
        if sec_since_vi > _OPP_WINDOW_SEC or w.released or (w.krx_resumed and not fresh_0h):
            break
        nxt = await loop.run_in_executor(None, lambda: _rest("ka10004", f"{w.code}_NX"))
        nxt_ask = round(_num(nxt.get("sel_fpr_bid")))   # NXT 최우선 매도호가 = 내가 매수하는 가격
        nxt_bid = round(_num(nxt.get("buy_fpr_bid")))   # NXT 최우선 매수호가 = 내가 매도하는 가격
        # KRX 예상체결가: WS 0H(신선) 최우선 → REST exp_cntr_pric → cur_prc(스테일)
        if fresh_0h:
            krx_exp, single_price = w._krx, True
        else:
            krx = await loop.run_in_executor(None, lambda: _rest("ka10001", w.code))
            exp = round(_num(krx.get("exp_cntr_pric")))
            if exp > 0:
                krx_exp, single_price = exp, True
            else:
                krx_exp, single_price = round(_num(krx.get("cur_prc"))), False
        # 수익 방향 결정: KRX예상 > NXT매도호가 → NXT 싸게매수→KRX 비싸게매도
        #                KRX예상 < NXT매수호가 → NXT 비싸게매도→KRX 싸게매수
        side = nxt_px = None
        nxt_qty = None
        spread = 0
        if krx_exp > 0 and nxt_ask > 0 and krx_exp > nxt_ask:
            side, nxt_px = "매수", nxt_ask
            nxt_qty = round(_num(nxt.get("sel_fpr_req"))) or None
            spread = krx_exp - nxt_px
        elif krx_exp > 0 and nxt_bid > 0 and krx_exp < nxt_bid:
            side, nxt_px = "매도", nxt_bid
            nxt_qty = round(_num(nxt.get("buy_fpr_req"))) or None
            spread = nxt_px - krx_exp
        else:
            nxt_px = nxt_ask or nxt_bid                  # 차익 방향 없음(관측 틱)
            spread = (krx_exp - nxt_px) if (nxt_px and krx_exp > 0) else 0
        if nxt_px and krx_exp > 0:
            cost = krx_exp * TAX + (nxt_px + krx_exp) * FEE
            net = spread - cost
            # opportunity = 수익방향 존재 + 진짜 단일가 + 발동 초기 윈도우 내 + 순이익 > 비용버퍼
            opportunity = (side is not None and single_price and sec_since_vi <= _OPP_WINDOW_SEC
                           and net > cost * (EDGE_BUFFER - 1))
            # 진입가(first_buy) 는 첫 기회 시점 NXT 체결가(매수=ask/매도=bid)로 고정
            if opportunity and w.first_buy is None:
                w.first_buy = nxt_px
            if w.first_buy and side:
                # 진입가 대비 KRX 방향 수익%: 매수=KRX 상승분 / 매도=KRX 하락분
                gain = (krx_exp - w.first_buy) if side == "매수" else (w.first_buy - krx_exp)
                w.max_profit_pct = max(w.max_profit_pct, gain / w.first_buy * 100)
            await broadcast({
                "type": "spread", "code": w.code, "name": w.name, "direction": w.direction,
                "side": side, "sec_since_vi": sec_since_vi, "single_price": 1 if single_price else 0,
                "krx_expected": krx_exp, "nxt_best_ask": nxt_px, "nxt_ask_qty": nxt_qty,
                "first_buy": w.first_buy, "spread": round(spread), "cost": round(cost),
                "net_spread": round(net), "net_pct": round(net / nxt_px * 100, 3),
                "max_profit_pct": round(w.max_profit_pct, 3),
                "opportunity": 1 if opportunity else 0, "ts": _now_iso()})
        await asyncio.sleep(_NXT_POLL_SEC)


def _env_ws_connect(env: dict):
    """주어진 환경 WS 연결 (wss://{domain}:10000/api/dostk/websocket)."""
    import ssl
    import urllib.parse
    import websockets
    host = urllib.parse.urlparse(env["base_url"]).netloc
    ctx = ssl.create_default_context()
    # ping_interval=None: 라이브러리 자동 ping 비활성 — Kiwoom 은 프로토콜 ping 에 응답 안 해
    # ~20s 후 keepalive timeout(1011)으로 끊김. 대신 Kiwoom 앱레벨 PING(trnm=PING) echo 로 유지.
    return websockets.connect(f"wss://{host}:10000/api/dostk/websocket", ssl=ctx,
                              open_timeout=15, ping_interval=None)


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


# ---- 디스코드 체결 알림 큐 — 버스트(일괄매도 등)를 배치로 묶어 레이트리밋 회피 ----
_DQ_BATCH = 10        # 한 메시지로 묶는 최대 건수 (2000자 제한 內)
_DQ_GRACE = 0.5       # 첫 건 수신 후 추가 건 수집 대기(초)
_DQ_INTERVAL = 0.5    # 전송 간 간격(초) — 웹훅 ~5건/초 제한 대비 여유
_dq: asyncio.Queue | None = None
_dq_task: asyncio.Task | None = None


def _discord_send(content: str) -> None:
    """웹훅 1회 전송 (blocking, executor 용). 429 는 Retry-After 만큼 대기 후 1회 재시도."""
    from config import VI_ARB_DISCORD_WEBHOOK
    if not VI_ARB_DISCORD_WEBHOOK:
        return
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        VI_ARB_DISCORD_WEBHOOK, data=json.dumps({"content": content}).encode(),
        # 기본 Python-urllib UA 는 Cloudflare 가 403 차단 → 명시 UA 필수
        headers={"Content-Type": "application/json", "User-Agent": "trakit-vi-arb/1.0"},
        method="POST")
    for attempt in (0, 1):
        try:
            urllib.request.urlopen(req, timeout=5).read()
            return
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:
                try:
                    wait = float(e.headers.get("Retry-After") or 1.0)
                except (TypeError, ValueError):
                    wait = 1.0
                time.sleep(min(wait, 5.0))
                continue
            logger.warning(f"디스코드 체결 알림 실패: HTTP {e.code}")
            return
        except Exception as e:
            logger.warning(f"디스코드 체결 알림 실패: {e}")
            return


async def _dq_worker() -> None:
    """큐 소비 워커 — grace 동안 모인 알림을 줄바꿈으로 묶어 1회 전송."""
    loop = asyncio.get_event_loop()
    while True:
        lines = [await _dq.get()]
        await asyncio.sleep(_DQ_GRACE)
        while len(lines) < _DQ_BATCH:
            try:
                lines.append(_dq.get_nowait())
            except asyncio.QueueEmpty:
                break
        await loop.run_in_executor(None, _discord_send, "\n".join(lines))
        await asyncio.sleep(_DQ_INTERVAL)


def _enqueue_discord(content: str) -> None:
    global _dq, _dq_task
    if _dq is None:
        _dq = asyncio.Queue(maxsize=200)
    try:
        _dq.put_nowait(content)
    except asyncio.QueueFull:
        logger.warning("디스코드 알림 큐 가득참 — 드롭")
        return
    if _dq_task is None or _dq_task.done():
        _dq_task = asyncio.get_event_loop().create_task(_dq_worker())


def _build_hourly_summary() -> str:
    """계좌·관측 현황 요약 텍스트 (blocking — executor 에서 호출)."""
    from services import kiwoom_order, vi_arb_store
    bal = kiwoom_order.get_balance()
    s = vi_arb_store.today_stats()
    today_pl = kiwoom_order.today_realized_pl() or 0
    buy_amt = bal.get("buy_amount") or 0
    today_rt = f" ({today_pl / buy_amt * 100:+.2f}%)" if buy_amt else ""
    budget_txt = f"{_order_budget:,}원" if _order_budget else "무제한"
    return (
        f"📊 VI 매수 요약 ({_now_iso()[11:16]})\n"
        f"🏦 모의계좌 {bal.get('account', '')} · 예수금 {bal.get('deposit', 0):,}원"
        f" · 예탁자산평가 {bal.get('asset_value', 0):,}원\n"
        f"매수원금 {buy_amt:,}원 / 목표 {budget_txt}\n"
        f"평가손익(미실현) {bal.get('eval_pl', 0):+,}원 ({bal.get('eval_pl_rt', 0):+}%)"
        f" · 실현손익(오늘) {today_pl:+,}원{today_rt}\n"
        f"보유 {len(bal.get('holdings') or [])}종목 · 지정가매도 등록 {len(_limit_sells)}종목\n"
        f"VI 발동 {s['vi']} · 기회 포착 {s['opp']} · 스프레드 틱 {s['ticks']} · 매수 {s['buys']}회")


async def hourly_summary_loop() -> None:
    """VI 매수 가동 중(_order_enabled)이면 매 정시에 디스코드 요약 전송 (app lifespan 에서 기동)."""
    loop = asyncio.get_event_loop()
    while True:
        await asyncio.sleep(3600 - time.time() % 3600)   # 다음 정시(:00)까지 대기
        if not _order_enabled:
            continue
        try:
            _enqueue_discord(await loop.run_in_executor(None, _build_hourly_summary))
        except Exception as e:
            logger.warning(f"VI 시간별 요약 실패: {e}")


def _notify_fill(m: dict) -> None:
    """체결 메시지 → 디스코드 알림 큐 적재 (매수 전부 + 매도 전부, 지정가 여부 표기)."""
    if m["fill_qty"] <= 0 or m["side"] not in ("매수", "매도"):
        return
    was_limit = m["side"] == "매도" and m["code"] in _limit_sells
    title = ("⚡ VI 매수 체결" if m["side"] == "매수"
             else "🎉 지정가 매도 체결" if was_limit else "💸 매도 체결")
    _enqueue_discord(f"{title} | {m.get('name') or m['code']}({m['code']}) "
                     f"{m['fill_qty']}주 @{m['fill_price']:,}원")


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
                                m = _fill_msg(d)
                                _notify_fill(m)   # 디스코드 체결 알림 (지정가 여부는 차감 전 판별)
                                if m["side"] == "매도" and m["fill_qty"] > 0:
                                    reduce_limit_sell(m["code"], m["fill_qty"])  # 지정가 매도 체결 → 등록 해제
                                await broadcast(m)
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
_OPP_WINDOW_SEC = 10   # 발동 후 이 시간까지만 수신/opportunity 인정 (초기 괴리만 유효, 이후 수렴) — 경과 시 폴링 중단
_KRX_0H_FRESH_SEC = 3  # WS 0H 예상체결가가 이 시간 내 수신됐으면 = 아직 단일가 구간 (REST 폴백보다 우선)

# 런타임 모의주문 제어 (FE 시작/종료 토글). 기본: 정지 — 사용자가 '시작' 버튼으로 명시 시작.
# --reload 워커 재시작 시 메모리 초기화로 매수가 조용히 꺼지는 문제 → 당일 한정 파일 영속화.
_order_enabled = False
_order_dir = "+"           # 기본 방향 스코프: 상방(매수)
_order_budget = 0          # 목표 매수 원금(원). 0=무제한. 현재 매수원금이 이 값 도달 시 매수 중단
_invested_amt = 0.0        # 현재 매수원금 추정 (balance 동기화 + 매수 시 즉시 증가)
_buy_dirs: dict[str, str] = {}   # 오늘 매수 종목 code → VI 방향(+/-)
_limit_sells: dict[str, dict] = {}   # 지정가 매도 등록 code → {ord_no, price, qty}
_min_mcap = VI_ARB_MIN_MCAP      # VI 매수 시총 하한(억원). 미만 종목 매수 스킵, 0=필터 없음

_STATE_FILE = Path(__file__).resolve().parent.parent / ".vi_arb_state.json"


def _today() -> str:
    return _now_iso()[:10]


def _save_state() -> None:
    """주문 제어 + 오늘 매수 종목 VI 방향을 디스크 영속화 (당일 한정)."""
    try:
        _STATE_FILE.write_text(json.dumps({
            "date": _today(), "enabled": _order_enabled, "dir": _order_dir,
            "budget": _order_budget, "min_mcap": _min_mcap, "buy_dirs": _buy_dirs,
            "limit_sells": _limit_sells}, ensure_ascii=False))
    except OSError as e:
        logger.warning(f"VI-arb 상태 저장 실패: {e}")


def _load_state() -> None:
    global _order_enabled, _order_dir, _order_budget, _buy_dirs, _limit_sells, _min_mcap
    try:
        d = json.loads(_STATE_FILE.read_text())
    except (OSError, ValueError):
        return
    if d.get("date") != _today():
        return  # 전일 상태는 복원하지 않음 (매수 자동 재개 방지)
    _order_enabled = bool(d.get("enabled", False))
    _order_dir = d.get("dir") if d.get("dir") in ("all", "+", "-") else "+"
    _order_budget = max(0, int(d.get("budget") or 0))
    if d.get("min_mcap") is not None:
        _min_mcap = max(0, int(d.get("min_mcap") or 0))
    _buy_dirs = {str(k): v for k, v in (d.get("buy_dirs") or {}).items() if v in ("+", "-")}
    _limit_sells = {str(k): v for k, v in (d.get("limit_sells") or {}).items() if isinstance(v, dict)}
    if _order_enabled:
        logger.info(f"⚡ 모의주문 제어 복원: dir={_order_dir} budget={_order_budget} buy_dirs={len(_buy_dirs)}종목")


def record_buy_dir(code: str, direction: str) -> None:
    """오늘 매수 주문한 종목의 VI 방향 기록 — 보유종목 배지가 새로고침/재시작에도 유지."""
    if _buy_dirs.get(code) != direction:
        _buy_dirs[code] = direction
        _save_state()


def get_buy_dirs() -> dict:
    """오늘 매수 종목 code→VI방향(+/-) 맵 (WS hello 로 FE 에 전달)."""
    return dict(_buy_dirs)


def register_limit_sell(code: str, ord_no: str, price: int, qty: int) -> None:
    """지정가 매도 주문 등록 기록 (FE 버튼 상태 복원용, 당일 영속)."""
    _limit_sells[code] = {"ord_no": str(ord_no), "price": int(price), "qty": int(qty),
                          "adj_ts": time.time()}   # 등록 시점부터 10분 후 자동 재조정 대상
    _save_state()


def pop_limit_sell(code: str) -> dict | None:
    e = _limit_sells.pop(code, None)
    if e:
        _save_state()
    return e


def get_limit_sells() -> dict:
    return dict(_limit_sells)


def reduce_limit_sell(code: str, fill_qty: int) -> None:
    """매도 체결 수신 → 등록 잔량 차감, 전량 체결 시 등록 해제."""
    e = _limit_sells.get(code)
    if not e or fill_qty <= 0:
        return
    e["qty"] = int(e["qty"]) - int(fill_qty)
    if e["qty"] <= 0:
        _limit_sells.pop(code, None)
    _save_state()


_READJ_SEC = 600.0   # 지정가 매도 자동 재조정 최소 간격 (추천가 갱신 주기와 동일)
_readj_lock: asyncio.Lock | None = None   # 동시 /balance 호출의 이중 정정 방지


async def readjust_limit_sells(holdings: list[dict]) -> None:
    """등록된 지정가 매도를 갱신된 추천 매도가로 자동 정정 (kt10002, 10분 간격).

    add_sell_targets 가 주입한 sell_target 과 등록 가격이 다르면 잔량 전부 정정.
    실패해도 10분 backoff (반복 호출 방지), '원주문 없음' 류는 등록 해제.
    동시 호출(FE 폴링 + 수동 새로고침)은 Lock 으로 직렬화 — 이중 정정 시
    두 번째가 소멸된 원주문번호로 나가 등록이 풀리는 레이스 방지.
    """
    from services import kiwoom_order
    global _readj_lock
    if _readj_lock is None:
        _readj_lock = asyncio.Lock()
    loop = asyncio.get_event_loop()
    async with _readj_lock:
        await _readjust_locked(kiwoom_order, loop, holdings)


async def _readjust_locked(kiwoom_order, loop, holdings: list[dict]) -> None:
    for h in holdings:
        code, target = h.get("code"), int(h.get("sell_target") or 0)
        e = _limit_sells.get(code)
        if not (e and target) or target == int(e["price"]):
            continue
        now = time.time()
        if now - float(e.get("adj_ts") or 0) < _READJ_SEC:
            continue
        r = await loop.run_in_executor(
            None,
            lambda o=e["ord_no"], c=code, p=target: kiwoom_order.modify_order(o, c, price=p, qty=0))
        if r.get("ok"):
            e.update(ord_no=str(r.get("ord_no") or e["ord_no"]), price=target, adj_ts=now)
            logger.info(f"♻️ 지정가 매도 자동 재조정: {code} → {target:,}원 (#{e['ord_no']})")
        elif "원주문" in str(r.get("reason", "")):
            _limit_sells.pop(code, None)   # 이미 체결/취소된 주문 → 등록 해제
            logger.info(f"♻️ 지정가 매도 등록 해제(원주문 소멸): {code}")
        else:
            e["adj_ts"] = now              # 실패 backoff
            logger.warning(f"지정가 매도 재조정 실패: {code} → {target:,}원 ({r.get('reason')})")
        _save_state()


def set_order_control(enabled: bool, direction: str = "all", budget=None, min_mcap=None) -> dict:
    global _order_enabled, _order_dir, _order_budget, _min_mcap
    _order_enabled = bool(enabled)
    _order_dir = direction if direction in ("all", "+", "-") else "all"
    if budget is not None:
        try:
            _order_budget = max(0, int(budget))
        except (TypeError, ValueError):
            pass
    if min_mcap is not None:
        try:
            _min_mcap = max(0, int(min_mcap))
        except (TypeError, ValueError):
            pass
    logger.info(f"⚡ 모의주문 제어: enabled={_order_enabled} dir={_order_dir} "
                f"budget={_order_budget} min_mcap={_min_mcap}억")
    _save_state()
    return get_order_control()


def get_order_control() -> dict:
    return {"enabled": _order_enabled, "dir": _order_dir, "budget": _order_budget,
            "min_mcap": _min_mcap, "invested": round(_invested_amt)}


def set_invested(amount) -> None:
    """현재 매수원금(추정) 동기화 — /balance 조회 시 호출해 캐시 보정."""
    global _invested_amt
    try:
        _invested_amt = float(amount)
    except (TypeError, ValueError):
        pass


def _add_invested(amount: float) -> None:
    global _invested_amt
    _invested_amt += amount


def _budget_ok() -> bool:
    """목표 매수 원금 미설정(0)이거나 현재 매수원금이 목표 미만이면 매수 허용."""
    return not _order_budget or _invested_amt < _order_budget


_load_state()  # --reload/재시작 시 당일 주문 제어·매수 방향 복원


# ---- 추천 매도가 (당일 변동폭 기반 수익 실현 목표, 10분 캐시) ----
_QUOTE_TTL = 600.0                                  # 10분
_quote_cache: dict[str, tuple[float, dict]] = {}    # code → (ts, {high, low, upl})


def _tick_ceil(p: float) -> int:
    """KRX 호가단위로 올림 — 매도 주문 가능한 가격."""
    for limit, unit in ((2000, 1), (5000, 5), (20000, 10), (50000, 50), (200000, 100), (500000, 500)):
        if p < limit:
            return math.ceil(p / unit) * unit
    return math.ceil(p / 1000) * 1000


def _day_range(code: str) -> dict | None:
    """당일 고가/저가/상한가 (ka10001, 10분 캐시). 조회 실패 시 stale 캐시 유지."""
    now = time.time()
    c = _quote_cache.get(code)
    if c and now - c[0] < _QUOTE_TTL:
        return c[1]
    r = _rest("ka10001", code)
    d = {"high": _num(r.get("high_pric")), "low": _num(r.get("low_pric")),
         "upl": _num(r.get("upl_pric"))}
    if not d["high"]:
        return c[1] if c else None
    _quote_cache[code] = (now, d)
    return d


async def add_sell_targets(holdings: list[dict]) -> None:
    """보유종목에 추천 매도가(sell_target) 주입 — /balance 응답에 인라인.

    수익 관점: max(세후 손익분기가, 현재가 + 당일변동폭×0.5) 를 상한가로 캡 후 호가단위 올림.
    당일 고저는 ka10001 을 10분 캐시로 조회 (캐시 미스만 4-동시 병렬).
    """
    loop = asyncio.get_event_loop()
    sem = asyncio.Semaphore(4)

    async def fill(h: dict) -> None:
        code, avg, cur = h.get("code"), h.get("avg") or 0, h.get("cur") or 0
        if not (code and avg and cur):
            return
        async with sem:
            d = await loop.run_in_executor(None, lambda: _day_range(code))
        breakeven = avg * (1 + 2 * FEE + TAX)                            # 왕복 수수료 + 매도 거래세
        if not d:
            # 개장 전 등 당일 고저 미형성 → 세후 손익분기 기반 폴백 (변동폭 항 없이)
            t = _tick_ceil(breakeven)
            h["sell_target"] = t
            h["sell_target_rt"] = round((t * (1 - TAX - FEE) - avg) / avg * 100, 2)
            return
        target = max(breakeven, cur + 0.5 * max(d["high"] - d["low"], 0))  # 변동폭 절반 위 익절
        if d.get("upl"):
            target = min(target, d["upl"])                               # 상한가 캡
        t = _tick_ceil(target)
        h["sell_target"] = t
        # 평단 대비 세후 수익률 — 매도 거래세+수수료 차감 (FE netAfterCost 와 동일 컨벤션)
        h["sell_target_rt"] = round((t * (1 - TAX - FEE) - avg) / avg * 100, 2)

    await asyncio.gather(*(fill(h) for h in holdings))

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
                 "expire", "krx_resumed", "first_buy", "max_profit_pct", "ordered",
                 "released", "_krx", "_krx_ts")

    def __init__(self, code, name, trigger, gubun, direction, vi_pct):
        self.code, self.name, self.trigger = code, name, trigger
        self.gubun, self.direction, self.vi_pct = gubun, direction, vi_pct
        self.expire = time.time() + TTL_SEC
        self.krx_resumed = False
        self._krx = 0
        self._krx_ts = 0.0
        self.first_buy = None
        self.max_profit_pct = 0.0
        self.ordered = False
        self.released = False


_mcap_cache: dict[str, tuple[float, int]] = {}   # code → (ts, 시가총액 억원)
_MCAP_TTL = 3600.0


def _market_cap(code: str) -> int:
    """시가총액 조회 (ka10001 mac, 억원, 1시간 캐시). 조회 실패 시 0."""
    now = time.time()
    c = _mcap_cache.get(code)
    if c and now - c[0] < _MCAP_TTL:
        return c[1]
    r = _rest("ka10001", code)
    try:
        mac = int(str(r.get("mac") or "0").replace(",", "").lstrip("+-") or 0)
    except (TypeError, ValueError):
        mac = 0
    if mac:
        _mcap_cache[code] = (now, mac)
    return mac


async def _mcap_ok(code: str, name: str) -> bool:
    """VI 매수 시총 필터 — _min_mcap(억원) 미만이면 False. 조회 실패(0)는 통과(매수 차단 안 함)."""
    if not _min_mcap:
        return True
    mcap = await asyncio.get_event_loop().run_in_executor(None, _market_cap, code)
    if mcap and mcap < _min_mcap:
        logger.info(f"⛔ 시총 필터: {name}({code}) {mcap:,}억 < {_min_mcap:,}억 — 매수 스킵")
        return False
    return True


async def _place_mock_order(broadcast, w: "_Watch") -> None:
    """VI 발동 종목에 모의 주문 (상방=매수 / 하방=매도). 장중 체결 → 00 스트림 수신.
    주의: mockapi(KRX 전용)는 공매도 불가 → 하방 매도는 보유 없으면 거부될 수 있음."""
    from services import kiwoom_order
    side = "sell" if w.direction == "-" else "buy"
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(
        None, lambda: kiwoom_order.place_order(w.code, side, price=w.trigger or None, exchange="KRX"))
    if res.get("ok") and side == "buy":
        record_buy_dir(w.code, w.direction)   # 보유종목 VI 방향 배지 영속화
    await broadcast({"type": "order", "code": w.code, "name": w.name,
                     "direction": w.direction, "side": "매수" if side == "buy" else "매도",
                     "ok": res.get("ok"), "ord_no": res.get("ord_no"),
                     "reason": res.get("reason", ""), "ts": _now_iso()})


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
                # 토큰 발급 일시 실패(레이트리밋/지정단말기 등) — 영구 중단하면 관측이
                # 침묵 속에 죽으므로 백오프 재시도 (12:31~15:01 2.5h 중단 사고 재발 방지)
                logger.warning(f"관측 토큰 없음 — {backoff}s 후 재시도")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
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
        m = {
            "type": "order_fill", "code": code, "name": vals.get("302", code),
            "status": vals.get("913", ""), "ord_no": vals.get("9203", ""),
            "side": "매수" if vals.get("907") == "2" else "매도" if vals.get("907") == "1" else "",
            "ord_qty": round(_num(vals.get("900"))), "fill_price": round(_num(vals.get("910"))),
            "fill_qty": round(_num(vals.get("911"))), "exchange": vals.get("2135", ""),
            "ts": _now_iso(),
        }
        _notify_fill(m)   # 디스코드 체결 알림 (지정가 여부는 차감 전 판별)
        if m["side"] == "매도" and m["fill_qty"] > 0:
            reduce_limit_sell(code, m["fill_qty"])  # 지정가 매도 체결 → 등록 해제
        await broadcast(m)
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
        # 해제(연속매매 재개) → 기존 watch 종료 표시 → 폴러가 단일가 차익 방출 중단
        if kind == "해제":
            ew = watches.get(code)
            if ew:
                ew.released = True
        # NXT 상장 종목만 동적구독/모의주문 (비상장은 스프레드 불가)
        if kind == "발동" and code not in watches and await _is_nxt_listed(code):
            w = _Watch(code, name, trigger, gubun, direction, vi_pct)
            watches[code] = w
            await _sub_dynamic(ws, code)                       # KRX 예상체결(WS)
            asyncio.create_task(_poll_nxt_spread(broadcast, w))  # NXT 매도호가(REST 폴링)
            if (_order_enabled and _order_dir in ("all", direction) and _budget_ok()
                    and (direction == "-" or await _mcap_ok(code, name))):  # 시총 필터는 매수(상방)만
                w.ordered = True
                await _place_mock_order(broadcast, w)
                # 매수 추정액 즉시 반영 (다음 VI 가 같은 캐시로 초과 매수하지 않도록)
                _add_invested((w.trigger or 0) * VI_ARB_ORDER_QTY)
        return

    w = watches.get(code)
    if not w:
        return

    if not is_nxt:
        # KRX 측: 0H=예상체결가(단일가) / 0B=첫 체결(랜덤엔드 재개)
        now = time.time()
        fresh_0h = w._krx > 0 and (now - w._krx_ts) < _KRX_0H_FRESH_SEC
        if rtype == RT_EXPECTED:
            w._krx = round(_num(vals.get(FID_PRICE)))   # 0H 예상체결가만 _krx 갱신 (체결가 오염 방지)
            w._krx_ts = now
        elif rtype == RT_TRADE and not w.krx_resumed and not fresh_0h:
            # 0H 끊긴 뒤의 체결 = 진짜 연속매매 재개 (단일가 중 0B 오인 방지)
            w.krx_resumed = True  # FR-06
            await broadcast({"type": "krx_resume", "code": code, "name": w.name,
                             "direction": w.direction, "randomend_sec": None, "ts": _now_iso()})
    else:
        # NXT 측: 0D 최우선매도호가(41)/잔량(61), 0B 매도호가(27) 보조
        nxt_ask = round(_num(vals.get(FID_ASK1) or vals.get(FID_TRADE_ASK) or vals.get(FID_PRICE)))
        krx_exp = getattr(w, "_krx", 0)
        if nxt_ask > 0 and krx_exp > 0:
            sec_since_vi = round(TTL_SEC - (w.expire - time.time()), 1)
            single_price = not w.krx_resumed          # 첫 KRX 체결 전 = 단일가 예상체결 구간
            spread = krx_exp - nxt_ask
            cost = krx_exp * TAX + (nxt_ask + krx_exp) * FEE
            net = spread - cost
            opportunity = (single_price and sec_since_vi <= _OPP_WINDOW_SEC
                           and net > cost * (EDGE_BUFFER - 1))
            if opportunity and w.first_buy is None:
                w.first_buy = nxt_ask
            if w.first_buy:
                w.max_profit_pct = max(w.max_profit_pct, (krx_exp - w.first_buy) / w.first_buy * 100)
            await broadcast({
                "type": "spread", "code": code, "name": w.name, "direction": w.direction,
                "sec_since_vi": sec_since_vi, "single_price": 1 if single_price else 0,
                "krx_expected": krx_exp, "nxt_best_ask": nxt_ask,
                "nxt_ask_qty": round(_num(vals.get(FID_ASKQTY1))) or None,
                "first_buy": w.first_buy, "spread": round(spread), "cost": round(cost),
                "net_spread": round(net), "net_pct": round(net / nxt_ask * 100, 3),
                "max_profit_pct": round(w.max_profit_pct, 3),
                "opportunity": 1 if opportunity else 0, "ts": _now_iso(),
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
