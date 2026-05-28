#!/usr/bin/env python3
"""나스닥 관련 헤드라인 수집기 (Step 1).

Google News RSS 를 통해 Reuters / AP / Axios 등 주요 매체의
나스닥 관련 헤드라인을 모은다. SQLite 에 (source, title) 해시로 중복 방지.

Usage:
    python -m scripts.briefing_collector              # 1회 수집
    python -m scripts.briefing_collector --stats      # DB 통계
    python -m scripts.briefing_collector --recent 20  # 최근 20개
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "briefing.db"
USER_AGENT = "Mozilla/5.0 (compatible; trakit-briefing/1.0)"
TIMEOUT = 15

# 나스닥 관련 검색 쿼리 (site: 필터로 매체 제한)
QUERIES = [
    'site:reuters.com (Nvidia OR Apple OR Microsoft OR Google OR Amazon OR Meta OR Tesla)',
    'site:reuters.com (semiconductor OR "AI chip" OR "data center")',
    'site:reuters.com ("rate cut" OR Fed OR FOMC OR CPI OR inflation)',
    'site:reuters.com (Hormuz OR Taiwan OR "China export" OR sanctions)',
    'site:reuters.com Nasdaq',
    'site:apnews.com (Nvidia OR Apple OR Microsoft OR Google OR Tesla)',
    'site:apnews.com (semiconductor OR Fed OR earnings)',
    'site:apnews.com Nasdaq',
    'site:axios.com (Nvidia OR Apple OR Microsoft OR semiconductor OR AI)',
]

# 허용 매체: 제목 끝의 " - <매체>" 패턴으로 매칭
ALLOWED_SOURCES = {
    "Reuters": "Reuters",
    "AP News": "AP",
    "The Associated Press": "AP",
    "Axios": "Axios",
    "Bloomberg": "Bloomberg",
    "CNBC": "CNBC",
    "Yahoo Finance": "Yahoo Finance",
    "Fox News": "FOX",
    "Nikkei Asia": "Nikkei",
    "The Wall Street Journal": "WSJ",
    "Financial Times": "FT",
}

TITLE_SUFFIX_RE = re.compile(r"\s+-\s+([^-]+?)\s*$")


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS headlines (
            id INTEGER PRIMARY KEY,
            content_hash TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            source TEXT NOT NULL,
            google_url TEXT NOT NULL,
            published_at TEXT,
            collected_at TEXT NOT NULL,
            query TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_published ON headlines(published_at DESC);
        CREATE INDEX IF NOT EXISTS idx_collected ON headlines(collected_at DESC);
        CREATE INDEX IF NOT EXISTS idx_source ON headlines(source);
        """
    )


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip().lower()


def content_hash(source: str, title: str) -> str:
    return hashlib.sha256(f"{source}|{normalize_title(title)}".encode()).hexdigest()


def parse_source_from_title(title: str) -> tuple[str, str | None]:
    """제목에서 ' - <매체>' 접미사를 떼어내고 정규화된 매체 라벨을 반환."""
    m = TITLE_SUFFIX_RE.search(title)
    if not m:
        return title, None
    raw_source = m.group(1).strip()
    label = ALLOWED_SOURCES.get(raw_source)
    if label is None:
        return title, None
    clean_title = title[: m.start()].rstrip()
    return clean_title, label


def fetch_query(query: str) -> list[dict]:
    rss_url = (
        f"https://news.google.com/rss/search?q={quote(query)}"
        f"&hl=en-US&gl=US&ceid=US:en"
    )
    r = requests.get(
        rss_url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}
    )
    r.raise_for_status()
    root = ET.fromstring(r.content)
    items: list[dict] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        if title and link:
            items.append({"title": title, "google_url": link, "pub_date": pub})
    return items


def insert_if_new(
    conn: sqlite3.Connection, item: dict, query: str
) -> bool:
    h = content_hash(item["source"], item["title"])
    try:
        conn.execute(
            """
            INSERT INTO headlines
                (content_hash, title, source, google_url, published_at, collected_at, query)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                h,
                item["title"],
                item["source"],
                item["google_url"],
                item.get("pub_date"),
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                query,
            ),
        )
        return True
    except sqlite3.IntegrityError:
        return False


def collect_all(conn: sqlite3.Connection) -> dict:
    stats = {"inserted": 0, "duplicate": 0, "no_source": 0, "queries_failed": 0}
    for q in QUERIES:
        try:
            items = fetch_query(q)
        except Exception as e:
            print(f"  [warn] query failed: {q[:60]}... -> {e}")
            stats["queries_failed"] += 1
            continue
        local_new = 0
        for it in items:
            clean_title, source = parse_source_from_title(it["title"])
            if source is None:
                stats["no_source"] += 1
                continue
            it["title"] = clean_title
            it["source"] = source
            if insert_if_new(conn, it, q):
                stats["inserted"] += 1
                local_new += 1
            else:
                stats["duplicate"] += 1
        conn.commit()
        print(f"  [{len(items):3d}] {q[:65]}{'...' if len(q) > 65 else ''}  +{local_new}")
    return stats


def show_stats(conn: sqlite3.Connection) -> None:
    total = conn.execute("SELECT COUNT(*) FROM headlines").fetchone()[0]
    by_source = conn.execute(
        "SELECT source, COUNT(*) FROM headlines GROUP BY source ORDER BY 2 DESC"
    ).fetchall()
    today_count = conn.execute(
        "SELECT COUNT(*) FROM headlines WHERE date(collected_at) = date('now')"
    ).fetchone()[0]
    print(f"\n총 헤드라인: {total}")
    print(f"오늘 수집: {today_count}")
    print("\n매체별:")
    for src, n in by_source:
        print(f"  {src:<15s} {n:>5d}")


def show_recent(conn: sqlite3.Connection, n: int) -> None:
    rows = conn.execute(
        """
        SELECT title, source, published_at
        FROM headlines
        ORDER BY collected_at DESC LIMIT ?
        """,
        (n,),
    ).fetchall()
    print(f"\n최근 {len(rows)}개:")
    for title, src, pub in rows:
        date = (pub or "")[:16]
        print(f"  [{src:<6s}] {date}  {title[:90]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--stats", action="store_true", help="DB 통계만 출력")
    parser.add_argument("--recent", type=int, default=0, help="최근 N개 표시")
    args = parser.parse_args()

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    if args.stats:
        show_stats(conn)
        return
    if args.recent > 0:
        show_recent(conn, args.recent)
        return

    print(f"수집 시작 ({len(QUERIES)} queries) -> {DB_PATH}")
    t0 = time.time()
    stats = collect_all(conn)
    elapsed = time.time() - t0
    print(
        f"\n완료 ({elapsed:.1f}s)  "
        f"new={stats['inserted']}  dup={stats['duplicate']}  "
        f"no_source={stats['no_source']}  failed={stats['queries_failed']}"
    )
    show_stats(conn)


if __name__ == "__main__":
    main()
