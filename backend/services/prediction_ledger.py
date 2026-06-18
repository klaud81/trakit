"""TQQQ 일간 예측 ledger — 라이브 예측 발행·채점·누적성적 (rq-02 §8.2).

predict_backtest 의 결정론 코어(predict_core/features_asof)를 그대로 재사용하되,
백테스트(과거 일괄)와 달리 '매 거래일 1건 발행 → 다음날 실측 채점' 흐름을 SQLite 에
영속화한다. vi_arb_store.py 의 단일커넥션+Lock 패턴을 따른다.

테이블:
- predictions : 발행 시점 예측 (regime/direction/band/근거/입력피처 스냅샷)
- outcomes    : 다음날 실측 채점 (방향·흐름·밴드 적중, 폭오차, 변곡포착)

흐름:
  발행  predict_and_record(date)  — 당일 피처+뉴스 → predict_core → predictions INSERT
  채점  score_due()               — outcome 없는 과거 예측의 실측 종가 조회 → outcomes INSERT
  주입  recent_scorecard(n)       — 최근 n건 누적성적 dict (LLM 피드백-인-컨텍스트용)

채점 기준은 predict_backtest.backtest 와 동일 정의를 사용한다(중복 정의 회피 차원에서
방향=종가부호, 흐름=전방 rhorizon 추세부호, 밴드=종가∈[low,high], 변곡=기술추세 반대).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)
KST = timezone.utc  # ISO 타임스탬프는 UTC 저장, 표기는 호출측
DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "prediction.db"
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT UNIQUE,            -- 예측 대상 거래일 (YYYY-MM-DD)
  regime TEXT, direction TEXT,
  low_pct REAL, high_pct REAL,
  band_low REAL, band_high REAL,
  ref_close REAL,             -- 기준(전일) 종가
  confidence TEXT,
  inflection TEXT,            -- 변곡 예측 라벨 (없으면 NULL)
  tech_up INTEGER,            -- 기술추세 상방 여부 (변곡 채점용)
  nasdaq_bias REAL,
  reasons_json TEXT, inputs_json TEXT,
  model TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS outcomes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  prediction_id INTEGER UNIQUE,
  actual_close REAL, actual_pct REAL,
  direction_hit INTEGER, regime_hit INTEGER,
  band_hit INTEGER, band_err REAL,     -- band_err = (실제-밴드중앙)/전일 *100 (%p, 부호)
  reversal_caught INTEGER,             -- 변곡 예측이 실제 반전과 일치 (1), 예측없음/불일치(0), 비반전일(NULL)
  scored_at TEXT,
  FOREIGN KEY(prediction_id) REFERENCES predictions(id));
CREATE INDEX IF NOT EXISTS idx_pred_date ON predictions(date);
"""


def _conn_get() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(_SCHEMA)
        _conn.commit()
    return _conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── 발행 ────────────────────────────────────────────────────────────────────
