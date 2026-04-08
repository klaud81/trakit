"""Trakit FastAPI 앱

실행: cd backend && uvicorn app:app --reload --port 8000
"""
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router
from config import API_HOST, API_PORT, CORS_ORIGINS

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


@app.get("/")
async def root():
    return {"message": "Trakit API", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host=API_HOST, port=API_PORT, reload=True)
