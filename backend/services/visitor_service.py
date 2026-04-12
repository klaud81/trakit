"""방문자 추적 서비스 (파일 기반)"""
import json
import logging
from datetime import date, datetime, timedelta
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
    return {"daily": {}, "total": 0}


def _save_data(data: dict):
    """방문자 데이터 저장"""
    try:
        VISITOR_FILE.parent.mkdir(parents=True, exist_ok=True)
        VISITOR_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.warning(f"방문자 데이터 저장 실패: {e}")


def record_visit():
    """방문 기록 (하루 1회 카운트 — 일별)"""
    data = _load_data()
    today = date.today().isoformat()

    if today not in data["daily"]:
        data["daily"][today] = 0

    data["daily"][today] += 1
    data["total"] += 1

    _save_data(data)


def get_visitor_stats() -> dict:
    """방문자 통계 반환"""
    data = _load_data()
    today = date.today().isoformat()

    # 하루 방문자
    today_count = data["daily"].get(today, 0)

    # 한달 방문자 (최근 30일)
    month_count = 0
    cutoff = (date.today() - timedelta(days=30)).isoformat()
    for day, count in data["daily"].items():
        if day >= cutoff:
            month_count += count

    # 오래된 데이터 정리 (90일 이전)
    cleanup_cutoff = (date.today() - timedelta(days=90)).isoformat()
    data["daily"] = {d: c for d, c in data["daily"].items() if d >= cleanup_cutoff}
    _save_data(data)

    return {
        "today": today_count,
        "month": month_count,
        "total": data["total"],
        "date": today,
    }
