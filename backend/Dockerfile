# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
# BuildKit pip 캐시 마운트 — 재빌드(심지어 --no-cache)에도 휠 재다운로드 안 함.
# (--no-cache-dir 제거: 그게 켜져 있으면 매번 전부 재다운로드 → 느림)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefer-binary -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
