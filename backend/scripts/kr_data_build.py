#!/usr/bin/env python3
"""KR 데이터 자체 생성 — dailybars (키움 ka10081).

100m1s 미러(kr_news_sync.py) 의 dailybars/{code}.json 레이어를 키움 REST 로 직접 생성한다.
universe(종목코드)는 frontend/public/kr-news/data/interpreted/*.json 의 stocks[] 에서 추출.

원본 참고: 100m1s-homepage/scripts/kiwoom-scraper/backfill_ohlc.py (ka10081 fetch),
           100m1s-homepage/.github/workflows/kiwoom-scrape.yml (실행/스케줄 패턴).
차이점:
  - 100m1s: SQLite(daily_picks) 백필 + GitHub Actions 가 git 에 커밋(정적 서빙).
  - trakit: dailybars JSON 을 직접 출력하고, kr-news/data 는 gitignore(런타임 재생성)이라
            git 커밋이 아니라 **서버 cron** 으로 라이브 정적 디렉토리에 in-place 생성.
            (프론트 data-loader 가 그대로 소비 → 무수정)

거래대금 검증 완료: get_daily_chart 결과가 100m1s dailybars 와 전 필드 원단위 일치
(2026-06-03 교차검증, 나무기술 242040 8거래일 100% 일치).

사용:
  cd backend && python -m scripts.kr_data_build [--limit N] [--stock CODE] [--days 240] [--dry-run]

env (config.py 가 읽음): KIWOOM_APP_KEY, KIWOOM_APP_SECRET, KIWOOM_MODE, KIWOOM_BASE_URL

서버 cron (KST, kr_news_sync 로 interpreted universe 갱신 후 실행):
  # 미러 동기화 (universe 공급) — 기존
  10 * * * 1-5  cd /path/to/trakit/backend && python3 scripts/kr_news_sync.py
  # dailybars 자체 생성 — 정규장(~15:30) 마감 후 1회
  20 16 * * 1-5 cd /path/to/trakit/backend && python3 -m scripts.kr_data_build
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
REPO_ROOT = BACKEND_DIR.parent
# config/services 를 직접 실행(python scripts/kr_data_build.py)에서도 import 가능하게 path 추가
sys.path.insert(0, str(BACKEND_DIR))

from services import kiwoom_service  # noqa: E402

KST = timezone(timedelta(hours=9))
KR_NEWS_DIR = REPO_ROOT / "frontend" / "public" / "kr-news" / "data"
INTERPRETED_DIR = KR_NEWS_DIR / "interpreted"
DAILYBARS_DIR = KR_NEWS_DIR / "dailybars"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("kr_data_build")


def collect_codes() -> dict[str, str]:
    """interpreted/*.json 의 stocks[] 에서 {code: name} 추출 (6자리 숫자코드만)."""
    out: dict[str, str] = {}
    if not INTERPRETED_DIR.exists():
        logger.warning(f"interpreted 디렉토리 없음: {INTERPRETED_DIR}")
        return out
    for f in sorted(INTERPRETED_DIR.glob("stock-*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for s in d.get("stocks") or []:
            c = s.get("code")
            if c and re.fullmatch(r"\d{6}", str(c)):
                out.setdefault(str(c), s.get("name", ""))  # 첫 등장 이름 유지
    return out


def write_json_if_changed(path: Path, obj) -> bool:
    """변경됐을 때만 쓰기 (불필요한 커밋 방지). 반환: 실제 기록 여부."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if path.exists() and path.read_bytes() == data:
        return False
    path.write_bytes(data)
    return True


def build_one(code: str, name: str, days: int, dry_run: bool) -> tuple[str, int]:
    """단일 종목 dailybars 생성. 반환: (status, actual_days).

    status: 'written' / 'skipped'(무변경 or dry-run) / 'empty' / 'failed'
    """
    rows = kiwoom_service.get_daily_chart(code)
    if rows is None:
        return "failed", 0
    if not rows:
        return "empty", 0
    rows = rows[-days:]  # 최근 N 거래일 (과거→현재 정렬은 get_daily_chart 가 보장)
    obj = {
        "code": code,
        "name": name,
        "window_days": days,
        "actual_days": len(rows),
        "generated_at_date": datetime.now(KST).strftime("%Y-%m-%d"),
        "rows": rows,
    }
    if dry_run:
        return "skipped", len(rows)
    out = DAILYBARS_DIR / f"{code}.json"
    return ("written" if write_json_if_changed(out, obj) else "skipped"), len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, default=0, help="처리 종목 수 제한 (0=전체)")
    ap.add_argument("--stock", type=str, default="", help="특정 종목코드 1개만")
    ap.add_argument("--days", type=int, default=240, help="저장할 거래일 수")
    ap.add_argument("--dry-run", action="store_true", help="조회만, 파일 쓰기 없음")
    ap.add_argument("--sleep", type=float, default=0.5, help="종목 간 sleep(초, rate limit 보호)")
    args = ap.parse_args()

    started = datetime.now(KST)

    # 토큰 사전 확인 (없으면 즉시 종료)
    if not kiwoom_service.get_token():
        logger.error("키움 토큰 발급 실패 — KIWOOM_APP_KEY/KIWOOM_APP_SECRET 확인")
        return 1

    name_map = collect_codes()  # {code: name} — 항상 수집 (이름 조회 겸 universe)
    if args.stock:
        items = [(args.stock, name_map.get(args.stock, ""))]
    else:
        items = list(name_map.items())
    if args.limit > 0:
        items = items[: args.limit]

    logger.info(
        f"🚀 dailybars 생성 시작 — 대상 {len(items)}종목, days={args.days}, dry_run={args.dry_run}"
    )
    if not items:
        logger.warning("대상 종목 없음 (interpreted 데이터 확인)")
        return 1

    stat = {"written": 0, "skipped": 0, "empty": 0, "failed": 0}
    sample_logged = False
    for i, (code, name) in enumerate(items):
        status, n = build_one(code, name, args.days, args.dry_run)
        stat[status] = stat.get(status, 0) + 1
        logger.info(f"[{i + 1}/{len(items)}] {code} {name} → {status} ({n}일)")
        if not sample_logged and n:
            sample_logged = True
        if i < len(items) - 1 and args.sleep > 0:
            time.sleep(args.sleep)

    elapsed = (datetime.now(KST) - started).total_seconds()
    logger.info(
        f"완료 ({elapsed:.1f}s) — written={stat['written']}, skipped={stat['skipped']}, "
        f"empty={stat['empty']}, failed={stat['failed']}"
    )
    # 키움 토큰은 폐기하지 않음 (kiwoom_service 디스크 캐시 재사용 — 재발급/SMS 최소화)
    # written+skipped 가 하나도 없으면(전부 empty/failed) 비정상.
    return 0 if (stat["written"] + stat["skipped"]) > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
