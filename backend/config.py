"""Trakit 설정"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)

# 프로젝트 루트 (backend/ 의 부모 = trakit/)
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = Path(os.getenv("TRAKIT_DATA_DIR", str(PROJECT_ROOT / "data")))

# backend/ 디렉토리
BACKEND_DIR = Path(__file__).parent

# 데이터 파일 경로 (로컬 fallback)
BASE_SHEET_CSV = DATA_DIR / "base_sheet.csv"
TRADE_SHEET_CSV = DATA_DIR / "trade_sheet.csv"
EXCHANGE_RATE_TSV = DATA_DIR / "exchange_rate_sheet.tsv"

# Google Sheets 설정
GOOGLE_SHEET_ID = "1dI12c4AikkHMiT9dXRUhTCPxJwPA08IzBqAsl8zwUsM"
GOOGLE_SHEET_URL = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/export?format=csv&gid=0"
USE_GOOGLE_SHEETS = True  # True면 Google Sheets에서 데이터 로딩

# 투자 설정
SYMBOL = "TQQQ"
WATCHLIST = ["TQQQ", "KORU", "QQQ", "SQQQ", "SPY", "SOXL", "SOXS", "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "GOOG", "META"]
CONTRIBUTION_PER_CYCLE = 200  # 2주마다 $200 적립
REBALANCE_INTERVAL_WEEKS = 2
GOAL_WEEK = 560  # 목표 주차
GOAL_KRW = 1_000_000_000  # 10억원
DEFAULT_EXCHANGE_RATE = 1400  # 기본 환율

# 성장 구간 설정
GROWTH_STAGES = {
    12: {"two_sqrt_g": 3.46410162, "label": "초기"},
    13: {"two_sqrt_g": 3.60555128, "label": "중간"},
    11: {"two_sqrt_g": 3.60555128, "label": "후반"},
}

# 매매 설정
TRADE_UNIT = 10  # 기준수량
TRADE_STEP = 10  # 단수
EXTRA_QUANTITY = 100  # 추가수량

# 수수료
DEFAULT_FEE_RATE = 0.003  # 0.3%

# 실시간 가격 조회 정책
# True(기본) → 시간대 무관 항상 갱신, False → KST 21~06시에만 갱신 (장외 캐시 고정)
PRICE_FETCH_ALWAYS = os.getenv("PRICE_FETCH_ALWAYS", "true").lower() == "true"

# 한국투자증권 API
KIS_APP_KEY = os.getenv("KIS_APP_KEY", "")
KIS_APP_SECRET = os.getenv("KIS_APP_SECRET", "")
KIS_MOCK = os.getenv("KIS_MOCK", "true").lower() == "true"
_KIS_MOCK_URL = "https://openapivts.koreainvestment.com:29443"
_KIS_REAL_URL = "https://openapi.koreainvestment.com:9443"
KIS_BASE_URL = os.getenv("KIS_BASE_URL", _KIS_MOCK_URL if KIS_MOCK else _KIS_REAL_URL)

# Discord
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_APP_ID = os.getenv("DISCORD_APP_ID", "")
DISCORD_PUBLIC_KEY = os.getenv("DISCORD_PUBLIC_KEY", "")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")

# API 설정
API_HOST = os.getenv("TRAKIT_HOST", "0.0.0.0")
API_PORT = int(os.getenv("TRAKIT_PORT", "8000"))
CORS_ORIGINS = ["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173", "http://localhost:8080", "http://127.0.0.1:8080", "*"]
