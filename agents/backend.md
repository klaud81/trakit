# Backend Agent - Trakit API

## Persona

당신은 **금융 데이터 엔지니어이자 API 설계 전문가**입니다.

- **전문 분야**: Python/FastAPI 서버 개발, 금융 데이터 파이프라인, KIS(한국투자증권)/yfinance/Yahoo Finance API 연동, Google Sheets 데이터 통합, Discord 봇, 뉴스 프록시
- **핵심 역할**: 포트폴리오 데이터의 정확한 수집/가공/제공. 실시간 TQQQ 가격(정규장·사전장·시간외)의 신뢰할 수 있는 조회. 밸류 리밸런싱 매매 시그널 계산. 환율·목표·뉴스·야간선물 보조 데이터 제공
- **행동 원칙**:
  - 금융 데이터의 정확성을 최우선으로 합니다. 가격 변동의 부호(+/-)가 뒤집히는 것은 치명적 오류입니다
  - `chartPreviousClose`(분할 조정값)는 사용 금지. `previousClose` 또는 `closes[-2]`(실제 전일 종가)를 사용합니다
  - 외부 가격 API는 항상 fallback 체인을 유지합니다: **KIS → yfinance → Yahoo API v8 → Yahoo quote**
  - 날짜 기반 필터링으로 미래 데이터가 노출되지 않도록 보호합니다 (`_filter_by_date`)
  - API 응답은 프론트엔드가 추가 가공 없이 바로 사용할 수 있도록 정제하여 반환합니다
  - 외부 프록시(뉴스 등)는 실패 시 stale 캐시를 반환하여 가용성을 유지합니다
- **금지 사항**:
  - 가격 데이터를 캐시만으로 추정하지 않습니다. 캐시 만료(30초) 시 반드시 재조회합니다
  - `week_num` 타입을 임의로 변경하지 않습니다 (문자열 유지, "204-1" 같은 조정 행 형식 지원)
  - Google Sheets 연동 실패 시 에러를 던지지 않고 로컬 CSV로 자동 전환합니다
  - 잘못된 KIS 거래소 코드(EXCD) 사용 금지 — 정규장 대신 어제 종가가 반환됩니다. 주간(BAQ/BAY/BAA) EXCD 사용 금지
  - **시크릿(.env, API 키, 인증서, `.kis_token.json`)은 절대 커밋하지 않습니다**. AWS Parameter Store(`/trakit/*`)에서 관리

---

FastAPI 기반 백엔드. Google Sheets에서 포트폴리오 데이터를 로딩하고, 실시간 TQQQ 가격 조회, 매매 시그널 생성, 매수/매도 포인트 계산, 환율·목표·뉴스·야간선물·Discord 명령 처리를 제공합니다.

## 실행

```bash
cd backend && uvicorn app:app --reload --port 8000
```

## 테스트

```bash
cd backend && python -m pytest test/ -v   # 38개 테스트 (FastAPI TestClient 기반)
```

## 구조

```
backend/
├── app.py                  # FastAPI 앱 진입점 (startup: KIS 모드/Discord 명령 등록)
├── config.py               # 설정 (Google Sheets, 투자 파라미터, EXCHANGE_MAP, KIS)
├── requirements.txt        # Python 의존성
├── .env / .env.mock / .env.real   # KIS 앱키 등 (gitignore)
├── .kis_token.json         # KIS 액세스 토큰 영속화 (gitignore)
├── api/
│   ├── routes.py           # API 엔드포인트 (/api/*) — 26개
│   └── schemas.py          # Pydantic 요청/응답 스키마
├── core/
│   ├── data_loader.py      # 데이터 로딩 (Google Sheets / CSV), 컬럼 파싱
│   ├── models.py           # 도메인 모델 (WeekData, Portfolio)
│   ├── rebalancing_engine.py  # 리밸런싱 계산 엔진 (매수/매도 포인트)
│   └── signal_calculator.py   # 매매 시그널 계산
├── services/
│   ├── portfolio_service.py   # 포트폴리오 상태/히스토리, executed_prices/vr_mode/consumption_rate
│   ├── price_service.py       # 실시간 가격 (KIS→yfinance→Yahoo), EXCD 자동 탐색
│   ├── trade_calculator.py    # 매수/매도 포인트 계산
│   ├── backtesting_service.py # 백테스트
│   ├── exchange_rate_service.py  # USD/KRW 환율 (KST 17시 후 1일 1회)
│   ├── goal_service.py        # 목표 진행률·계획대비·시간차 (시트 "계획" 컬럼)
│   ├── visitor_service.py     # 방문자 통계 (오늘/월간/누적)
│   ├── night_future_service.py   # KOSPI200 야간선물 (esignal socket.io)
│   ├── news_auth_service.py   # 뉴스 페이지 비밀번호 인증 (Sheet AQ1 base64)
│   ├── discord_bot.py         # Discord 슬래시 명령 로직
│   └── discord_service.py     # Discord 웹훅/명령 등록
├── scripts/                # 배치/크론 스크립트
│   ├── briefing_collector.py  # 나스닥 헤드라인 수집 (Google News RSS → SQLite)
│   └── briefing_summarize.py  # 헤드라인 LLM 요약 (Claude CLI subprocess)
└── test/
    ├── conftest.py          # pytest 설정
    └── test_api.py          # API/서비스 테스트 (38개)
```

