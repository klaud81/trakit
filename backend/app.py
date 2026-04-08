"""Trakit FastAPI 앱

실행: cd backend && uvicorn app:app --reload --port 8000
"""
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router
from config import API_HOST, API_PORT, CORS_ORIGINS, KIS_MOCK, KIS_BASE_URL, KIS_APP_KEY

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt=LOG_DATEFMT)

# uvicorn 로거에도 동일 포맷 적용
for name in ["uvicorn", "uvicorn.access", "uvicorn.error"]:
    uv_logger = logging.getLogger(name)
    uv_logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT))
    uv_logger.addHandler(handler)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Trakit",
    description="TQQQ 밸류 리밸런싱 투자 추적 대시보드 API",
    version="0.1.0",
)

# CORS (프론트엔드 dev server에서 직접 호출 시 대비)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 라우터 (/api prefix)
app.include_router(router)

# 시작 로그
_mode = "모의투자(Mock)" if KIS_MOCK else "실전투자(Real)"
_key = KIS_APP_KEY[:10] + "..." if KIS_APP_KEY else "미설정"
logger.info(f"🚀 Trakit API 시작 — KIS: {_mode} | URL: {KIS_BASE_URL} | Key: {_key}")


@app.get("/")
async def root():
    return {"message": "Trakit API", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host=API_HOST, port=API_PORT, reload=True)
