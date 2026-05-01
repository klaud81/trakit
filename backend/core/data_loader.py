"""CSV/TSV/Google Sheets 데이터 로더"""
import pandas as pd
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
from config import BASE_SHEET_CSV, TRADE_SHEET_CSV, EXCHANGE_RATE_TSV, GOOGLE_SHEET_URL, USE_GOOGLE_SHEETS
from core.models import WeekData, TradePoint, SignalType
import math

logger = logging.getLogger(__name__)


def _load_from_google_sheets() -> pd.DataFrame:
    """Google Sheets에서 데이터 로딩"""
    df = pd.read_csv(GOOGLE_SHEET_URL)

    # 사용할 컬럼만 선택 (처음 20개)
    df = df.iloc[:, :20]

    # 컬럼명 매핑
    df.columns = [
        "seq", "week_label", "date_range",
        "two_sqrt_g", "price", "shares", "avg_cost", "dividend",
        "valuation", "pool", "contribution", "g",
        "target_value", "min_band", "max_band",
        "trade_amount", "pool_start", "pool_end", "fee_rate", "purchase"
    ]

    # week_label에서 week_num 추출 ("142 주차" → "142", "205주차" → "205")
    df["week_num"] = df["week_label"].astype(str).str.extract(r'(\d+)')[0]

    return df


def _load_from_csv(path: Optional[Path] = None) -> pd.DataFrame:
    """로컬 CSV에서 데이터 로딩"""
    csv_path = path or BASE_SHEET_CSV
    df = pd.read_csv(csv_path)

    df.columns = [
        "seq", "week_num", "week_label", "date_range",
        "two_sqrt_g", "price", "shares", "avg_cost", "dividend",
        "valuation", "pool", "contribution", "g",
        "target_value", "min_band", "max_band",
        "trade_amount", "pool_start", "pool_end", "fee_rate", "purchase"
    ]

    return df


_sheet_cache: Optional[pd.DataFrame] = None
_sheet_cache_time: Optional[datetime] = None
SHEET_CACHE_TTL_DAYS = 5


