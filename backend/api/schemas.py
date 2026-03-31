"""API 요청/응답 스키마"""
from pydantic import BaseModel
from typing import Optional


class BacktestRequest(BaseModel):
    start_week: Optional[int] = None
    end_week: Optional[int] = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
