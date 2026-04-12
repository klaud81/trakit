"""방문자 추적 서비스 (파일 기반)

데이터 구조:
- daily: {"2026/04/13": 5, ...} — 당월 일별 기록
- monthly: {"2026/03": 150, ...} — 이전 월별 집계
- total: 1234 — 누적 합계

월이 바뀌면 이전 달 일별 데이터를 월별로 집계하여 이동.
"""
import json
import logging
from datetime import date
from pathlib import Path
from config import DATA_DIR

logger = logging.getLogger(__name__)

VISITOR_FILE = DATA_DIR / "visitors.json"


def _load_data() -> dict:
    """방문자 데이터 로드"""
    if VISITOR_FILE.exists():
        try:
            return json.loads(VISITOR_FILE.read_text())
        except Exception:
            pass
    return {"daily": {}, "monthly": {}, "total": 0}


def _save_data(data: dict):
    """방문자 데이터 저장"""
    try:
        VISITOR_FILE.parent.mkdir(parents=True, exist_ok=True)
        VISITOR_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception as e:
        logger.warning(f"방문자 데이터 저장 실패: {e}")


def _compact(data: dict) -> dict:
    """이전 월 일별 데이터를 월별로 집계"""
    current_month = date.today().strftime("%Y/%m")
    to_remove = []

    for day, count in data["daily"].items():
        # day: "2026/04/13" → month: "2026/04"
        month = day[:7]
        if month < current_month:
            data["monthly"][month] = data["monthly"].get(month, 0) + count
            to_remove.append(day)

    for day in to_remove:
        del data["daily"][day]

    return data


def record_visit():
    """방문 기록"""
    data = _load_data()
    data = _compact(data)

    today = date.today().strftime("%Y/%m/%d")
    data["daily"][today] = data["daily"].get(today, 0) + 1
    data["total"] += 1

    _save_data(data)


def get_visitor_stats() -> dict:
    """방문자 통계 반환"""
    data = _load_data()
    data = _compact(data)

    today_key = date.today().strftime("%Y/%m/%d")
    current_month = date.today().strftime("%Y/%m")

    # 오늘
    today_count = data["daily"].get(today_key, 0)

    # 당월 (일별 합계)
    month_count = sum(c for d, c in data["daily"].items() if d.startswith(current_month))

    return {
        "today": today_count,
        "month": month_count,
        "total": data["total"],
        "date": today_key,
    }
