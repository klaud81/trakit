#!/usr/bin/env bash
# 이미지를 로컬에서 빌드해 Docker Hub에 올리고, 서버는 받아서 실행만 한다.
#   scripts/deploy.sh            현재 HEAD를 빌드·배포
#   scripts/deploy.sh <tag>      이미 올린 태그로 되돌리기 (빌드 없음)
# 필요: 로컬·서버의 docker login, 서버 계정의 비밀번호 없는 sudo.
set -euo pipefail

SERVER="${TRAKIT_SERVER:-claudkim@49.50.139.64}"
REMOTE_DIR="${TRAKIT_REMOTE_DIR:-/root/git/trakit}"
REPO="${TRAKIT_IMAGE_REPO:-claudkim/trakit}"
PLATFORM="${TRAKIT_PLATFORM:-linux/amd64}"

cd "$(git rev-parse --show-toplevel)"

if [ $# -ge 1 ]; then
  TAG="$1"
  docker manifest inspect "$REPO-backend:$TAG" >/dev/null
  docker manifest inspect "$REPO-frontend:$TAG" >/dev/null
else
  if [ -n "$(git status --porcelain -- backend frontend)" ]; then
    echo "backend/ 또는 frontend/에 커밋되지 않은 변경이 있습니다. 태그와 이미지가 어긋나므로 중단합니다." >&2
    exit 1
  fi
  TAG="$(git rev-parse --short HEAD)"
  for service in backend frontend; do
    docker buildx build --platform "$PLATFORM" --push \
      -t "$REPO-$service:$TAG" -t "$REPO-$service:latest" "./$service"
  done
fi

ssh -o BatchMode=yes "$SERVER" bash -s -- "$REMOTE_DIR" "$TAG" <<'REMOTE'
set -euo pipefail
dir="$1"; tag="$2"
compose() { sudo -n env DOCKER_CONFIG="$HOME/.docker" TRAKIT_TAG="$tag" docker compose --project-directory "$dir" -f "$dir/docker-compose.yml" "$@"; }

# sudo가 표준 입력을 읽으면 이 스크립트의 나머지가 사라지므로 모두 /dev/null을 준다.
sudo -n git -C "$dir" pull --ff-only --quiet </dev/null
compose pull --quiet backend frontend </dev/null
compose up -d --no-build backend frontend </dev/null
# nginx는 시작할 때 upstream IP를 고정하므로, 컨테이너를 새로 만들면 다시 읽어야 한다.
docker exec trakit-nginx nginx -t </dev/null
docker exec trakit-nginx nginx -s reload </dev/null

code="$(curl -sk -o /dev/null -w '%{http_code}' --retry 15 --retry-all-errors --retry-delay 2 \
  --resolve trakit.stock-snow.com:443:127.0.0.1 https://trakit.stock-snow.com/)"
[ "$code" = 200 ] || { echo "상태 확인 실패: HTTP $code" >&2; exit 1; }
docker ps --format '{{.Names}} {{.Image}} {{.Status}}' | grep '^trakit-'
REMOTE
echo "배포 완료: $TAG"
