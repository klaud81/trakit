"""VI 차익거래 관측 — 실시간 WebSocket 허브 (A단계: mock 피드).

rq-01-001.md (KRX×NXT VI 랜덤엔드 차익거래 관측) 의 FR-05/06 모델을 따른
이벤트 스트림을 프론트엔드로 push 한다.

A단계: mock 제너레이터(랜덤엔드 갭 시뮬레이션) — Kiwoom 연동/시세신청 없이 즉시 동작.
B단계: 이 피드 자리에 실제 Kiwoom WS observer(1h VI + NXT/KRX 동적구독)를 꽂는다.
       FE 와 메시지 스키마는 동일하게 유지 → FE 변경 없이 데이터만 교체.

메시지 타입(JSON):
  hello       : 접속 시 1회 {mode, params}
  vi          : VI 발동/해제 {code,name,trigger_price,kind,gubun}
  spread      : 스프레드 틱 {sec_since_vi,krx_expected,nxt_best_ask,nxt_ask_qty,
                            spread,cost,net_spread,opportunity}
  krx_resume  : KRX 랜덤엔드 재개 {randomend_sec}
모든 메시지에 code,name,ts 포함.
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

# 비용 파라미터 (rq-01 FR-05 기본값)
TAX = 0.0015          # 매도 거래세
FEE = 0.00015         # 편도 수수료
EDGE_BUFFER = 1.5
_SIM_TARGET_QTY = 100  # Phase2 모의 목표 체결수량

# mock 유니버스 (종목코드, 종목명, 기준가)
_UNIVERSE = [
    ("005930", "삼성전자", 78000), ("000660", "SK하이닉스", 195000),
    ("373220", "LG에너지솔루션", 412000), ("207940", "삼성바이오로직스", 985000),
    ("005380", "현대차", 243000), ("035420", "NAVER", 168000),
    ("000270", "기아", 118000), ("105560", "KB금융", 84000),
    ("068270", "셀트리온", 178000), ("035720", "카카오", 47000),
]

# 데모용 압축 타임스케일(실제: 단일가 120s + 랜덤엔드 0~30s)
_SINGLE_PRICE_SEC = 12.0      # 단일가 구간(압축)
_TICK_SEC = 0.7               # 스프레드 틱 간격
_EPISODE_GAP = (4.0, 9.0)     # 다음 VI 발동까지 대기


def _now_iso() -> str:
    return datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now(KST).microsecond // 1000:03d}+09:00"


def _calc(krx_expected: int, nxt_best_ask: int) -> dict:
    spread = krx_expected - nxt_best_ask
    cost = krx_expected * TAX + (nxt_best_ask + krx_expected) * FEE
    net = spread - cost
    return {
        "spread": round(spread),
        "cost": round(cost),
        "net_spread": round(net),
        "opportunity": 1 if net > cost * (EDGE_BUFFER - 1) else 0,
    }


def _sim_fill(code: str, name: str, direction: str, entry: dict, krx_confirm: int) -> dict:
    """Phase2 모의 체결: NXT 매수 → KRX 확정가 청산 손익 (비용 차감)."""
    qty, buy = entry["qty"], entry["buy"]
    gross = (krx_confirm - buy) * qty
    cost = (krx_confirm * TAX + (buy + krx_confirm) * FEE) * qty
    net = gross - cost
    return {
        "type": "sim_fill", "code": code, "name": name, "direction": direction,
        "entry_buy": buy, "qty": qty, "krx_expected": entry["krx_exp"],
        "krx_confirm": krx_confirm, "gross": round(gross), "cost": round(cost),
        "net": round(net), "ret_pct": round(net / (buy * qty) * 100, 3),
        "win": 1 if net > 0 else 0, "ts": _now_iso(),
    }


class ViArbHub:
    """접속 클라이언트 관리 + mock 피드 태스크 (클라이언트 있을 때만 가동)."""

    def __init__(self) -> None:
        self._clients: set = set()
        self._feed_task: asyncio.Task | None = None

    @property
    def mode(self) -> str:
        from config import VI_ARB_SOURCE
        return VI_ARB_SOURCE

    async def connect(self, ws) -> None:
        await ws.accept()
        self._clients.add(ws)
        await ws.send_json({
            "type": "hello", "mode": self.mode, "ts": _now_iso(),
            "params": {"TAX": TAX, "FEE": FEE, "EDGE_BUFFER": EDGE_BUFFER},
        })
        if self._feed_task is None or self._feed_task.done():
            self._feed_task = asyncio.create_task(self._feed_loop())
        logger.info(f"⚡ VI-arb WS 접속 (clients={len(self._clients)})")

    def disconnect(self, ws) -> None:
        self._clients.discard(ws)
        if not self._clients and self._feed_task:
            self._feed_task.cancel()
            self._feed_task = None
        logger.info(f"⚡ VI-arb WS 종료 (clients={len(self._clients)})")

    async def _broadcast(self, msg: dict) -> None:
        # 백테스트용 영속화 (rq-01 FR-07). hello 는 제외.
        if msg.get("type") != "hello":
            try:
                from services import vi_arb_store
                vi_arb_store.record(msg, self.mode)
            except Exception:
                pass
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def _episode(self) -> None:
        """VI 1건 라이프사이클: 발동 → 단일가 스프레드 틱 → KRX 랜덤엔드 재개 → 해제."""
        code, name, base = random.choice(_UNIVERSE)
        sign = random.choice([1, -1])
        direction = "+" if sign > 0 else "-"          # 상방 / 하방 VI
        # KRX 개별종목 VI 2단계: 동적(직전체결가, KOSPI200 3%) / 정적(전일종가 10%)
        gubun = random.choice(["정적", "동적"])
        vi_rate = 0.10 if gubun == "정적" else 0.03   # 유니버스가 KOSPI200 → 동적 3%
        trigger = round(base * (1 + sign * vi_rate))
        vi_pct = round(vi_rate * 100, 1)
        await self._broadcast({"type": "vi", "code": code, "name": name, "kind": "발동",
                               "gubun": gubun, "direction": direction, "vi_pct": vi_pct,
                               "trigger_price": trigger, "ts": _now_iso()})

        # 단일가 구간: NXT 매도호가 vs KRX 예상체결가 스프레드 틱
        t0 = asyncio.get_event_loop().time()
        first_buy = None       # 이 VI 구간 최초 매수가(첫 NXT 매도호가)
        max_profit_pct = 0.0   # 최초매수가 기준 누적 최대수익%
        entry = None           # Phase2 모의진입: 첫 기회 틱에 NXT 매수
        last_krx = trigger
        while asyncio.get_event_loop().time() - t0 < _SINGLE_PRICE_SEC:
            sec = round(asyncio.get_event_loop().time() - t0, 1)
            mid = trigger * (1 + random.uniform(-0.004, 0.004))
            nxt_ask = round(mid * (1 + random.uniform(-0.002, 0.001)))
            # 가끔 KRX 예상가가 NXT 매도호가 위로 벌어지는 기회 발생
            gap = random.uniform(-0.001, 0.006) if random.random() < 0.35 else random.uniform(-0.001, 0.001)
            krx_exp = round(nxt_ask * (1 + gap))
            last_krx = krx_exp
            ask_qty = random.randint(5, 800)
            calc = _calc(krx_exp, nxt_ask)
            if first_buy is None:
                first_buy = nxt_ask
            # Phase2: 첫 기회(opportunity)에서 가상 진입 (실현가능 수량만큼)
            if calc["opportunity"] and entry is None:
                entry = {"buy": nxt_ask, "qty": min(_SIM_TARGET_QTY, ask_qty),
                         "krx_exp": krx_exp, "sec": sec}
            net_pct = calc["net_spread"] / nxt_ask * 100                 # 이번 틱 순이익%
            cur_profit_pct = (krx_exp - first_buy) / first_buy * 100     # 최초매수가→현재 KRX예상
            max_profit_pct = max(max_profit_pct, cur_profit_pct)
            await self._broadcast({
                "type": "spread", "code": code, "name": name, "direction": direction,
                "sec_since_vi": sec, "krx_expected": krx_exp, "nxt_best_ask": nxt_ask,
                "nxt_ask_qty": ask_qty, "first_buy": first_buy,
                "net_pct": round(net_pct, 3), "max_profit_pct": round(max_profit_pct, 3),
                "ts": _now_iso(), **calc,
            })
            await asyncio.sleep(_TICK_SEC)

        # KRX 랜덤엔드 재개 (0~30s 중 압축 표현)
        randomend = round(random.uniform(0, 30), 1)
        await self._broadcast({"type": "krx_resume", "code": code, "name": name,
                               "direction": direction, "randomend_sec": randomend, "ts": _now_iso()})

        # Phase2 모의 체결: 진입했으면 KRX 확정가로 청산 (레그 리스크 = 확정가가 진입예상가에서 이탈)
        if entry:
            drift = random.uniform(-0.006, 0.004)         # 확정가 이탈(음수=불리)
            krx_confirm = round(entry["krx_exp"] * (1 + drift))
            await self._broadcast(_sim_fill(code, name, direction, entry, krx_confirm))

        await self._broadcast({"type": "vi", "code": code, "name": name, "kind": "해제",
                               "gubun": gubun, "direction": direction, "vi_pct": vi_pct,
                               "trigger_price": trigger, "ts": _now_iso()})

    async def _feed_loop(self) -> None:
        try:
            if self.mode == "kiwoom":
                from services import vi_arb_kiwoom
                await vi_arb_kiwoom.run(self._broadcast, lambda: bool(self._clients))
            else:
                while self._clients:
                    await self._episode()
                    await asyncio.sleep(random.uniform(*_EPISODE_GAP))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"VI-arb 피드 오류({self.mode}): {e}")


hub = ViArbHub()
