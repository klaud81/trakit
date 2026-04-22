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
- `backend/services/` — portfolio, price, trade_calculator, backtesting, exchange_rate 서비스
- `frontend/src/App.jsx` — 메인 앱 (상태관리, 데이터 로딩, 주차 네비게이션, 해시 라우팅 `#tqqq` / `#news`)
- `frontend/src/components/` — UI 컴포넌트 (Header, Sidebar, SignalPanel, NewsPanel 등)
- `data/` — 로컬 CSV/TSV fallback 데이터

## 코드 수정 시 주의사항

### 백엔드
- 데이터 소스: Google Sheets가 기본 (`USE_GOOGLE_SHEETS=True`), 실패 시 로컬 CSV fallback. 캐시 5일 유효, `POST /api/refresh`로 강제 갱신
- Google Sheet ID: `1dI12c4AikkHMiT9dXRUhTCPxJwPA08IzBqAsl8zwUsM` (config.py)
- `date_range` 형식: `"2026/3/23-4/3"` — 연도 넘김(12월→1월) 처리 필요
- `week_num`: 문자열 ("258"). `week_label` ("258 주차")에서 추출
- 실시간 가격: KIS(한국투자증권) → yfinance → Yahoo API v8 → Yahoo quote 순서. 캐시 30초, KST 21~06시만 갱신
- KIS API 키: `backend/.env`에 저장 (`.gitignore` 포함). AWS Parameter Store(`/trakit/*`)에서 관리
- **시크릿 파일(.env, .pem, credentials)은 절대 커밋하지 않음**
- 캐시 저장 시 로그 출력: 가격(`💰`), 환율(`💱`), KIS 토큰(`🔑`), Google Sheets(`📊`)
- 서버 시작 시 KIS 모드(mock/real), URL, 앱키를 로그에 출력
- 로그 포맷: `2026-04-09T11:53:22+09:00 INFO name: message` (KST, ISO 8601)
- 환율: `exchange_rate_service.py` — 외부 API 조회, KST 17시 이후 하루 1회 갱신 캐시
- `chartPreviousClose`는 분할 조정값이므로 사용 금지. `previousClose` 또는 `closes[-2]` 사용
- 날짜 필터링: 시작일이 오늘 이후인 미래 데이터 자동 제외 (`_filter_by_date`)
- 뉴스 프록시: `/api/news`, `/api/news/detail/{id}` — `api.saveticker.com/api/news/list|detail` 을 서버측에서 호출 (브라우저 직접 호출 시 CORS 차단됨). 목록 60초 / 상세 5분 메모리 캐시. 실패 시 stale 캐시 반환
- saveticker 필터 파라미터: `label_group` (2=SAVE, 3=로이터, 4=파이낸셜뉴스), `label_name` (SAVE 하위: 1=전체, 2=종합, 3=속보, 4=정보, 5=분석, 6=암호화폐, 7=경제지표, 8=에너지, 9=연준, 10=일정, 11=투자의견), `sort=created_at_desc`

### 프론트엔드
- `week_num`은 숫자로 변환하여 사용 (차트 ReferenceLine 매칭)
- XAxis: `type="number"`, `domain=['dataMin', 'dataMax']`
- 가격 색상: 상승(+) 빨간색 `#E53935`, 하락(-) 파란색 `#1E88E5`
- 실시간 가격은 SignalPanel 내부에 표시 (↻ 새로고침 아이콘)
- 자동 갱신: `/api/config`에서 시간대/간격을 가져와 적용 (기본 KST 21~06시, 20초 간격)
- 마지막 주차: 실시간 가격으로 평가금/시그널 재계산. 이전 주차: 저장 데이터 사용
- 환율: `/api/exchange-rate`에서 가져와 PortfolioCard(원화 환산), ProgressCard(목표 금액) 적용
- API 실패 시 `demoData.js`로 fallback
- 레이아웃: `.app-shell` (flex) = `Sidebar` + `.app-content` (Header + `.main`). 사이드바는 full-height sticky, 로고 `TRAKIT` 포함. 접기/펼치기 토글 (64px ↔ 220px)
- 라우팅: `window.location.hash` 기반 (`#tqqq` / `#news`). `hashchange` 이벤트로 App.jsx의 `route` 상태와 Sidebar의 active 상태 동기화
- 뉴스 라우트(`#news`)에서는 Header / 후원하기 카드 숨김, 방문자 통계는 모든 라우트에 표시
- NewsPanel 필터: SOURCE_TABS (전체/SAVE/로이터/파이낸셜뉴스) 는 서버측 `label_group` 파라미터로 refetch. CATEGORIES_BY_TAB 은 클라이언트측 `tag_names` 필터 (전체 tab의 '분석' pill은 `분석` OR `시황/분석` 매칭). SAVE_CATEGORIES 는 서버측 `label_name` 파라미터로 refetch
- NewsDetailModal: 뉴스 행 클릭 → `/api/news/detail/{id}` 조회 → 모달 표시. 닫기: ✕ / 배경 클릭 / Escape. 본문은 `content[]` 의 text 블록을 `\n` 기준으로 단락 분할

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
| POST | `/api/visit` | 방문 기록 + 통계 반환 |
| GET | `/api/visitors` | 방문자 통계 (오늘/월간/누적) |
| POST | `/api/notify` | Discord 웹훅 알림 전송 |
| POST | `/api/refresh` | Google Sheets 데이터 강제 갱신 |
| POST | `/api/discord/interactions` | Discord 슬래시 명령어 처리 |
| GET | `/api/config` | 프론트엔드 설정 (갱신 시간대/간격) |
| GET | `/api/exchange-rate` | USD/KRW 환율 (KST 17시 이후 갱신) |
| GET | `/api/news` | 뉴스 목록 프록시 (saveticker, 60초 캐시). 파라미터: `page`, `page_size`, `label_group`, `label_name`, `sort` |
| GET | `/api/news/detail/{id}` | 뉴스 상세 프록시 (saveticker, 5분 캐시) |

상세: [docs/api-spec.md](docs/api-spec.md)

## 배포

- **로컬 개발**: `./start.sh` (Vite proxy: `/api` → `localhost:8000`)
- **Docker**: `docker compose up --build -d` (nginx proxy: `/api/` → `backend:8000`)
- **AWS**: `git pull && docker-compose build --no-cache && docker-compose up -d`
- API 호출은 항상 `/api` 상대경로 사용 (`frontend/src/utils/api.js`)
- 변경 미반영 시 `--no-cache` 옵션으로 재빌드
- 상세: [agents/cicd.md](agents/cicd.md)

## 테스트

```bash
cd backend && python -m pytest test/ -v  # 19개 API 테스트
```

테스트 파일: `backend/test/test_api.py` — FastAPI TestClient 기반
