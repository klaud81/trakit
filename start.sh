#!/bin/bash
# TRAKIT - 백엔드 + 프론트엔드 동시 실행 스크립트
#
# 사용법: bash start.sh [mock|real]
#   mock  - 모의투자 API (기본값)
#   real  - 실전투자 API
# 종료: Ctrl+C

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_MODE="${1:-mock}"

echo "🚀 TRAKIT 시작... (모드: $ENV_MODE)"
echo ""

# 포트 사용 중이면 기존 프로세스 종료
for PORT in 8000 5173; do
  PIDS=$(lsof -ti :$PORT 2>/dev/null || true)
  if [ -n "$PIDS" ]; then
    echo "⚠️  포트 $PORT 사용 중 (PID: $PIDS) — 종료합니다."
    echo "$PIDS" | xargs kill -9 2>/dev/null || true
    while lsof -ti :$PORT >/dev/null 2>&1; do sleep 0.5; done
    echo "   ✅ 포트 $PORT 해제 완료"
  fi
done
echo ""

# 0. .env 로딩 (mock 또는 real)
ENV_FILE="$SCRIPT_DIR/backend/.env.$ENV_MODE"
if [ -f "$ENV_FILE" ]; then
  cp "$ENV_FILE" "$SCRIPT_DIR/backend/.env"
  echo "🔑 .env.$ENV_MODE → .env 로딩 완료"
else
  echo "⚠️  $ENV_FILE 파일이 없습니다. .env 없이 시작합니다."
fi
echo ""

# 1. Backend 의존성 확인 & 설치
echo "📦 Backend 의존성 설치..."
cd "$SCRIPT_DIR/backend"
pip install -r requirements.txt -q 2>/dev/null || pip install -r requirements.txt --break-system-packages -q 2>/dev/null || echo "⚠️  pip install 실패 - 수동으로 설치하세요"

# 2. Frontend 의존성 확인 & 설치
echo "📦 Frontend 의존성 설치..."
cd "$SCRIPT_DIR/frontend"
if [ ! -d "node_modules" ]; then
  npm install 2>/dev/null || echo "⚠️  npm install 실패 - 수동으로 설치하세요"
fi

# 3. Backend 실행 (백그라운드)
echo ""
echo "🔧 Backend 서버 시작 (port 8000)..."
cd "$SCRIPT_DIR/backend"
uvicorn app:app --reload --port 8000 &
BACKEND_PID=$!
echo "   PID: $BACKEND_PID"

# 4. Frontend 실행
echo "🎨 Frontend 서버 시작 (port 5173)..."
cd "$SCRIPT_DIR/frontend"
npm run dev &
FRONTEND_PID=$!
echo "   PID: $FRONTEND_PID"

echo ""
echo "✅ TRAKIT 실행 중!"
echo "   📊 대시보드: http://localhost:5173"
echo "   🔌 API 문서: http://localhost:8000/docs"
echo ""
echo "   종료하려면 Ctrl+C 를 누르세요."
echo ""

# Ctrl+C 시 둘 다 종료
trap "echo '종료 중...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" SIGINT SIGTERM
wait
