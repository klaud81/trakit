#!/usr/bin/env python3
"""헤드라인 LLM 요약기 (Claude CLI subprocess 사용, API 키 불필요).

Step 1 수집기가 모은 SQLite의 headlines 테이블에서 아직 요약 안 된 항목을 골라,
`claude -p --output-format json --json-schema ...` 로 점수 + 한국어 요약을 생성한다.
구독 OAuth 인증을 그대로 사용하므로 별도 ANTHROPIC_API_KEY 가 필요 없다.

Usage:
    python -m scripts.briefing_summarize                    # 미요약 헤드라인 전체 처리
    python -m scripts.briefing_summarize --limit 10         # 최대 10개만
    python -m scripts.briefing_summarize --stats            # 요약 통계
    python -m scripts.briefing_summarize --recent 10 --min-score 7
    python -m scripts.briefing_summarize --model haiku      # 빠르고 저렴 (기본=sonnet)
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "briefing.db"
CLAUDE_CMD = "claude"
DEFAULT_MODEL = "sonnet"
PER_CALL_TIMEOUT = 180  # 초
SLEEP_BETWEEN = 0.5     # 호출 사이 대기 (rate-limit 방지)

JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "minimum": 0, "maximum": 10},
        "category": {"type": "string", "enum": ["A", "B", "C", "D", "none"]},
        "tickers": {"type": "array", "items": {"type": "string"}},
        "direction": {
            "type": "string",
            "enum": ["positive", "negative", "neutral", "mixed"],
        },
        "summary_kr": {"type": "string"},
    },
    "required": ["score", "category", "direction", "summary_kr"],
}

# 노이즈 제목 (요약 가치 낮음)
NOISE_PATTERNS = [
    "How major US stock indexes fared",
    "Asia Markets:",
    "Wall Street Week Ahead",
    "Daily Newsletter",
]


def init_summaries_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS summaries (
            headline_id INTEGER PRIMARY KEY,
            score INTEGER NOT NULL,
            category TEXT NOT NULL,
            tickers TEXT NOT NULL,
            direction TEXT NOT NULL,
            summary_kr TEXT NOT NULL,
            model TEXT NOT NULL,
            duration_ms INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY (headline_id) REFERENCES headlines(id)
        );
        CREATE INDEX IF NOT EXISTS idx_summary_score ON summaries(score DESC);
        CREATE INDEX IF NOT EXISTS idx_summary_created ON summaries(created_at DESC);
        """
    )


def is_noisy(title: str) -> bool:
    return any(p in title for p in NOISE_PATTERNS)


def build_prompt(title: str, source: str) -> str:
    return f"""다음 영문 뉴스 제목을 나스닥 투자자 관점에서 분석해서 JSON으로만 응답.

분류 기준:
- A: 특정 미국 상장 종목 직접 호재/악재
- B: 섹터(반도체/AI/EV/바이오 등) 영향
- C: 매크로(연준/CPI/유가 등) 지수 영향
- D: 지정학(중동/대만/중국 등) 간접 영향
- none: 무관

score 가이드:
- 9-10: 메가캡(NVDA/AAPL/MSFT/GOOGL/AMZN/META/TSLA) 직접 발표
- 7-8: 나스닥 상장 종목 또는 명확한 섹터 영향
- 4-6: 매크로 또는 지정학
- 1-3: 간접/배경
- 0: 무관

summary_kr: 한 문장 한국어 요약 (50자 이내, 사실만, 추측 금지).
tickers: 제목에 명시된 미국 티커만 ($NVDA 형식). 없으면 빈 배열.

제목 ({source}): {title}
"""


def _extract_json(text: str) -> dict | None:
    """plain text에서 JSON object를 추출 (code fence 처리)."""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip()
        if s.endswith("```"):
            s = s.rsplit("```", 1)[0].strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return None


