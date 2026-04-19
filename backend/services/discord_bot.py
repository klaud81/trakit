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
            "name": "help",
            "description": "전체 명령어 사용법 안내",
        },
        {
            "name": "price",
            "description": "TQQQ 현재 가격 조회",
        },
        {
            "name": "signal",
            "description": "매매 시그널 조회 (오프셋: -1 이전 주차)",
            "options": [{"name": "offset", "description": "주차 오프셋 (0=현재, -1=이전, -2=2주전...)", "type": 4, "required": False}],
        },
        {
            "name": "portfolio",
            "description": "포트폴리오 현황 조회 (오프셋: -1 이전 주차)",
            "options": [{"name": "offset", "description": "주차 오프셋 (0=현재, -1=이전, -2=2주전...)", "type": 4, "required": False}],
        },
        {
            "name": "rate",
            "description": "USD/KRW 환율 조회",
        },
        {
            "name": "quote",
            "description": "티커 실시간 가격 조회",
            "options": [{"name": "symbol", "description": "티커 심볼 (예: NVDA, TSLA, SPY)", "type": 3, "required": True}],
        },
        {
            "name": "watch",
            "description": "관심 티커 목록 조회",
        },
        {
            "name": "refresh",
            "description": "Google Sheets 데이터 갱신",
        },
    ]

    url = f"https://discord.com/api/v10/applications/{DISCORD_APP_ID}/commands"
    headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}

    # Bulk overwrite: 한 번의 PUT 요청으로 전체 명령어를 원자적으로 갱신 (rate limit 회피)
    try:
        resp = requests.put(url, json=commands, headers=headers, timeout=15)
        if resp.status_code in (200, 201):
            names = ", ".join(f"/{c['name']}" for c in commands)
            logger.info(f"📎 Discord 명령어 등록 ({len(commands)}개): {names}")
        else:
            logger.warning(f"Discord 명령어 등록 실패: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"Discord 명령어 등록 에러: {e}")


def _get_week_by_offset(offset: int) -> dict:
    """히스토리에서 오프셋 기준 주차 데이터 조회 (0=마지막, -1=이전)"""
    from services.portfolio_service import get_portfolio_history
    history = get_portfolio_history()
    if not history:
        return None
    idx = len(history) - 1 + offset
    if idx < 0 or idx >= len(history):
        return None
    return history[idx]


def _build_help_text() -> str:
    from config import WATCHLIST
    tickers = ", ".join(WATCHLIST)
    return (
        "📖 **Trakit 명령어 도움말**\n"
        "`/help` — 전체 명령어 사용법 안내\n"
        "`/price` — TQQQ 현재 실시간 가격\n"
        "`/signal [offset]` — 매매 시그널 (BUY/SELL/HOLD). `offset` 미지정 시 현재, `-1` 이전 주차, `-2` 2주 전...\n"
        "`/portfolio [offset]` — 포트폴리오 현황 (평가금·Pool·총자산). `offset` 규칙은 `/signal`과 동일\n"
        "`/quote <symbol>` — 개별 티커 실시간 가격 (예: `/quote symbol:NVDA`)\n"
        f"`/watch` — 관심 티커 목록 [{tickers}]\n"
        "`/rate` — USD/KRW 환율"
    )


def handle_command(command_name: str, options: dict = None) -> str:
    """슬래시 명령어 처리 → 응답 메시지 생성"""
    try:
        if command_name == "help":
            return _build_help_text()

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
            offset = (options or {}).get("offset", 0)
            if offset and offset < 0:
                # 이전 주차 조회
                week = _get_week_by_offset(offset)
                if not week:
                    return f"❌ 오프셋 {offset}에 해당하는 주차 데이터가 없습니다."
                from core.signal_calculator import generate_signal
                valuation = week["valuation"]
                min_b = week["min_band"]
                max_b = week["max_band"]
                st = "BUY" if valuation < min_b else "SELL" if valuation > max_b else "HOLD"
                band_range = max_b - min_b
                pos = int((valuation - min_b) / band_range * 100) if band_range > 0 else 50
                emoji = {"BUY": "🔵", "SELL": "🔴", "HOLD": "🟢"}.get(st, "⚪")
                msg = f"{emoji} **{st}** | {week['week_num']}주차 ({week.get('date_range', '')})\n"
                msg += f"가격: ${week['price']:.2f} | 밴드 내 {pos}% 위치\n"
                avg_cost = week.get("avg_cost")
                if avg_cost and avg_cost > 0:
                    profit = (week["price"] - avg_cost) * week["shares"]
                    profit_pct = (week["price"] - avg_cost) / avg_cost * 100
                    msg += f"수익률: {profit:+,.0f}$ ({profit_pct:+.2f}%)"
                return msg
            else:
                # 현재 (실시간)
                from services.portfolio_service import get_current_portfolio
                from services.price_service import get_current_price
                from core.signal_calculator import generate_signal
                live = get_current_price()
                current_price = live["price"] if live["price"] > 0 else None
                portfolio = get_current_portfolio(current_price=current_price)
                signal = generate_signal(portfolio, current_price=current_price)
                emoji = {"BUY": "🔵", "SELL": "🔴", "HOLD": "🟢"}.get(signal["signal_type"], "⚪")
                date_range = portfolio.get('date_range', '')
                msg = f"{emoji} **{signal['signal_type']}** | {portfolio['week_num']}주차 ({date_range})\n"
                msg += f"TQQQ ${live['price']:.2f} ({live['change']:+.2f}, {live['change_pct']:+.2f}%)\n"
                msg += f"{signal['recommendation']}\n"
                if portfolio.get("profit") is not None:
                    msg += f"수익률: {portfolio['profit']:+,.0f}$ ({portfolio['profit_pct']:+.2f}%)"
                return msg

        elif command_name == "portfolio":
            offset = (options or {}).get("offset", 0)
            if offset and offset < 0:
                week = _get_week_by_offset(offset)
                if not week:
                    return f"❌ 오프셋 {offset}에 해당하는 주차 데이터가 없습니다."
                valuation = week["valuation"]
                pool = week["pool"]
                total = valuation + pool
                msg = f"📊 **포트폴리오** ({week['week_num']}주차 · {week.get('date_range', '')})\n"
                msg += f"가격: ${week['price']:.2f} | 평가금: ${valuation:,.2f}\n"
                msg += f"보유: {week['shares']}주"
                avg_cost = week.get("avg_cost")
                if avg_cost:
                    msg += f" · 평단 ${avg_cost:.2f}"
                msg += f"\nPool: ${pool:,.2f}\n"
                msg += f"총 자산: **${total:,.2f}**"
                return msg
            else:
                from services.portfolio_service import get_current_portfolio
                from services.price_service import get_current_price
                live = get_current_price()
                p = get_current_portfolio(current_price=live["price"] if live["price"] > 0 else None)
                msg = f"📊 **포트폴리오** ({p['week_num']}주차 · {p.get('date_range', '')})\n"
                msg += f"평가금: ${p['valuation']:,.2f}\n"
                trade_shares = p.get("trade_shares")
                trade_info = ""
                if trade_shares and trade_shares != 0:
                    label = "매도" if trade_shares < 0 else "매수"
                    trade_amt = p.get("trade_amount", 0) or 0
                    trade_info = f" ({label} {abs(trade_shares)}주 · ${trade_amt:,.2f})"
                msg += f"보유: {p['shares']}주 · 평단 ${p.get('avg_cost', 0) or 0:.2f}{trade_info}\n"
                msg += f"Pool: ${p['pool']:,.2f}\n"
                msg += f"총 자산: **${p['total_value']:,.2f}**\n"
                msg += f"목표 달성률: {p['goal_progress']:.2f}%"
                return msg

        elif command_name == "quote":
            symbol = (options or {}).get("symbol", "TQQQ").upper()
            from services.price_service import get_current_price
            p = get_current_price(symbol=symbol)
            if p["price"] == 0:
                return f"❌ {symbol}: 가격 조회 실패"
            arrow = "📈" if p["change"] >= 0 else "📉"
            msg = f"{arrow} **{symbol} ${p['price']:.2f}**\n"
            msg += f"변동: {p['change']:+.2f} ({p['change_pct']:+.2f}%)\n"
            msg += f"전일종가: ${p['prev_close']}"
            if p.get("day_high"):
                msg += f" | 고가: ${p['day_high']} | 저가: ${p['day_low']}"
            return msg

        elif command_name == "watch":
            from config import WATCHLIST
            msg = "📋 **관심 티커 목록**\n"
            msg += " · ".join(WATCHLIST)
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
