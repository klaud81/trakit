"""Discord Bot 인터랙션 핸들러

슬래시 명령어를 처리하여 trakit API 데이터를 Discord에 반환.
Discord Interactions Endpoint 방식 (HTTP 기반, 별도 프로세스 불필요).
"""
import requests
import logging
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError
from config import DISCORD_APP_ID, DISCORD_PUBLIC_KEY, DISCORD_BOT_TOKEN

logger = logging.getLogger(__name__)

# Discord Interaction Types
PING = 1
APPLICATION_COMMAND = 2

# Discord Response Types
PONG = 1
CHANNEL_MESSAGE = 4


def verify_signature(body: bytes, signature: str, timestamp: str) -> bool:
    """Discord 요청 서명 검증"""
    try:
        vk = VerifyKey(bytes.fromhex(DISCORD_PUBLIC_KEY))
        vk.verify(timestamp.encode() + body, bytes.fromhex(signature))
        return True
    except (BadSignatureError, Exception):
        return False


def register_slash_commands():
    """Discord 슬래시 명령어 등록"""
    if not DISCORD_APP_ID or not DISCORD_BOT_TOKEN:
        logger.warning("Discord Bot 설정 없음, 슬래시 명령어 등록 건너뜀")
        return

    commands = [
        {
            "name": "price",
            "description": "TQQQ 현재 가격 조회",
        },
        {
            "name": "signal",
            "description": "현재 매매 시그널 조회",
        },
        {
            "name": "portfolio",
            "description": "포트폴리오 현황 조회",
        },
        {
            "name": "rate",
            "description": "USD/KRW 환율 조회",
        },
        {
            "name": "refresh",
            "description": "Google Sheets 데이터 갱신",
        },
    ]

    url = f"https://discord.com/api/v10/applications/{DISCORD_APP_ID}/commands"
    headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}

    for cmd in commands:
        try:
            resp = requests.post(url, json=cmd, headers=headers, timeout=10)
            if resp.status_code in (200, 201):
                logger.info(f"📎 Discord 명령어 등록: /{cmd['name']}")
            else:
                logger.warning(f"Discord 명령어 등록 실패: /{cmd['name']} ({resp.status_code})")
        except Exception as e:
            logger.warning(f"Discord 명령어 등록 에러: {e}")


def handle_command(command_name: str) -> str:
    """슬래시 명령어 처리 → 응답 메시지 생성"""
    try:
        if command_name == "price":
            from services.price_service import get_current_price
            p = get_current_price()
            arrow = "📈" if p["change"] >= 0 else "📉"
            msg = f"{arrow} **TQQQ ${p['price']:.2f}**\n"
            msg += f"변동: {p['change']:+.2f} ({p['change_pct']:+.2f}%)\n"
            msg += f"전일종가: ${p['prev_close']}"
            if p.get("day_high"):
                msg += f" | 고가: ${p['day_high']} | 저가: ${p['day_low']}"
            return msg

        elif command_name == "signal":
            from services.portfolio_service import get_current_portfolio
            from core.signal_calculator import generate_signal
            portfolio = get_current_portfolio()
            signal = generate_signal(portfolio)
            emoji = {"BUY": "🔵", "SELL": "🔴", "HOLD": "🟢"}.get(signal["signal_type"], "⚪")
            msg = f"{emoji} **{signal['signal_type']}**\n"
            msg += f"{signal['recommendation']}\n"
            if portfolio.get("avg_cost") and portfolio["avg_cost"] > 0:
                profit_pct = (portfolio["price"] - portfolio["avg_cost"]) / portfolio["avg_cost"] * 100
                total_profit = (portfolio["price"] - portfolio["avg_cost"]) * portfolio["shares"]
                msg += f"수익률: {total_profit:+,.0f}$ ({profit_pct:+.2f}%)"
            return msg

        elif command_name == "portfolio":
            from services.portfolio_service import get_current_portfolio
            p = get_current_portfolio()
            msg = f"📊 **포트폴리오** ({p['week_num']}주차)\n"
            msg += f"평가금: ${p['valuation']:,.2f}\n"
            msg += f"보유: {p['shares']}주 · 평단 ${p.get('avg_cost', 0) or 0:.2f}\n"
            msg += f"Pool: ${p['pool']:,.2f}\n"
            msg += f"총 자산: **${p['total_value']:,.2f}**\n"
            msg += f"목표 달성률: {p['goal_progress']:.2f}%"
            return msg

        elif command_name == "rate":
            from services.exchange_rate_service import get_exchange_rate
            r = get_exchange_rate()
            msg = f"💱 **1 USD = {r['rate']:,.2f} KRW**\n"
            msg += f"날짜: {r['date']} | 소스: {r['source']}"
            return msg

        elif command_name == "refresh":
            from core.data_loader import refresh_base_sheet
            df = refresh_base_sheet()
            valid = len(df[df["price"].notna()])
            return f"📊 데이터 갱신 완료: {len(df)}행 (유효 {valid}행)"

        else:
            return f"알 수 없는 명령어: /{command_name}"

    except Exception as e:
        logger.error(f"Discord 명령어 처리 실패: {command_name} - {e}")
        return f"❌ 오류: {str(e)}"