def record_prediction(date: str, pred: dict, ref_close: float, *,
                      nasdaq_bias: float = 0.0, inputs: dict | None = None,
                      model: str = "deterministic") -> int:
    """predict_core 산출(pred) 을 predictions 에 1행 기록. date 중복이면 갱신(재발행).

    반환: prediction id.
    """
    with _lock:
        c = _conn_get()
        c.execute("DELETE FROM predictions WHERE date=?", (date,))
        cur = c.execute(
            """INSERT INTO predictions(date, regime, direction, low_pct, high_pct,
                 band_low, band_high, ref_close, confidence, inflection, tech_up,
                 nasdaq_bias, reasons_json, inputs_json, model, created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (date, pred.get("regime"), pred.get("direction"),
             pred.get("low_pct"), pred.get("high_pct"),
             pred.get("band_low"), pred.get("band_high"), ref_close,
             pred.get("confidence", ""), pred.get("inflection"),
             1 if pred.get("tech_up") else 0, float(nasdaq_bias),
             json.dumps(pred.get("reasons", []), ensure_ascii=False),
             json.dumps(inputs or {}, ensure_ascii=False),
             model, _now()))
        c.commit()
        return int(cur.lastrowid)


def predict_and_record(date: str | None = None, *, use_news: bool = True,
                       lookback: int = 20, width: float | None = None) -> dict | None:
    """당일(또는 지정일) 예측을 발행하고 ledger 에 기록. 반환: 기록된 예측 dict (+ id).

    use_news 시 D-1 뉴스 캐시 bias 를 적용. width 미지정이면 최근창 캘리브.
    """
    import scripts.predict_backtest as pb
    from services.price_service import get_overseas_daily

    hist = get_overseas_daily("TQQQ", days=max(160, lookback + 90))
    if len(hist) < lookback + 5:
        logger.warning("예측 불가: 일봉 데이터 부족 (%d행)", len(hist))
        return None
    # features_asof 는 hist[:i] 만 과거로 사용(hist[i] 미접근) → i=len(hist) 로 호출하면
    # 마지막 확정 거래일까지 전부를 과거로 보고 '다음 거래일'용 피처를 구성한다.
    f = pb.features_asof(hist, len(hist), lookback)
    if f is None:
        logger.warning("예측 불가: 피처 구성 실패")
        return None

    prev = hist[-1]
    # date 미지정 시 '마지막 확정 종가의 다음 영업일'로 도출(주말 건너뜀). 평일 사전장
    # (ET 04:00, 직전 종가=전일) 발화에선 곧 그날 거래일과 일치. 휴일은 미구분(드물게
    # 비거래일 행이 남으나 score_due 가 실측 없으면 건너뛰므로 무해). score_due 의
    # 날짜 GLOB 에 걸리려면 실제 날짜여야 채점된다.
    if date is None:
        d = datetime.strptime(prev["date"], "%Y-%m-%d") + timedelta(days=1)
        while d.weekday() >= 5:  # 토(5)/일(6) 건너뜀
            d += timedelta(days=1)
        target_date = d.strftime("%Y-%m-%d")
    else:
        target_date = date
    news = None
    bias = 0.0
    if use_news:
        # D-1 뉴스를 saveticker 에서 수집·분석(없으면) — analyze_day 가 캐시 미스 시
        # collect_by_date 로 라이브 수집 후 LLM 분석·캐시한다. 캐시 있으면 즉시 반환.
        try:
            from services.nasdaq_news import day_bias
            news = day_bias(prev["date"], use_cache=True)
            bias = news.get("nasdaq_bias", 0.0)
        except Exception as e:  # 뉴스 실패 시 가격전용으로 강등(예측은 계속)
            logger.warning("뉴스 분석 실패(%s) — 가격전용 예측: %s", prev["date"], e)
            news = None

    cal_days = min(40, len(hist) - lookback - 5)
    if width is None:
        width, drift = pb.calibrate_joint(hist, cal_days, lookback, None)
    else:
        drift = pb.calibrate_drift(hist, cal_days, lookback, width, None)
    pred = pb.predict_core(f, width, news=news, drift=drift)
    inputs = {"mom": f["mom"], "ma5": f["ma5"], "ma20": f["ma20"], "ma50": f["ma50"],
              "rsi": f["rsi"], "vol": f["vol"], "above20": f["above20"],
              "width": width, "drift": drift}
    pid = record_prediction(target_date, pred, prev["close"], nasdaq_bias=bias,
                            inputs=inputs, model="sonnet" if news else "price_only")
    out = {**pred, "id": pid, "date": target_date, "ref_close": prev["close"],
           "ref_date": prev["date"], "nasdaq_bias": bias}
    logger.info("🔮 예측 발행 #%d (%s 기준 → %s): %s/%s 밴드 %.2f~%.2f",
                pid, prev["date"], target_date, pred["regime"], pred["direction"],
                pred["band_low"], pred["band_high"])
    return out


# ── 채점 ────────────────────────────────────────────────────────────────────
def pending() -> list[sqlite3.Row]:
    """outcome 이 없고 date 가 실측 가능한(플레이스홀더 아닌) 예측 목록."""
    c = _conn_get()
    return c.execute(
        """SELECT p.* FROM predictions p
           LEFT JOIN outcomes o ON o.prediction_id = p.id
           WHERE o.id IS NULL AND p.date GLOB '20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
           ORDER BY p.date""").fetchall()


def score_one(pred: sqlite3.Row, actual_close: float, trend_pct: float | None = None,
              flat: float = 1.0) -> dict:
    """예측 1건을 실측 종가로 채점해 outcomes 에 기록. trend_pct=전방추세(흐름채점용)."""
    prev = pred["ref_close"]
    act_pct = (actual_close - prev) / prev * 100
    act_dir = "상승" if actual_close >= prev else "하락"
    dir_hit = int(pred["direction"] == act_dir)
    band_hit = int(pred["band_low"] <= actual_close <= pred["band_high"])
    band_mid = (pred["band_low"] + pred["band_high"]) / 2
    band_err = (actual_close - band_mid) / prev * 100
    # 흐름: trend_pct 주어지면 부호 비교, 없으면 당일 act_pct 로 근사
    tp = trend_pct if trend_pct is not None else act_pct
    regime_hit = int((pred["regime"] == "상승흐름" and tp > 0)
                     or (pred["regime"] == "하락흐름" and tp < 0)
                     or (pred["regime"] == "중립" and abs(tp) <= flat))
    # 변곡: 실제가 기술추세 반대로 갔는가(actual_reversal) & 예측이 그걸 맞췄는가
    tech_up = bool(pred["tech_up"])
    actual_reversal = (tech_up and act_dir == "하락") or (not tech_up and act_dir == "상승")
    if not actual_reversal:
        reversal_caught = None       # 비반전일은 변곡 채점 대상 아님
    else:
        reversal_caught = int(pred["inflection"] is not None)
    with _lock:
        c = _conn_get()
        c.execute("DELETE FROM outcomes WHERE prediction_id=?", (pred["id"],))
        c.execute(
            """INSERT INTO outcomes(prediction_id, actual_close, actual_pct,
                 direction_hit, regime_hit, band_hit, band_err, reversal_caught, scored_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (pred["id"], actual_close, round(act_pct, 3), dir_hit, regime_hit,
             band_hit, round(band_err, 3),
             reversal_caught, _now()))
        c.commit()
    return {"prediction_id": pred["id"], "date": pred["date"], "actual_pct": round(act_pct, 2),
            "direction_hit": bool(dir_hit), "regime_hit": bool(regime_hit),
            "band_hit": bool(band_hit), "reversal_caught": reversal_caught}


def score_due(rhorizon: int = 3) -> list[dict]:
    """미채점 예측들을 KIS 일봉 실측으로 채점. 실측 가능한(과거가 된) 날짜만 처리."""
    from services.price_service import get_overseas_daily
    rows = pending()
    if not rows:
        return []
    hist = get_overseas_daily("TQQQ", days=200)
    by_date = {h["date"]: idx for idx, h in enumerate(hist)}
    closes = [h["close"] for h in hist]
    scored = []
    for p in rows:
        idx = by_date.get(p["date"])
        if idx is None:
            continue  # 아직 실측 없음 (미래/휴장)
        fwd = min(idx + rhorizon - 1, len(closes) - 1)
        trend_pct = (closes[fwd] - p["ref_close"]) / p["ref_close"] * 100
        scored.append(score_one(p, closes[idx], trend_pct=trend_pct))
    if scored:
        logger.info("✅ 예측 채점 %d건", len(scored))
    return scored


# ── 누적성적 (LLM 피드백-인-컨텍스트) ─────────────────────────────────────────
def recent_scorecard(n: int = 20) -> dict:
    """최근 n 건의 채점된 성적 집계. 예측 프롬프트 주입/Discord 노출용."""
    c = _conn_get()
    rows = c.execute(
        """SELECT o.* FROM outcomes o JOIN predictions p ON p.id=o.prediction_id
           ORDER BY p.date DESC LIMIT ?""", (n,)).fetchall()
    if not rows:
        return {"n": 0}
    n_ = len(rows)
    dh = sum(r["direction_hit"] for r in rows) / n_
    rh = sum(r["regime_hit"] for r in rows) / n_
    bh = sum(r["band_hit"] for r in rows) / n_
    be = sum(r["band_err"] for r in rows) / n_
    rev = [r for r in rows if r["reversal_caught"] is not None]
    rev_recall = (sum(r["reversal_caught"] for r in rev) / len(rev)) if rev else None
    return {"n": n_, "direction_hit": round(dh, 3), "regime_hit": round(rh, 3),
            "band_cover": round(bh, 3), "band_bias": round(be, 2),
            "n_reversal": len(rev), "reversal_recall": rev_recall}


def _row_to_pred(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "date": r["date"], "regime": r["regime"],
            "direction": r["direction"], "band_low": r["band_low"], "band_high": r["band_high"],
            "low_pct": r["low_pct"], "high_pct": r["high_pct"], "ref_close": r["ref_close"],
            "ref_date": None, "confidence": r["confidence"], "inflection": r["inflection"],
            "nasdaq_bias": r["nasdaq_bias"], "reasons": json.loads(r["reasons_json"] or "[]"),
            "model": r["model"], "created_at": r["created_at"]}


def latest_prediction() -> dict | None:
    """가장 최근 발행 예측 1건 (FE/API 노출용)."""
    c = _conn_get()
    r = c.execute("SELECT * FROM predictions ORDER BY id DESC LIMIT 1").fetchone()
    return _row_to_pred(r) if r else None


def history(n: int = 60) -> list[dict]:
    """채점된 예측 이력(최신순 n건) — 성적 추이 차트용. 오래된→최신 정렬 반환."""
    c = _conn_get()
    rows = c.execute(
        """SELECT p.date, p.direction, p.regime, p.band_low, p.band_high, p.ref_close,
                  o.actual_close, o.actual_pct, o.direction_hit, o.regime_hit,
                  o.band_hit, o.band_err, o.reversal_caught
           FROM predictions p JOIN outcomes o ON o.prediction_id=p.id
           ORDER BY p.date DESC LIMIT ?""", (n,)).fetchall()
    return [dict(r) for r in reversed(rows)]


def scorecard_prompt(n: int = 20) -> str:
    """recent_scorecard 를 LLM 프롬프트에 주입할 한국어 한 줄 문자열로."""
    s = recent_scorecard(n)
    if not s.get("n"):
        return "(누적 성적 없음 — 첫 예측)"
    rr = f"{s['reversal_recall']*100:.0f}%" if s["reversal_recall"] is not None else "—"
    return (f"최근 {s['n']}일 성적: 방향 {s['direction_hit']*100:.0f}% · "
            f"흐름 {s['regime_hit']*100:.0f}% · 밴드커버 {s['band_cover']*100:.0f}% · "
            f"폭편향 {s['band_bias']:+.2f}%p · 변곡recall {rr}")
