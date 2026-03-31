"""Trakit 데이터 모델 정의"""
from pydantic import BaseModel
from typing import Optional, List
from enum import Enum
from datetime import datetime


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class GrowthStage(BaseModel):
    """성장 구간 (G)"""
    stage: int  # G값 (11, 12, 13)
    two_over_sqrt_g: float  # 2/√G 값
    contribution: float  # 적립금 (보통 200)


class WeekData(BaseModel):
    """주차별 데이터 (base_sheet.csv 한 행)"""
    seq: int  # 순번
    week_num: int  # 주차 번호 (142, 144, ...)
    week_label: str  # "142 주차"
    date_range: Optional[str] = None  # "1/15~1/26"
    two_sqrt_g: float  # 2/루트G
    price: Optional[float] = None  # TQQQ 가격
    shares: Optional[int] = None  # 보유갯수
    avg_cost: Optional[float] = None  # 구매평단
    dividend: Optional[float] = None  # 배당금
    valuation: Optional[float] = None  # 평가금(E) = 가격 × 보유갯수
    pool: Optional[float] = None  # 투자 가용 현금
    contribution: Optional[float] = None  # 적립금
    g: Optional[int] = None  # 성장 구간 번호
    target_value: Optional[float] = None  # V (목표 가치)
    min_band: Optional[float] = None  # 최소 밴드
    max_band: Optional[float] = None  # 최대 밴드
    trade_amount: Optional[float] = None  # 거래액 (매수- / 매도+)
    pool_start: Optional[float] = None  # 처음 pool
    pool_end: Optional[float] = None  # 마지막 pool
    fee_rate: Optional[float] = None  # 수수료율
    purchase: Optional[float] = None  # 구매 금액


class Portfolio(BaseModel):
    """현재 포트폴리오 상태"""
    week_num: int
    date_range: Optional[str] = None
    price: float
    shares: int
    avg_cost: Optional[float] = None
    valuation: float  # price × shares
    pool: float
    target_value: float  # V
    min_band: float
    max_band: float
    growth_stage: int  # G
    total_value: float  # valuation + pool
    goal_progress: float  # 목표 대비 진행률 (%)
    updated_at: Optional[datetime] = None


class Signal(BaseModel):
    """매매 시그널"""
    signal_type: SignalType
    confidence: float  # 0~1 (밴드 내 위치 기반)
    current_valuation: float
    target_value: float
    min_band: float
    max_band: float
    distance_to_buy: float  # 매수 밴드까지 거리
    distance_to_sell: float  # 매도 밴드까지 거리
    recommendation: str  # 한글 추천 메시지
    timestamp: Optional[datetime] = None


class TradePoint(BaseModel):
    """매수/매도 포인트"""
    action: SignalType  # BUY or SELL
    shares_after: int  # 거래 후 보유 수량
    price: float  # 매매 가격
    amount: float  # 거래 금액
    pool_after: float  # 거래 후 pool


class TradePoints(BaseModel):
    """매수/매도 포인트 테이블"""
    current_shares: int
    current_min: float
    current_max: float
    buy_points: List[TradePoint]
    sell_points: List[TradePoint]
    unit_size: int = 10  # 기준수량


class BacktestResult(BaseModel):
    """백테스팅 결과"""
    start_week: int
    end_week: int
    total_weeks: int
    total_trades: int
    buy_count: int
    sell_count: int
    hold_count: int
    initial_value: float
    final_value: float
    total_return_pct: float
    total_contributions: float
    equity_curve: List[dict]  # [{week, valuation, pool, total}]


class PriceData(BaseModel):
    """실시간 가격 데이터"""
    symbol: str = "TQQQ"
    price: float
    change: float
    change_pct: float
    timestamp: datetime
    prev_close: Optional[float] = None
    day_high: Optional[float] = None
    day_low: Optional[float] = None