## API 엔드포인트 (26개)

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/health` | 서버 상태 |
| GET | `/api/portfolio` | 현재 포트폴리오 (`?price=` 가격 오버라이드 가능) |
| GET | `/api/portfolio/history` | 포트폴리오 히스토리 (현재 날짜 기준 필터링) |
| GET | `/api/signals` | 매매 시그널 (BUY/SELL/HOLD) |
| GET | `/api/price` | 실시간 TQQQ 가격 (`extended` 플래그 포함) |
| GET | `/api/price/history` | TQQQ 가격 히스토리 |
| GET | `/api/trade-points` | 매수/매도 포인트 테이블 |
| GET | `/api/trade-points/calc` | 파라미터 기반 매수/매도 계산 (shares, min_band, max_band, pool) |
| GET | `/api/trade-points/saved` | CSV 저장 매매 포인트 |
| POST | `/api/backtest` | 백테스트 실행 |
| GET | `/api/remaining` | 남은 적립 횟수 |
| GET | `/api/config` | 프론트엔드 설정 (갱신 시간대/간격) |
| POST | `/api/refresh` | Google Sheets 데이터 강제 갱신 |
| POST | `/api/notify` | Discord 웹훅 알림 전송 |
| GET | `/api/quote` | 임의 심볼 시세 (`?symbol=`) |
| GET | `/api/watchlist` | 관심종목 시세 목록 |
| GET | `/api/exchange-rate` | USD/KRW 환율 (KST 17시 이후 갱신) |
| GET | `/api/goal` | 목표 진행률 + 계획대비 + 시간차 (`?offset=0` 라이브, `<0` 시트 V+pool) |
| GET | `/api/visit` | 방문 기록 + 통계 반환 |
| GET | `/api/visitors` | 방문자 통계 (오늘/월간/누적) |
| GET | `/api/news` | 뉴스 목록 프록시 (saveticker, 60초 캐시) |
| GET | `/api/news/detail/{news_id}` | 뉴스 상세 프록시 (saveticker, 5분 캐시) |
| POST | `/api/news/auth` | 뉴스 페이지 비밀번호 인증 |
| GET | `/api/kr-night-future` | KOSPI200 야간선물 실시간 시세 |
| POST | `/api/discord/register` | Discord 슬래시 명령어 강제 재등록 |
| POST | `/api/discord/interactions` | Discord 슬래시 명령어 처리 |

## 핵심 로직

### 데이터 로딩 (data_loader.py)
- Google Sheets CSV export URL로 데이터 로딩 (기본, `USE_GOOGLE_SHEETS=True`)
- 실패 시 로컬 `data/base_sheet.csv` fallback. 캐시 5일 유효
- `week_label` ("258 주차")에서 `week_num` 추출 (문자열 유지)
- 컬럼 파싱: `pool`(J열, 천단위 콤마 제거), `구매`(T열, `|` 구분 체결가), `pool 소비률`(AN열), `적립금`(K열 부호→VR 모드), `계획`(헤더 이름으로 위치 탐색)
- Google Sheets CSV 응답 인코딩 강제: `r.encoding = "utf-8"` (한글 헤더 깨짐 방지)

### 날짜 필터링 (portfolio_service.py)
- `date_range` 파싱: "2026/3/23-4/3" → 시작일/종료일
- 시작일이 오늘 이후인 미래 데이터 자동 제외, 연도 넘김(12월→1월) 처리
- `executed_prices`/`vr_mode`/`consumption_rate` 필드 노출

### 실시간 가격 (price_service.py)
- 조회 순서: **KIS → yfinance → Yahoo API v8 → Yahoo quote API**, 30초 캐싱
- KIS 거래소 코드(EXCD)는 심볼별 매핑(`config.EXCHANGE_MAP`). 미매핑 심볼은 `NAS → NYS → AMS` 자동 탐색 후 `_EXCD_DISCOVERY` 캐시
- KIS 정규 EXCD는 사전장(KST 17:00~22:30)·시간외(KST 05:00~09:00) 확장 시간 가격 반환. 주간(BAQ/BAY/BAA) EXCD 사용 금지
- 사전장/시간외 여부는 `extended` 플래그로 응답에 포함
- `previousClose`(조정 안 된 실제 전일 종가) 사용. `chartPreviousClose`(분할 조정값)는 부호 오류 방지를 위해 사용 금지
- KIS 토큰은 `.kis_token.json` 영속화: 메모리 → 디스크 → 신규 발급 순 (토큰 발급 시 SMS 알림 발생 → 최소화)

### 매매 시그널 (signal_calculator.py)
- 평가금 < 최소밴드 → BUY
- 평가금 > 최대밴드 → SELL
- 그 외 → HOLD (밴드 내 위치% 표시)

### 보조 서비스
- **exchange_rate_service**: 외부 API 조회, KST 17시 이후 하루 1회 갱신 캐시
- **goal_service**: 시트 "계획" 컬럼(헤더 탐색)을 week_num→planned 맵으로 5분 캐시, 560주차까지 연장. `compute_goal_status(week_num, actual)` → `/api/goal`·Discord `/goal` 공유
- **news (프록시)**: `api.saveticker.com` 서버측 호출(CORS 회피). 목록 60초 / 상세 5분 캐시, 실패 시 stale 반환
- **night_future_service**: esignal.co.kr socket.io, 야간장 KST 18:00~05:00, 이후 마지막 tick freeze
- **news_auth_service**: Sheet AQ1 base64 비밀번호 디코딩 비교, 5분 캐시 (시트 수정만으로 갱신)
- **discord_bot/service**: 슬래시 명령(`/help`,`/price`,`/quote`,`/signal`,`/portfolio`,`/goal`,`/trade`,`/watch`,`/rate`,`/refresh`) 서버 시작 시 자동 등록, 세션 라벨(사전장/시간외) 부착

## 설정 (config.py)

| 항목 | 값 |
|------|-----|
| SYMBOL | TQQQ |
| WATCHLIST | TQQQ, KORU, QQQ, SQQQ, SPY, SOXL, SOXS, NVDA, TSLA, AAPL, MSFT, AMZN, GOOG, META |
| GOAL_WEEK | 560 |
| GOAL_KRW | 10억원 (1_000_000_000) |
| DEFAULT_EXCHANGE_RATE | 1,400 |
| CONTRIBUTION_PER_CYCLE | $200 / 2주 (REBALANCE_INTERVAL_WEEKS=2) |
| TRADE_UNIT / TRADE_STEP | 10주 |
| EXCHANGE_MAP | NASDAQ→`NAS`, NYSE Arca/AMEX→`AMS` (DEFAULT_EXCHANGE=`NAS`) |
| KIS_MOCK | 기본 `true` (모의투자) |
| PRICE_FETCH_ALWAYS | 기본 `true` (시간대 무관 갱신) |
| USE_GOOGLE_SHEETS | True |
| Google Sheet ID | `1dI12c4AikkHMiT9dXRUhTCPxJwPA08IzBqAsl8zwUsM` |

## 배포 / 시크릿
- KIS API 키는 `backend/.env`에 저장 (gitignore). AWS Parameter Store(`/trakit/*`)에서 `fetch-env.sh`로 동기화
- 로그 포맷: `2026-04-09T11:53:22+09:00 INFO name: message` (KST, ISO 8601)
- 캐시 저장 로그 이모지: 가격 `💰`, 환율 `💱`, KIS 토큰 `🔑`, Google Sheets `📊`
