#!/usr/bin/env python3
"""KR 뉴스 정적 자산/데이터 미러링 (100m1s.com → frontend/public/kr-news/).

100m1s 의 news.html 셸과 의존 데이터/종목 페이지를 frontend 정적 디렉토리에
복제. 사용자 요청에 따라 클라이언트에서 100m1s 로 직접 fetch 하지 않고
모두 자체 도메인에서 서빙.

크론 추천 (KST 평일 매시 10분):
  10 * * * 1-5 /usr/bin/python3 /path/to/trakit/backend/scripts/kr_news_sync.py

미러 대상:
  data/
    ├── kiwoom/                (index.json + {date}.json)
    ├── interpreted/           (stock-{date}.json, cafe-{date}.json 등)
    ├── themes/                (themes.json, theme-trend.json, theme-tree.json, theme-map.json)
    ├── calendar/index.json
    ├── dailybars/{code}.json  (interpreted 안의 종목 코드만)
    ├── holidays.json
    └── limit-up-trend.json
  news/stock/{date}/{code}.html  (interpreted 안의 종목 코드만)
"""
from __future__ import annotations
import argparse
import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("kr_news_sync")

KST = timezone(timedelta(hours=9))
REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_ROOT = REPO_ROOT / "frontend" / "public" / "kr-news"
DATA_DIR = OUT_ROOT / "data"
STOCK_DIR = OUT_ROOT / "news" / "stock"

SOURCE = "https://100m1s.com"
HEADERS = {"User-Agent": "trakit-kr-news-sync/2.0"}
TIMEOUT = 20

# 동시 fetch (너무 높이면 100m1s 부담 — github pages 라 관대하지만 매너 차원)
WORKERS = 8


def fetch_bytes(url: str) -> bytes | None:
    try:
        r = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.content
    except Exception as e:
        logger.debug(f"fetch 실패 {url}: {e}")
        return None


def fetch_json(url: str) -> dict | list | None:
    raw = fetch_bytes(url)
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as e:
        logger.warning(f"json 파싱 실패 {url}: {e}")
        return None


