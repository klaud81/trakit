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
from datetime import datetime, timezone, timedelta

from config import SCHEDULE_ENABLED, PREMARKET_BRIEF_ENABLED

KST = timezone(timedelta(hours=9))
_WEEKDAY_KR = ("월", "화", "수", "목", "금", "토", "일")

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


def _brief_job(header: str):
    """signal/trade/portfolio 를 Discord 채널로 전송.

    Discord content 2000자 제한 회피를 위해 명령어별로 분리 전송한다.
    명령어 빌더(handle_command)를 그대로 재사용해 슬래시 명령과 동일한 출력.
    """
    from services.discord_bot import handle_command
    from services.discord_service import send_discord
    now = datetime.now(KST)
    date_line = f"**{now:%Y-%m-%d} ({_WEEKDAY_KR[now.weekday()]})**"
    send_discord(f"{date_line}\n{header}")
    for cmd in ("portfolio", "signal", "trade"):
        try:
            send_discord(handle_command(cmd))
        except Exception as e:
            logger.warning(f"브리핑 {cmd} 실패: {e}")


def start() -> None:
    """활성화된 스케줄(회차기록/사전장 브리핑)이 있으면 스케줄러 시작."""
    global _scheduler
    if not (SCHEDULE_ENABLED or PREMARKET_BRIEF_ENABLED):
        logger.info("⏰ 스케줄 비활성 (SCHEDULE_ENABLED / PREMARKET_BRIEF_ENABLED=false)")
        return
    if _scheduler is not None:
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        logger.warning("apscheduler 미설치 — 스케줄 건너뜀 (pip install apscheduler)")
        return
    _scheduler = BackgroundScheduler(timezone="Asia/Seoul")

    if SCHEDULE_ENABLED:
        _scheduler.add_job(
            _job, "cron", day_of_week="mon-sat", hour="0-6,17-23", minute="*/5",
            id="cycle_record", max_instances=1, coalesce=True,
        )
        logger.info("⏰ 회차기록 스케줄 활성화 (KST 0~6·17~23, 평일~토, 5분 간격)")

    if PREMARKET_BRIEF_ENABLED:
        # timezone 지정으로 서머타임 자동 처리 (EDT=KST-13h / EST=KST-14h)
        # 사전장 개장: 미 동부 04:00
        _scheduler.add_job(
            lambda: _brief_job("🔔 **미국 사전장 시작** — TQQQ 자동 브리핑"),
            "cron", day_of_week="mon-fri", hour=4, minute=0,
            timezone="America/New_York",
            id="premarket_brief", max_instances=1, coalesce=True,
        )
        # 장종료 후: 미 동부 16:00 (정규장 마감)
        _scheduler.add_job(
            lambda: _brief_job("🏁 **미국 장 종료** — TQQQ 마감 브리핑"),
            "cron", day_of_week="mon-fri", hour=16, minute=0,
            timezone="America/New_York",
            id="close_brief", max_instances=1, coalesce=True,
        )
        logger.info("🔔 브리핑 스케줄 활성화 (ET 04:00 사전장 개장 · 16:00 장종료, 평일)")

    _scheduler.start()


def stop() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None
