"""API 엔드포인트"""
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from typing import Optional

from api.schemas import BacktestRequest, HealthResponse
from services.portfolio_service import (
    get_current_portfolio,
    get_portfolio_history,
    get_remaining_cycles,
)
from services.price_service import get_current_price, get_price_history
from services.trade_calculator import get_trade_points, get_saved_trade_points, get_trade_points_by_params
from services.backtesting_service import run_backtest
from services.exchange_rate_service import get_exchange_rate
from core.data_loader import refresh_base_sheet
from services.visitor_service import record_visit, get_visitor_stats
from core.signal_calculator import generate_signal
from services.discord_service import notify_signal, notify_refresh, send_discord
from services.discord_bot import verify_signature, handle_command, register_slash_commands, PING, APPLICATION_COMMAND, PONG, CHANNEL_MESSAGE

router = APIRouter(prefix="/api")


@router.get("/health")
async def health():
    return HealthResponse()


@router.get("/portfolio")
async def portfolio(price: Optional[float] = Query(None, description="실시간 가격 오버라이드")):
    """현재 포트폴리오 상태"""
    try:
        return get_current_portfolio(current_price=price)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/portfolio/history")
async def portfolio_history():
    """포트폴리오 히스토리 (차트 데이터)"""
    try:
        return get_portfolio_history()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signals")
async def signals(price: Optional[float] = Query(None)):
    """현재 매매 시그널"""
    try:
        portfolio = get_current_portfolio(current_price=price)
        signal = generate_signal(portfolio, current_price=price)
        signal["profit"] = portfolio.get("profit")
        signal["profit_pct"] = portfolio.get("profit_pct")
        return signal
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/price")
async def price():
    """실시간 TQQQ 가격"""
    try:
        return get_current_price()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/price/history")
async def price_history(period: str = Query("6mo", description="기간: 1d,5d,1mo,3mo,6mo,1y,2y")):
    """TQQQ 가격 히스토리"""
    try:
        return get_price_history(period=period)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trade-points")
async def trade_points(price: Optional[float] = Query(None)):
    """매수/매도 포인트 테이블"""
    try:
        return get_trade_points(current_price=price)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trade-points/calc")
async def trade_points_calc(
    shares: int = Query(..., description="보유수량"),
    min_band: float = Query(..., description="최소밴드"),
    max_band: float = Query(..., description="최대밴드"),
    pool: float = Query(..., description="Pool 잔고"),
    unit: Optional[int] = Query(None, description="기준 단수 (미지정 시 자동계산: pool/13/(min_band/shares)/2)"),
):
    """주차 파라미터 기반 매수/매도 포인트 계산"""
    try:
        return get_trade_points_by_params(shares, min_band, max_band, pool, unit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trade-points/saved")
async def saved_trade_points():
    """CSV에 저장된 매매 포인트"""
    try:
        return get_saved_trade_points()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/backtest")
async def backtest(req: BacktestRequest):
    """백테스트 실행"""
    try:
        return run_backtest(start_week=req.start_week, end_week=req.end_week)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/remaining")
async def remaining():
    """남은 적립 횟수"""
    try:
        return get_remaining_cycles()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config")
async def config():
    """프론트엔드 설정 (자동 갱신 시간대, 간격 등)"""
    return {
        "price_refresh_interval": 20,
        "price_refresh_start_hour": 21,
        "price_refresh_end_hour": 6,
        "timezone": "Asia/Seoul",
    }


@router.post("/refresh")
async def refresh():
    """Google Sheets 데이터 강제 갱신"""
    try:
        df = refresh_base_sheet()
        valid = len(df[df["price"].notna()])
        notify_refresh(len(df), valid)
        return {"status": "ok", "rows": len(df), "valid_rows": valid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/notify")
async def notify(message: str = Query(..., description="Discord 알림 메시지")):
    """Discord 웹훅 알림 전송"""
    try:
        ok = send_discord(message)
        return {"status": "ok" if ok else "failed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/exchange-rate")
async def exchange_rate():
    """USD/KRW 환율 (하루 1회 갱신)"""
    try:
        return get_exchange_rate()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/visit")
async def visit():
    """방문 기록"""
    try:
        record_visit()
        return get_visitor_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/visitors")
async def visitors():
    """방문자 통계 조회"""
    try:
        return get_visitor_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/discord/interactions")
async def discord_interactions(request: Request):
    """Discord 슬래시 명령어 처리 (Interactions Endpoint)"""
    body = await request.body()
    signature = request.headers.get("X-Signature-Ed25519", "")
    timestamp = request.headers.get("X-Signature-Timestamp", "")

    if not verify_signature(body, signature, timestamp):
        raise HTTPException(status_code=401, detail="Invalid signature")

    data = await request.json()

    if data.get("type") == PING:
        return JSONResponse({"type": PONG})

    if data.get("type") == APPLICATION_COMMAND:
        command_name = data["data"]["name"]
        raw_options = data["data"].get("options", [])
        options = {opt["name"]: opt["value"] for opt in raw_options}
        message = handle_command(command_name, options)
        return JSONResponse({
            "type": CHANNEL_MESSAGE,
            "data": {"content": message},
        })

    return JSONResponse({"type": PONG})
