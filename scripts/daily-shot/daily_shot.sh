#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# TQQQ 대시보드 일일 스샷 → Discord 로컬 cron 래퍼.
# launchd com.trakit.daily-shot 가 월~금 22:30 KST 에 fire.
# 전제: :5173(프론트) + :8000(백엔드) 가 그 시각에 떠 있어야 함 (없으면 캡처 실패 로그).
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# launchd 최소 PATH 보정 (node/npm/playwright 탐색)
export PATH="$HOME/.nvm/versions/node/v18.20.8/bin:/usr/local/bin:/usr/bin:/bin"

# 웹훅: backend/.env 에서 로드 (커밋 안 됨)
if [ -f backend/.env ]; then
  export DISCORD_WEBHOOK_URL="$(grep -E '^DISCORD_WEBHOOK_URL=' backend/.env | head -1 | cut -d= -f2- | tr -d '"'"'"' ')"
fi
# 전역 playwright index.js (ESM 디렉토리 import 불가 → 파일 경로)
export PW_PKG="$(npm root -g 2>/dev/null)/playwright/index.js"

LOGDIR="$ROOT/data/daily-shots"; mkdir -p "$LOGDIR"
LOG="$LOGDIR/cron.log"
echo "[$(date '+%F %T')] ▶ daily-shot 시작" >> "$LOG"
node scripts/daily-shot/shot.mjs >> "$LOG" 2>&1
rc=$?
echo "[$(date '+%F %T')] ■ 종료 rc=$rc" >> "$LOG"
exit $rc
