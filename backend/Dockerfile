# syntax=docker/dockerfile:1
FROM python:3.11-slim

# 뉴스 bias 분석용 claude CLI (NEWS_LLM=claude_cli) — Node 20 + @anthropic-ai/claude-code.
# 슬림 이미지엔 node/claude 가 없어 claude_cli 가 "No such file: 'claude'" 로 실패하던 것 해결.
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get purge -y --auto-remove gnupg \
    && rm -rf /var/lib/apt/lists/* /root/.npm \
    && claude --version
# CLI 헤드리스 위생: 자동업데이트·비필수 트래픽 끔. 인증은 런타임 env
# (ANTHROPIC_API_KEY 또는 CLAUDE_CODE_OAUTH_TOKEN) 로 주입 — .env 에 넣으면 됨.
ENV DISABLE_AUTOUPDATER=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

WORKDIR /app

COPY requirements.txt .
# BuildKit pip 캐시 마운트 — 재빌드(심지어 --no-cache)에도 휠 재다운로드 안 함.
# (--no-cache-dir 제거: 그게 켜져 있으면 매번 전부 재다운로드 → 느림)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefer-binary -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
