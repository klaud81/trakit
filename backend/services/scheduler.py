"""APScheduler — 장중 회차기록 자동 기록 스케줄러.

SCHEDULE_ENABLED=true 일 때만 동작 (실전 .env.real). 백엔드 startup 에서 start(),
shutdown 에서 stop() 호출 (app.py lifespan).

US 사전장+정규장(KST 0~6, 17~23) 평일~토, 5분 간격으로
sheets_writer.update_cycle_record(dry_run=False) 실행. 작업은 idempotent(중복 제거)라
다중 발화해도 안전.

비고: BackgroundScheduler(별도 스레드)라 동기 blocking I/O(gspread/requests) 안전.
멀티워커(gunicorn -w N) 환경에선 워커마다 스케줄러가 떠 다중 발화 가능하나, 작업이
idempotent 라 첫 발화 외엔 no-op.
"""
from __future__ import annotations
import logging

from config import SCHEDULE_ENABLED

logger = logging.getLogger(__name__)
_scheduler = None


def _job():
    try:
        from services.sheets_writer import update_cycle_record
        res = update_cycle_record(dry_run=False)
        if res.get("updated"):
            logger.info(f"⏰ 회차기록 자동 갱신: 주차 {res.get('week')} {res.get('added')}")
    except Exception as e:
        logger.warning(f"스케줄 회차기록 실패: {e}")


def start() -> None:
    """SCHEDULE_ENABLED 면 스케줄러 시작."""
    global _scheduler
    if not SCHEDULE_ENABLED:
        logger.info("⏰ 회차기록 스케줄 비활성 (SCHEDULE_ENABLED=false)")
        return
    if _scheduler is not None:
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        logger.warning("apscheduler 미설치 — 스케줄 건너뜀 (pip install apscheduler)")
        return
    _scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    _scheduler.add_job(
        _job, "cron", day_of_week="mon-sat", hour="0-6,17-23", minute="*/5",
        id="cycle_record", max_instances=1, coalesce=True,
    )
    _scheduler.start()
    logger.info("⏰ 회차기록 스케줄 활성화 (KST 0~6·17~23, 평일~토, 5분 간격)")


def stop() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None
