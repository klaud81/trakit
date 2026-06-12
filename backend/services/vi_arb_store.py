"""VI 차익거래 데이터 적재 — SQLite (rq-01 FR-07). 나중에 백테스트용.

hub 가 방송하는 모든 메시지를 record() 로 data/vi_arb.db 에 저장한다.
- vi_events   : VI 발동/해제 (정적/동적·방향·발동가)
- spreads     : 스프레드/기회 틱 (KRX예상·NXT매도호가·잔량·net·opportunity) ← 백테스트 코어
- krx_resumes : KRX 랜덤엔드 재개 (경과초)
- orders / order_fills : 모의 주문·체결
각 행에 source(mock|kiwoom) 태그 → 백테스트는 source='kiwoom' 만 필터.

스레드 안전: 단일 커넥션 + Lock (asyncio 루프 + 폴링 혼용 대비).
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)
DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "vi_arb.db"
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vi_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, source TEXT, code TEXT, name TEXT,
  kind TEXT, gubun TEXT, direction TEXT, vi_pct REAL, trigger_price INTEGER);
CREATE TABLE IF NOT EXISTS spreads(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, source TEXT, code TEXT, name TEXT,
  direction TEXT, sec_since_vi REAL, krx_expected INTEGER, nxt_best_ask INTEGER,
  nxt_ask_qty INTEGER, spread INTEGER, cost INTEGER, net_spread INTEGER, net_pct REAL,
  max_profit_pct REAL, first_buy INTEGER, opportunity INTEGER, single_price INTEGER, side TEXT);
CREATE TABLE IF NOT EXISTS krx_resumes(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, source TEXT, code TEXT, name TEXT,
  randomend_sec REAL);
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, source TEXT, code TEXT, name TEXT,
  direction TEXT, ok INTEGER, ord_no TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS order_fills(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, source TEXT, code TEXT, name TEXT,
  status TEXT, ord_no TEXT, side TEXT, ord_qty INTEGER, fill_price INTEGER,
  fill_qty INTEGER, exchange TEXT);
CREATE TABLE IF NOT EXISTS sim_fills(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, source TEXT, code TEXT, name TEXT,
  direction TEXT, entry_buy INTEGER, qty INTEGER, krx_expected INTEGER, krx_confirm INTEGER,
  gross INTEGER, cost INTEGER, net INTEGER, ret_pct REAL, win INTEGER);
CREATE INDEX IF NOT EXISTS idx_sp_code_ts ON spreads(code, ts);
CREATE INDEX IF NOT EXISTS idx_sp_opp ON spreads(opportunity);
CREATE INDEX IF NOT EXISTS idx_vi_code_ts ON vi_events(code, ts);
"""


def _conn_get() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.executescript(_SCHEMA)
        # 마이그레이션: 기존 DB 의 spreads 에 single_price 컬럼 보강
        cols = {r[1] for r in _conn.execute("PRAGMA table_info(spreads)")}
        if "single_price" not in cols:
            _conn.execute("ALTER TABLE spreads ADD COLUMN single_price INTEGER")
        if "side" not in cols:
            _conn.execute("ALTER TABLE spreads ADD COLUMN side TEXT")
        _conn.commit()
    return _conn