def load_base_sheet(path: Optional[Path] = None) -> pd.DataFrame:
    """base_sheet 로딩 (캐시 5일 유효, 만료 시 자동 갱신)"""
    global _sheet_cache, _sheet_cache_time

    if _sheet_cache is not None and _sheet_cache_time and path is None:
        elapsed = (datetime.now() - _sheet_cache_time).total_seconds()
        if elapsed < SHEET_CACHE_TTL_DAYS * 86400:
            return _sheet_cache.copy()
        logger.info("📊 Google Sheets 캐시 만료 (5일), 자동 갱신")

    df = None

    if USE_GOOGLE_SHEETS and path is None:
        try:
            df = _load_from_google_sheets()
            logger.info("📊 Google Sheets 데이터 캐시 저장")
        except Exception as e:
            logger.warning(f"Google Sheets 로딩 실패, 로컬 CSV fallback: {e}")

    if df is None:
        df = _load_from_csv(path)
        logger.info("📊 로컬 CSV 데이터 캐시 저장")

    # week_num은 문자열로 보존 (204-1, 208-1 등 지원)
    df["week_num"] = df["week_num"].astype(str).str.strip()

    # 나머지 숫자 변환 (purchase 는 콤마 구분 체결가 리스트일 수 있어 string 보존)
    numeric_cols = [
        "seq", "two_sqrt_g", "price", "shares", "avg_cost",
        "dividend", "valuation", "pool", "contribution", "g",
        "target_value", "min_band", "max_band", "trade_amount",
        "pool_start", "pool_end", "fee_rate",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["purchase"] = df["purchase"].astype(str).fillna("").replace("nan", "")

    if path is None:
        _sheet_cache = df.copy()
        _sheet_cache_time = datetime.now()

    return df


def refresh_base_sheet() -> pd.DataFrame:
    """캐시를 강제 갱신하고 새 데이터를 반환"""
    global _sheet_cache, _sheet_cache_time
    _sheet_cache = None
    _sheet_cache_time = None
    return load_base_sheet()


def load_exchange_rates(path: Optional[Path] = None) -> pd.DataFrame:
    """exchange_rate_sheet.tsv 로딩"""
    tsv_path = path or EXCHANGE_RATE_TSV
    df = pd.read_csv(tsv_path, sep="\t")
    df.columns = [
        "seq", "week_label", "date_range", "two_sqrt_g",
        "exchange_rate", "v", "min_band", "max_band"
    ]
    numeric_cols = ["seq", "two_sqrt_g", "exchange_rate", "v", "min_band", "max_band"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def get_week_data_list(df: Optional[pd.DataFrame] = None) -> List[WeekData]:
    """base_sheet를 WeekData 리스트로 변환"""
    if df is None:
        df = load_base_sheet()

    weeks = []
    for _, row in df.iterrows():
        week = WeekData(
            seq=int(row["seq"]) if pd.notna(row["seq"]) else 0,
            week_num=int(row["week_num"]) if pd.notna(row["week_num"]) else 0,
            week_label=str(row["week_label"]) if pd.notna(row["week_label"]) else "",
            date_range=str(row["date_range"]) if pd.notna(row["date_range"]) else None,
            two_sqrt_g=float(row["two_sqrt_g"]) if pd.notna(row["two_sqrt_g"]) else 0.0,
            price=float(row["price"]) if pd.notna(row["price"]) else None,
            shares=int(row["shares"]) if pd.notna(row["shares"]) else None,
            avg_cost=float(row["avg_cost"]) if pd.notna(row["avg_cost"]) else None,
            dividend=float(row["dividend"]) if pd.notna(row["dividend"]) else None,
            valuation=float(row["valuation"]) if pd.notna(row["valuation"]) else None,
            pool=float(row["pool"]) if pd.notna(row["pool"]) else None,
            contribution=float(row["contribution"]) if pd.notna(row["contribution"]) else None,
            g=int(row["g"]) if pd.notna(row["g"]) else None,
            target_value=float(row["target_value"]) if pd.notna(row["target_value"]) else None,
            min_band=float(row["min_band"]) if pd.notna(row["min_band"]) else None,
            max_band=float(row["max_band"]) if pd.notna(row["max_band"]) else None,
            trade_amount=float(row["trade_amount"]) if pd.notna(row["trade_amount"]) else None,
            pool_start=float(row["pool_start"]) if pd.notna(row["pool_start"]) else None,
            pool_end=float(row["pool_end"]) if pd.notna(row["pool_end"]) else None,
            fee_rate=float(row["fee_rate"]) if pd.notna(row["fee_rate"]) else None,
            purchase=float(row["purchase"]) if pd.notna(row["purchase"]) else None,
        )
        weeks.append(week)
    return weeks


def get_latest_week(df: Optional[pd.DataFrame] = None) -> WeekData:
    """가격 데이터가 있는 마지막 주차 반환"""
    if df is None:
        df = load_base_sheet()
    # 가격이 있는 행만 필터
    valid = df[df["price"].notna()]
    if valid.empty:
        raise ValueError("가격 데이터가 없습니다")
    last = valid.iloc[-1]
    weeks = get_week_data_list(valid.tail(1))
    return weeks[0]


def parse_trade_points() -> Tuple[List[dict], List[dict], dict]:
    """trade_sheet.csv에서 매수/매도 포인트 파싱"""
    buy_points = []
    sell_points = []
    settings = {}

    with open(TRADE_SHEET_CSV, "r") as f:
        lines = f.readlines()

    section = None
    for line in lines:
        line = line.strip()
        if "매수 테이블" in line:
            section = "buy"
            continue
        elif "매도 테이블" in line:
            section = "sell"
            continue
        elif "매매 설정" in line:
            section = "settings"
            continue
        elif "요약" in line or "진행률" in line:
            section = "summary"
            continue

        if not line or line.startswith("시트") or line.startswith("TQQQ") or line.startswith("현재"):
            continue

        parts = [p.strip() for p in line.split(",")]

        if section == "buy":
            if parts[0] == "최소값" or parts[0] == "":
                # 헤더 또는 데이터행
                if len(parts) >= 4:
                    try:
                        shares = int(float(parts[1])) if parts[1] else None
                        price = float(parts[2]) if parts[2] else None
                        pool = float(parts[3]) if parts[3] else None
                        if shares and price:
                            buy_points.append({
                                "shares": shares,
                                "price": price,
                                "pool_after": pool,
                            })
                    except (ValueError, IndexError):
                        pass

        elif section == "sell":
            if len(parts) >= 5:
                try:
                    shares = int(float(parts[2])) if parts[2] else None
                    price = float(parts[3]) if parts[3] else None
                    pool = float(parts[4]) if parts[4] else None
                    if shares and price:
                        sell_points.append({
                            "shares": shares,
                            "price": price,
                            "pool_after": pool,
                        })
                except (ValueError, IndexError):
                    pass

        elif section == "settings":
            if len(parts) >= 2 and parts[0]:
                try:
                    settings[parts[0]] = int(float(parts[1]))
                except (ValueError, IndexError):
                    pass

    return buy_points, sell_points, settings
