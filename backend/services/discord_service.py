"""Discord 웹훅 알림 서비스"""
import requests
import logging
from config import DISCORD_WEBHOOK_URL

logger = logging.getLogger(__name__)


def send_discord(message: str, username: str = "TRAKIT") -> bool:
    """Discord 웹훅으로 메시지 전송"""
    if not DISCORD_WEBHOOK_URL:
        logger.warning("Discord webhook URL이 설정되지 않았습니다")
        return False
    try:
        resp = requests.post(
            DISCORD_WEBHOOK_URL,
            json={"content": message, "username": username},
            timeout=5,
        )
        resp.raise_for_status()
        logger.info(f"📨 Discord 알림 전송: {message[:50]}...")
        return True
    except Exception as e:
        logger.warning(f"Discord 알림 실패: {e}")
        return False


def notify_signal(signal_type: str, price: float, recommendation: str):
    """매매 시그널 알림"""
    emoji = {"BUY": "🔵", "SELL": "🔴", "HOLD": "🟢"}.get(signal_type, "⚪")
    msg = f"{emoji} **{signal_type}** | TQQQ ${price:.2f}\n{recommendation}"
    send_discord(msg)


def notify_price(price: float, change: float, change_pct: float):
    """가격 변동 알림"""
    arrow = "📈" if change >= 0 else "📉"
    msg = f"{arrow} TQQQ **${price:.2f}** ({change:+.2f}, {change_pct:+.2f}%)"
    send_discord(msg)


def notify_refresh(rows: int, valid_rows: int):
    """데이터 갱신 알림"""
    send_discord(f"📊 데이터 갱신 완료: {rows}행 (유효 {valid_rows}행)")