def record(msg: dict, source: str = "kiwoom") -> None:
    """방송 메시지 1건을 타입별 테이블에 적재."""
    t = msg.get("type")
    g = msg.get
    try:
        with _lock:
            c = _conn_get()
            if t == "vi":
                c.execute("INSERT INTO vi_events(ts,source,code,name,kind,gubun,direction,vi_pct,trigger_price)"
                          " VALUES(?,?,?,?,?,?,?,?,?)",
                          (g("ts"), source, g("code"), g("name"), g("kind"), g("gubun"),
                           g("direction"), g("vi_pct"), g("trigger_price")))
            elif t == "spread":
                c.execute("INSERT INTO spreads(ts,source,code,name,direction,sec_since_vi,krx_expected,"
                          "nxt_best_ask,nxt_ask_qty,spread,cost,net_spread,net_pct,max_profit_pct,first_buy,opportunity,single_price,side)"
                          " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (g("ts"), source, g("code"), g("name"), g("direction"), g("sec_since_vi"),
                           g("krx_expected"), g("nxt_best_ask"), g("nxt_ask_qty"), g("spread"),
                           g("cost"), g("net_spread"), g("net_pct"), g("max_profit_pct"),
                           g("first_buy"), g("opportunity"), g("single_price"), g("side")))
            elif t == "krx_resume":
                c.execute("INSERT INTO krx_resumes(ts,source,code,name,randomend_sec) VALUES(?,?,?,?,?)",
                          (g("ts"), source, g("code"), g("name"), g("randomend_sec")))
            elif t == "order":
                c.execute("INSERT INTO orders(ts,source,code,name,direction,ok,ord_no,reason)"
                          " VALUES(?,?,?,?,?,?,?,?)",
                          (g("ts"), source, g("code"), g("name"), g("direction"),
                           1 if g("ok") else 0, g("ord_no"), g("reason")))
            elif t == "order_fill":
                c.execute("INSERT INTO order_fills(ts,source,code,name,status,ord_no,side,ord_qty,fill_price,fill_qty,exchange)"
                          " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                          (g("ts"), source, g("code"), g("name"), g("status"), g("ord_no"),
                           g("side"), g("ord_qty"), g("fill_price"), g("fill_qty"), g("exchange")))
            elif t == "sim_fill":
                c.execute("INSERT INTO sim_fills(ts,source,code,name,direction,entry_buy,qty,krx_expected,"
                          "krx_confirm,gross,cost,net,ret_pct,win) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (g("ts"), source, g("code"), g("name"), g("direction"), g("entry_buy"),
                           g("qty"), g("krx_expected"), g("krx_confirm"), g("gross"), g("cost"),
                           g("net"), g("ret_pct"), g("win")))
            else:
                return
            c.commit()
    except Exception as e:
        logger.warning(f"vi_arb_store 적재 실패({t}): {e}")


def today_stats(source: str = "kiwoom") -> dict:
    """당일(KST) 관측 통계 — FE 새로고침 시 카운터 복원용 (WS hello 에 포함)."""
    like = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d") + "%"
    with _lock:
        c = _conn_get()
        def n(q):
            return c.execute(q, (source, like)).fetchone()[0]
        sim = c.execute("SELECT COUNT(*), COALESCE(SUM(win),0), COALESCE(SUM(net),0)"
                        " FROM sim_fills WHERE source=? AND ts LIKE ?", (source, like)).fetchone()
        return {
            "vi": n("SELECT COUNT(*) FROM vi_events WHERE source=? AND ts LIKE ? AND kind='발동'"),
            "ticks": n("SELECT COUNT(*) FROM spreads WHERE source=? AND ts LIKE ?"),
            "opp": n("SELECT COUNT(*) FROM spreads WHERE source=? AND ts LIKE ? AND opportunity=1"),
            "buys": n("SELECT COUNT(*) FROM orders WHERE source=? AND ts LIKE ? AND ok=1 AND direction!='-'"),
            "sim": {"fills": sim[0], "wins": sim[1], "pnl": sim[2]},
        }


def stats() -> dict:
    """적재 현황 요약 (행 수 + 기회 수)."""
    with _lock:
        c = _conn_get()
        def n(q):
            return c.execute(q).fetchone()[0]
        return {
            "vi_events": n("SELECT COUNT(*) FROM vi_events"),
            "spreads": n("SELECT COUNT(*) FROM spreads"),
            "opportunities": n("SELECT COUNT(*) FROM spreads WHERE opportunity=1"),
            "opportunities_single": n("SELECT COUNT(*) FROM spreads WHERE opportunity=1 AND single_price=1"),
            "krx_resumes": n("SELECT COUNT(*) FROM krx_resumes"),
            "orders": n("SELECT COUNT(*) FROM orders"),
            "order_fills": n("SELECT COUNT(*) FROM order_fills"),
            "db": str(DB_PATH),
        }