def write_bytes(path: Path, data: bytes) -> bool:
    """변경됐을 때만 쓰기."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            if path.read_bytes() == data:
                return False
        except Exception:
            pass
    path.write_bytes(data)
    return True


def mirror_url(url_path: str, out_path: Path) -> str:
    """단일 URL 미러링. 반환: 'synced' / 'skipped' / 'failed'."""
    data = fetch_bytes(f"{SOURCE}{url_path}")
    if data is None:
        return "failed"
    return "synced" if write_bytes(out_path, data) else "skipped"


def collect_stock_codes(interpreted_files: list[Path]) -> set[str]:
    """interpreted/*.json 본문에서 종목 코드 추출 (dailybars/stock 페이지 미러용)."""
    codes: set[str] = set()
    for f in interpreted_files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for s in d.get("stocks", []) or []:
            c = s.get("code")
            if c and re.fullmatch(r"\d{6}", str(c)):
                codes.add(str(c))
    return codes


def sync(limit_dates: int = 60) -> dict:
    stats = {
        "kiwoom_dates": 0, "interpreted_files": 0,
        "stock_pages": 0, "dailybars": 0, "themes": 0, "misc": 0,
        "synced": 0, "skipped": 0, "failed": 0,
    }
    counted_synced = 0
    counted_skipped = 0
    counted_failed = 0

    def bump(r: str):
        nonlocal counted_synced, counted_skipped, counted_failed
        if r == "synced":
            counted_synced += 1
        elif r == "skipped":
            counted_skipped += 1
        else:
            counted_failed += 1

    # 1) kiwoom/index.json — 마스터 인덱스
    idx = fetch_json(f"{SOURCE}/data/kiwoom/index.json")
    if not idx or "dates" not in idx:
        logger.error("kiwoom/index.json 로드 실패")
        return stats
    dates = idx["dates"][:limit_dates]
    stats["kiwoom_dates"] = len(dates)

    # 2) themes/calendar/holidays/limit-up-trend
    misc_jobs = [
        ("/data/themes/themes.json", DATA_DIR / "themes" / "themes.json"),
        ("/data/themes/theme-trend.json", DATA_DIR / "themes" / "theme-trend.json"),
        ("/data/themes/theme-tree.json", DATA_DIR / "themes" / "theme-tree.json"),
        ("/data/themes/theme-map.json", DATA_DIR / "themes" / "theme-map.json"),
        ("/data/calendar/index.json", DATA_DIR / "calendar" / "index.json"),
        ("/data/holidays.json", DATA_DIR / "holidays.json"),
        ("/data/limit-up-trend.json", DATA_DIR / "limit-up-trend.json"),
    ]
    for url_path, out in misc_jobs:
        r = mirror_url(url_path, out)
        bump(r)
        stats["misc"] += 1

    # 3) kiwoom/{date}.json — 일별 거래대금 상위
    write_bytes(DATA_DIR / "kiwoom" / "index.json",
                json.dumps(idx, ensure_ascii=False).encode("utf-8"))

    # 4) interpreted/stock-{date}.json (메인 종목 해석)
    interpreted_paths: list[Path] = []

    def mirror_kiwoom(date):
        return mirror_url(f"/data/kiwoom/{date}.json", DATA_DIR / "kiwoom" / f"{date}.json")

    def mirror_stock(date):
        out = DATA_DIR / "interpreted" / f"stock-{date}.json"
        r = mirror_url(f"/data/interpreted/stock-{date}.json", out)
        if r != "failed":
            interpreted_paths.append(out)
        return r

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for r in ex.map(mirror_kiwoom, dates):
            bump(r)
        for r in ex.map(mirror_stock, dates):
            bump(r)
    stats["interpreted_files"] = len(interpreted_paths)

    # 5) 종목 코드 수집 → dailybars + stock 상세 페이지
    codes = collect_stock_codes(interpreted_paths)
    logger.info(f"📊 종목 코드 {len(codes)}개 수집 → dailybars/stock 페이지 미러링")

    def mirror_dailybar(code):
        return mirror_url(f"/data/dailybars/{code}.json", DATA_DIR / "dailybars" / f"{code}.json")

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for r in ex.map(mirror_dailybar, sorted(codes)):
            bump(r)
            stats["dailybars"] += 1

    # 6) news/stock/{date}/{code}.html — 종목 상세 페이지 (interpreted 에 포함된 (date,code) 페어)
    stock_pairs: list[tuple[str, str]] = []
    for f in interpreted_paths:
        m = re.search(r"stock-(\d{4}-\d{2}-\d{2})\.json$", f.name)
        if not m:
            continue
        date = m.group(1)
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for s in d.get("stocks", []) or []:
            c = s.get("code")
            if c and re.fullmatch(r"\d{6}", str(c)):
                stock_pairs.append((date, str(c)))

    def mirror_stock_page(pair):
        date, code = pair
        return mirror_url(f"/news/stock/{date}/{code}.html",
                          STOCK_DIR / date / f"{code}.html")

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(mirror_stock_page, p): p for p in stock_pairs}
        for fut in as_completed(futures):
            bump(fut.result())
            stats["stock_pages"] += 1

    stats["synced"] = counted_synced
    stats["skipped"] = counted_skipped
    stats["failed"] = counted_failed
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--limit", type=int, default=60, help="최근 N일 (kiwoom 인덱스 기준)")
    args = parser.parse_args()

    started = datetime.now(KST)
    logger.info(f"🚀 KR 뉴스 미러링 시작 (limit={args.limit} days)")
    stats = sync(limit_dates=args.limit)
    elapsed = (datetime.now(KST) - started).total_seconds()
    logger.info(
        f"완료 ({elapsed:.1f}s) — kiwoom={stats['kiwoom_dates']}, "
        f"interpreted={stats['interpreted_files']}, dailybars={stats['dailybars']}, "
        f"stock_pages={stats['stock_pages']}, misc={stats['misc']} | "
        f"synced={stats['synced']}, skipped={stats['skipped']}, failed={stats['failed']}"
    )
    # stock 페이지/dailybars 는 인기 없는 종목/비거래일에서 404 가 자연 발생 (정상).
    # interpreted 가 0 일 때만 비정상으로 본다.
    return 1 if stats["interpreted_files"] == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
