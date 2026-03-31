# CLAUDE.md - Trakit

## 프로젝트 개요

TQQQ 밸류 리밸런싱 투자 추적 대시보드. FastAPI(백엔드) + React/Vite(프론트엔드).

## 빌드 & 실행

```bash
# 백엔드
cd backend && uvicorn app:app --reload --port 8000

# 프론트엔드
cd frontend && npm run dev

# 테스트
cd backend && python -m pytest test/ -v
```

## 디렉토리 구조

- `backend/` — FastAPI 서버. 진입점: `app.py`, 설정: `config.py`
- `backend/api/routes.py` — 모든 API 엔드포인트 (`/api/*`)
- `backend/core/data_loader.py` — Google Sheets / CSV 데이터 로딩
- `backend/services/` — portfolio, price, trade_calculator, backtesting 서비스
- `frontend/src/App.jsx` — 메인 앱 (상태관리, 데이터 로딩, 주차 네비게이션)
- `frontend/src/components/` — UI 컴포넌트 (Header, SignalPanel, EquityChart 등)
- `data/` — 로컬 CSV/TSV fallback 데이터

## 코드 수정 시 주의사항

### 백엔드
- 데이터 소스: Google Sheets가 기본 (`USE_GOOGLE_SHEETS=True`), 실패 시 로컬 CSV fallback
- Google Sheet ID: `1dI12c4AikkHMiT9dXRUhTCPxJwPA08IzBqAsl8zwUsM` (config.py)
- `date_range` 형식: `"2026/3/23-4/3"` — 연도 넘김(12월→1월) 처리 필요
- `week_num`: 문자열 ("258"). `week_label` ("258 주차")에서 추출
- 실시간 가격: yfinance `fast_info` → Yahoo API v8 → Yahoo quote 순서
- `chartPreviousClose`는 분할 조정값이므로 사용 금지. `previousClose` 또는 `closes[-2]` 사용
- 날짜 필터링: 시작일이 오늘 이후인 미래 데이터 자동 제외 (`_filter_by_date`)

### 프론트엔드
- `week_num`은 숫자로 변환하여 사용 (차트 ReferenceLine 매칭)
- XAxis: `type="number"`, `domain=['dataMin', 'dataMax']`
- 가격 색상: 상승(+) 빨간색 `#E53935`, 하락(-) 파란색 `#1E88E5`
- 실시간 가격은 SignalPanel 내부에 표시 (↻ 새로고침 아이콘, 30초 자동 갱신)
- 마지막 주차: 실시간 가격으로 평가금/시그널 재계산. 이전 주차: 저장 데이터 사용
- API 실패 시 `demoData.js`로 fallback

### 디자인 (Pencil)
- .pen 파일은 Pencil MCP 도구로만 읽기/수정 (Read/Grep 사용 금지)
- 디자인 변수는 CSS 변수와 동일한 네이밍 (`--bg`, `--card`, `--primary` 등)

## API 엔드포인트 요약

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/portfolio` | 현재 포트폴리오 (?price= 오버라이드 가능) |
| GET | `/api/portfolio/history` | 히스토리 (날짜 필터링 적용) |
| GET | `/api/signals` | 매매 시그널 BUY/SELL/HOLD |
| GET | `/api/price` | 실시간 TQQQ 가격 |
| GET | `/api/trade-points` | 매수/매도 포인트 |
| GET | `/api/trade-points/calc` | 파라미터 기반 계산 (shares, min_band, max_band, pool) |
| GET | `/api/remaining` | 남은 적립 횟수 |

상세: [docs/api-spec.md](docs/api-spec.md)

## 테스트

```bash
cd backend && python -m pytest test/ -v  # 18개 API 테스트
```

테스트 파일: `backend/test/test_api.py` — FastAPI TestClient 기반