def call_claude(prompt: str, model: str, debug: bool = False) -> tuple[dict | None, int]:
    """claude -p 를 subprocess 로 호출. (parsed_json | None, duration_ms)."""
    t0 = time.time()
    try:
        proc = subprocess.run(
            [
                CLAUDE_CMD,
                "-p",
                "--output-format", "json",
                "--json-schema", json.dumps(JSON_SCHEMA),
                "--model", model,
                "--no-session-persistence",
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=PER_CALL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None, int((time.time() - t0) * 1000)

    duration_ms = int((time.time() - t0) * 1000)
    if proc.returncode != 0:
        if debug:
            print(f"      stderr: {proc.stderr[:200]}")
        return None, duration_ms

    try:
        meta = json.loads(proc.stdout)
    except json.JSONDecodeError:
        if debug:
            print(f"      bad meta json: {proc.stdout[:200]}")
        return None, duration_ms

    if meta.get("is_error"):
        if debug:
            print(f"      api_error: {meta.get('api_error_status')}")
        return None, duration_ms

    # 1순위: --json-schema 가 검증한 structured_output
    if "structured_output" in meta and isinstance(meta["structured_output"], dict):
        return meta["structured_output"], duration_ms
    # 2순위: result 필드에서 JSON 추출
    parsed = _extract_json(meta.get("result", ""))
    if parsed:
        return parsed, duration_ms
    if debug:
        print(f"      no parseable output: {meta.get('result', '')[:150]}")
    return None, duration_ms


def process_headlines(conn: sqlite3.Connection, limit: int, model: str, debug: bool = False) -> dict:
    rows = conn.execute(
        """
        SELECT h.id, h.title, h.source
        FROM headlines h
        LEFT JOIN summaries s ON s.headline_id = h.id
        WHERE s.headline_id IS NULL
        ORDER BY h.collected_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    stats = {"processed": 0, "saved": 0, "skipped_noise": 0, "failed": 0}
    print(f"대상: {len(rows)}개  (model={model})")

    for hid, title, source in rows:
        stats["processed"] += 1

        if is_noisy(title):
            stats["skipped_noise"] += 1
            print(f"  [skip-noise] {title[:80]}")
            continue

        prompt = build_prompt(title, source)
        result, duration_ms = call_claude(prompt, model, debug=debug)

        if not result:
            stats["failed"] += 1
            print(f"  [fail {duration_ms:>5d}ms] {title[:80]}")
            time.sleep(SLEEP_BETWEEN)
            continue

        conn.execute(
            """
            INSERT INTO summaries
                (headline_id, score, category, tickers, direction,
                 summary_kr, model, duration_ms, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                hid,
                result["score"],
                result["category"],
                json.dumps(result.get("tickers", []), ensure_ascii=False),
                result["direction"],
                result["summary_kr"],
                model,
                duration_ms,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        stats["saved"] += 1
        score = result["score"]
        cat = result["category"]
        dirn = result["direction"][:3]
        print(f"  [{score:>2} {cat} {dirn} {duration_ms:>5d}ms] {title[:60]}")
        print(f"          → {result['summary_kr']}")
        time.sleep(SLEEP_BETWEEN)
    return stats


def show_stats(conn: sqlite3.Connection) -> None:
    h_total = conn.execute("SELECT COUNT(*) FROM headlines").fetchone()[0]
    s_total = conn.execute("SELECT COUNT(*) FROM summaries").fetchone()[0]
    pending = h_total - s_total
    avg_dur = conn.execute(
        "SELECT AVG(duration_ms) FROM summaries"
    ).fetchone()[0]
    print(f"\n헤드라인 {h_total}, 요약됨 {s_total}, 미처리 {pending}")
    if avg_dur:
        print(f"평균 호출 시간: {avg_dur/1000:.1f}s")

    print("\n점수별 분포:")
    for score, n in conn.execute(
        "SELECT score, COUNT(*) FROM summaries GROUP BY score ORDER BY score DESC"
    ):
        bar = "█" * min(n, 30)
        print(f"  {score:>2d} | {bar} {n}")

    print("\n카테고리별:")
    for cat, n in conn.execute(
        "SELECT category, COUNT(*) FROM summaries GROUP BY category ORDER BY 2 DESC"
    ):
        labels = {"A": "종목 직접", "B": "섹터", "C": "매크로", "D": "지정학", "none": "무관"}
        print(f"  {cat} ({labels.get(cat, '?')}): {n}")


def show_recent(conn: sqlite3.Connection, n: int, min_score: int) -> None:
    rows = conn.execute(
        """
        SELECT h.title, h.source, s.score, s.category, s.direction,
               s.tickers, s.summary_kr
        FROM summaries s
        JOIN headlines h ON h.id = s.headline_id
        WHERE s.score >= ?
        ORDER BY s.score DESC, s.created_at DESC
        LIMIT ?
        """,
        (min_score, n),
    ).fetchall()
    print(f"\n점수 >= {min_score}, 최근 {len(rows)}개:")
    for title, src, score, cat, dirn, tickers_json, summary in rows:
        tickers = ", ".join(json.loads(tickers_json) or [])
        suffix = f"  {tickers}" if tickers else ""
        print(f"\n  [{score:>2} {cat} {dirn[:3]:<3s}] [{src}] {title[:80]}{suffix}")
        print(f"        → {summary}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--limit", type=int, default=20, help="이번에 처리할 최대 헤드라인 수")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="claude --model 값 (sonnet|haiku|opus|...)")
    parser.add_argument("--stats", action="store_true", help="통계만")
    parser.add_argument("--recent", type=int, default=0, help="최근 N개 요약 표시")
    parser.add_argument("--min-score", type=int, default=0, help="--recent 와 함께 점수 임계값")
    parser.add_argument("--debug", action="store_true", help="실패 시 stderr/응답 출력")
    args = parser.parse_args()

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_summaries_table(conn)

    if args.stats:
        show_stats(conn)
        return
    if args.recent > 0:
        show_recent(conn, args.recent, args.min_score)
        return

    print(f"요약 시작 (limit={args.limit}, model={args.model})")
    t0 = time.time()
    stats = process_headlines(conn, args.limit, args.model, debug=args.debug)
    elapsed = time.time() - t0
    print(
        f"\n완료 ({elapsed:.1f}s)  "
        f"saved={stats['saved']}  noise={stats['skipped_noise']}  failed={stats['failed']}"
    )
    show_stats(conn)


if __name__ == "__main__":
    main()
