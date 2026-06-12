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
# 시트 쓰기(회차기록 등 수정)용 서비스계정. 읽기는 공개 CSV, 쓰기는 SA 인증 필요.
# GOOGLE_SA_KEY: .env 에 JSON 내용 직접 포함(우선). 비면 GOOGLE_SA_JSON 파일 경로 사용.
GOOGLE_SA_KEY = os.getenv("GOOGLE_SA_KEY", "")
GOOGLE_SA_JSON = os.getenv("GOOGLE_SA_JSON", str(BACKEND_DIR / ".gsa.json"))

# 장중 회차기록 자동 기록 스케줄러 on/off (실전 .env.real 에서만 true 권장)
SCHEDULE_ENABLED = os.getenv("SCHEDULE_ENABLED", "false").lower() == "true"

# 미국 사전장 시작(ET 04:00) 시 signal/trade/portfolio 자동 Discord 브리핑 on/off.
# 미설정 시 SCHEDULE_ENABLED 값을 따라감 (실전에서만 자동 on)
PREMARKET_BRIEF_ENABLED = os.getenv(
    "PREMARKET_BRIEF_ENABLED", str(SCHEDULE_ENABLED)
).lower() == "true"

# 투자 설정
SYMBOL = "TQQQ"
WATCHLIST = ["TQQQ", "KORU", "QQQ", "SQQQ", "SPY", "SOXL", "SOXS", "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "GOOG", "META"]

# KIS 해외주식 거래소 코드 (정규장)
#   NAS=나스닥, NYS=뉴욕, AMS=아멕스/NYSE Arca
EXCHANGE_MAP = {
    "TQQQ": "NAS", "QQQ": "NAS", "SQQQ": "NAS",
    "NVDA": "NAS", "TSLA": "NAS", "AAPL": "NAS",
    "MSFT": "NAS", "AMZN": "NAS", "GOOG": "NAS", "META": "NAS",
    "KORU": "AMS", "SPY": "AMS", "SOXL": "AMS", "SOXS": "AMS",
}
DEFAULT_EXCHANGE = "NAS"

# 정규장 EXCD → 주간(사전장/시간외) EXCD 매핑
DAYTIME_EXCD = {"NAS": "BAQ", "NYS": "BAY", "AMS": "BAA"}
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

# 키움증권 REST API (KR 데이터 자체 수집용 — 100m1s 미러 대체)
# ── Kiwoom 환경 맵 (mock / real) ──────────────────────────────────────────
# env 를 모드별 dict 로 로딩해 사용. 각 환경: app_key·app_secret·base_url·account.
#   mock: 모의투자(mockapi.kiwoom.com, KRX만 지원) — 주문/체결 테스트용 (계좌 81277130)
#   real: 실전(api.kiwoom.com) — 관측·시세용
# 우선순위: KIWOOM_{MOCK|REAL}_* > (mock 한정) 레거시 KIWOOM_ORDER_* / KIWOOM_* 폴백
def _kiwoom_env(mode: str, base_default: str, legacy_key="", legacy_secret="", legacy_acct="") -> dict:
    p = f"KIWOOM_{mode.upper()}"
    return {
        "app_key": os.getenv(f"{p}_APP_KEY", legacy_key),
        "app_secret": os.getenv(f"{p}_APP_SECRET", legacy_secret),
        "base_url": os.getenv(f"{p}_BASE_URL", base_default),
        "account": os.getenv(f"{p}_ACCOUNT", legacy_acct),
    }

KIWOOM_ENVS = {
    "mock": _kiwoom_env("MOCK", "https://mockapi.kiwoom.com",
                        legacy_key=os.getenv("KIWOOM_ORDER_APP_KEY", ""),
                        legacy_secret=os.getenv("KIWOOM_ORDER_APP_SECRET", ""),
                        legacy_acct=os.getenv("KIWOOM_ACCOUNT", "")),
    "real": _kiwoom_env("REAL", "https://api.kiwoom.com",
                        legacy_key=os.getenv("KIWOOM_APP_KEY", ""),
                        legacy_secret=os.getenv("KIWOOM_APP_SECRET", ""),
                        legacy_acct=os.getenv("KIWOOM_ACCOUNT_REAL", "62596885")),  # 데이터키 계좌
}
KIWOOM_MODE = os.getenv("KIWOOM_MODE", "mock").lower()              # 활성 모드 (기본 mock)
KIWOOM_ENV = KIWOOM_ENVS.get(KIWOOM_MODE, KIWOOM_ENVS["mock"])      # 활성 환경 dict

# 데이터 파이프라인(ka10081 일봉)용 플랫 별칭 — 활성 모드(KIWOOM_MODE) 환경에서 파생.
# 기본 mock. real 데이터/관측이 필요하면 KIWOOM_MODE=real 또는 KIWOOM_ENVS["real"] 직접 사용.
# (주문은 항상 KIWOOM_ENVS["mock"] — kiwoom_order 전용)
KIWOOM_APP_KEY = KIWOOM_ENV["app_key"]
KIWOOM_APP_SECRET = KIWOOM_ENV["app_secret"]
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", KIWOOM_ENV["base_url"])

# VI 차익거래 관측 데이터 소스: mock(시뮬) | kiwoom(실연동 관측 전용, rq-01 FR-01~06)
VI_ARB_SOURCE = os.getenv("VI_ARB_SOURCE", "mock").lower()
# 관측 WS 환경: real 필수(NXT 차익 괴리는 mockapi 미지원). 주문은 별도로 항상 mock.
VI_ARB_OBS_ENV = os.getenv("VI_ARB_OBS_ENV", "real").lower()
# 1h 전종목 등록 불가 대비 감시 유니버스 (쉼표구분 종목코드). 비면 전종목 시도.
VI_ARB_UNIVERSE = [c.strip() for c in os.getenv("VI_ARB_UNIVERSE", "").split(",") if c.strip()]
# 모의 체결 시도(rq-01 Phase): true 시 VI 종목에 모의 주문. ⚠️ KIWOOM_ENVS["mock"]만 사용.
VI_ARB_ORDER = os.getenv("VI_ARB_ORDER", "false").lower() == "true"
# VI 매수 시총 하한 (억원). 이 미만 소형주는 VI 발동해도 매수 스킵 (유동성 보호). 0=필터 없음
VI_ARB_MIN_MCAP = int(os.getenv("VI_ARB_MIN_MCAP", "3300"))
# 정시 브리핑(KST 08~16시) 디스코드 발송 on/off
VI_ARB_HOURLY_BRIEFING = os.getenv("VI_ARB_HOURLY_BRIEFING", "true").lower() == "true"
VI_ARB_ORDER_QTY = int(os.getenv("VI_ARB_ORDER_QTY", "1"))          # 모의 주문 수량

# KR 뉴스 정리(interpreted) 레이어용 — 뉴스 소스(네이버) + LLM 가공(Gemini)
# 발급 안내: docs/kr-data-sources.md §2(네이버), §3(Gemini)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")  # 무료 tier 권장

# 뉴스 분석 LLM 백엔드 분기:
#   NEWS_LLM=gemini      → Gemini API (GEMINI_MODEL)
#   NEWS_LLM=claude_cli  → claude CLI 헤드리스 (NEWS_CLAUDE_MODEL: haiku|sonnet|opus)
# Gemini 무료 쿼터 소진 시 claude_cli 로 우회 가능
NEWS_LLM = os.getenv("NEWS_LLM", "gemini").lower()
NEWS_CLAUDE_MODEL = os.getenv("NEWS_CLAUDE_MODEL", "sonnet")  # 최신: haiku|sonnet(4.6)|opus(4.8)
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")

# Discord
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_APP_ID = os.getenv("DISCORD_APP_ID", "")
DISCORD_PUBLIC_KEY = os.getenv("DISCORD_PUBLIC_KEY", "")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
# VI 차익거래 체결 알림 전용 웹훅 (.env, 미설정 시 알림 안 보냄)
VI_ARB_DISCORD_WEBHOOK = os.getenv("VI_ARB_DISCORD_WEBHOOK", "")

# API 설정
API_HOST = os.getenv("TRAKIT_HOST", "0.0.0.0")
API_PORT = int(os.getenv("TRAKIT_PORT", "8000"))
CORS_ORIGINS = ["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173", "http://localhost:8080", "http://127.0.0.1:8080", "*"]
