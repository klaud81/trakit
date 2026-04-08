"""API 엔드포인트"""
from fastapi import APIRouter, HTTPException, Query
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
from core.signal_calculator import generate_signal

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


@router.get("/exchange-rate")
async def exchange_rate():
    """USD/KRW 환율 (하루 1회 갱신)"""
    try:
        return get_exchange_rate()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
